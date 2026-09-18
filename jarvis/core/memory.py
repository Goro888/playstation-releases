"""Long-term memory for JARVIS.

Three independent stores in one SQLite file:

* ``facts``        — durable knowledge (user preferences, projects, people, notes)
* ``conversations``— rolling transcript of every session
* ``tasks``        — to-dos / reminders the assistant promised to track

Full-text search uses SQLite FTS5 when available and degrades to ``LIKE``
queries otherwise. Optional vector recall is wired through Ollama embeddings
(``memory.embeddings: true``) for semantic "what did we discuss last week"
queries; it is off by default so the base system stays dependency-free.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..config import MemoryConfig

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL DEFAULT 'note',
    subject      TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL,
    tags         TEXT NOT NULL DEFAULT '',
    importance   INTEGER NOT NULL DEFAULT 3,
    source       TEXT NOT NULL DEFAULT 'user',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id, ts);

CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    notes      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'open',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS prefs (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS embeddings (
    fact_id  INTEGER PRIMARY KEY,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vector   BLOB NOT NULL
);
"""

FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    subject, content, tags, content='facts', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, subject, content, tags)
    VALUES (new.id, new.subject, new.content, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content, tags)
    VALUES ('delete', old.id, old.subject, old.content, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, subject, content, tags)
    VALUES ('delete', old.id, old.subject, old.content, old.tags);
    INSERT INTO facts_fts(rowid, subject, content, tags)
    VALUES (new.id, new.subject, new.content, new.tags);
END;
"""


@dataclass
class Fact:
    id: int
    kind: str
    subject: str
    content: str
    tags: str
    importance: int
    source: str
    created_at: float
    updated_at: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["created_at_human"] = _human(self.created_at)
        return d


class Memory:
    """Thread-safe SQLite-backed memory store."""

    def __init__(self, cfg: MemoryConfig, *, embed_fn=None) -> None:
        self.cfg = cfg
        self.path = Path(cfg.db_path).expanduser()
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._fts = False
        self._embed_fn = embed_fn  # async callable(text) -> list[float]
        with self._lock:
            self._conn.executescript(SCHEMA)
            try:
                self._conn.executescript(FTS_SCHEMA)
                self._fts = True
            except sqlite3.Error:  # pragma: no cover - no FTS5 build
                self._fts = False
            self._conn.commit()

    # ------------------------------------------------------------------ facts
    def remember(
        self,
        content: str,
        *,
        kind: str = "note",
        subject: str = "",
        tags: str | Sequence[str] = "",
        importance: int = 3,
        source: str = "user",
    ) -> Fact:
        content = (content or "").strip()
        if not content:
            raise ValueError("cannot remember an empty fact")
        if isinstance(tags, (list, tuple)):
            tags = ",".join(str(t) for t in tags)
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO facts (kind, subject, content, tags, importance, source, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (kind, subject, content, str(tags), int(importance), source, now, now),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM facts WHERE id=?", (cur.lastrowid,)).fetchone()
        return Fact(**dict(row))

    def forget(self, fact_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            self._conn.execute("DELETE FROM embeddings WHERE fact_id=?", (fact_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def recall(self, query: str, limit: int | None = None, kind: str | None = None) -> List[Fact]:
        query = (query or "").strip()
        limit = limit or self.cfg.recall_limit
        if not query:
            return self.recent(limit)
        with self._lock:
            rows: List[sqlite3.Row] = []
            if self._fts:
                safe = _fts_query(query)
                if safe:
                    try:
                        sql = """SELECT f.* FROM facts_fts ft JOIN facts f ON f.id = ft.rowid
                                 WHERE facts_fts MATCH ? ORDER BY bm25(facts_fts), f.updated_at DESC LIMIT ?"""
                        rows = list(self._conn.execute(sql, (safe, limit)).fetchall())
                    except sqlite3.Error:
                        rows = []
            if not rows:
                like = f"%{query}%"
                rows = list(
                    self._conn.execute(
                        """SELECT * FROM facts WHERE content LIKE ? OR subject LIKE ? OR tags LIKE ?
                           ORDER BY importance DESC, updated_at DESC LIMIT ?""",
                        (like, like, like, limit),
                    ).fetchall()
                )
        facts = [Fact(**dict(r)) for r in rows]
        if kind:
            facts = [f for f in facts if f.kind == kind]
        return facts

    def recent(self, limit: int = 10, kind: str | None = None) -> List[Fact]:
        with self._lock:
            if kind:
                rows = self._conn.execute(
                    "SELECT * FROM facts WHERE kind=? ORDER BY updated_at DESC LIMIT ?", (kind, limit)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM facts ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [Fact(**dict(r)) for r in rows]

    # ---------------------------------------------------------- conversations
    def add_message(self, role: str, content: str, session_id: str = "default") -> None:
        if not self.cfg.store_conversations:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO conversations (session_id, role, content, ts) VALUES (?,?,?,?)",
                (session_id, role, content, time.time()),
            )
            self._conn.commit()

    def history(self, limit: int | None = None, session_id: str = "default") -> List[Dict[str, Any]]:
        limit = limit or self.cfg.history_limit
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, ts FROM conversations WHERE session_id=? ORDER BY ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in reversed(rows)]

    def sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT session_id, COUNT(*) n, MAX(ts) last FROM conversations
                   GROUP BY session_id ORDER BY last DESC LIMIT 20"""
            ).fetchall()
        return [{"session_id": r["session_id"], "messages": r["n"], "last": r["last"]} for r in rows]

    def clear_conversation(self, session_id: str = "default") -> None:
        with self._lock:
            self._conn.execute("DELETE FROM conversations WHERE session_id=?", (session_id,))
            self._conn.commit()

    # ------------------------------------------------------------------ tasks
    def add_task(self, title: str, notes: str = "") -> Dict[str, Any]:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tasks (title, notes, status, created_at, updated_at) VALUES (?,?, 'open', ?, ?)",
                (title, notes, now, now),
            )
            self._conn.commit()
            return {"id": cur.lastrowid, "title": title, "notes": notes, "status": "open"}

    def list_tasks(self, status: str = "open") -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        return [dict(r) for r in rows]

    def complete_task(self, task_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='done', updated_at=? WHERE id=?", (time.time(), task_id)
            )
            self._conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------ prefs
    def set_pref(self, key: str, value: Any) -> None:
        payload = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO prefs (key, value, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, payload, time.time()),
            )
            self._conn.commit()

    def get_pref(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM prefs WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError):
            return row["value"]

    def all_prefs(self) -> Dict[str, Any]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM prefs").fetchall()
        out: Dict[str, Any] = {}
        for r in rows:
            try:
                out[r["key"]] = json.loads(r["value"])
            except (TypeError, ValueError):
                out[r["key"]] = r["value"]
        return out

    # ------------------------------------------------------------- embeddings
    def set_embedding(self, fact_id: int, model: str, vector: Sequence[float]) -> None:
        blob = _pack(vector)
        with self._lock:
            self._conn.execute(
                "INSERT INTO embeddings (fact_id, model, dim, vector) VALUES (?,?,?,?) "
                "ON CONFLICT(fact_id) DO UPDATE SET model=excluded.model, dim=excluded.dim, vector=excluded.vector",
                (fact_id, model, len(vector), blob),
            )
            self._conn.commit()

    def semantic_recall(self, query_vector: Sequence[float], limit: int = 5) -> List[Fact]:
        """Brute-force cosine similarity over stored vectors (small stores)."""
        with self._lock:
            rows = self._conn.execute("SELECT fact_id, vector FROM embeddings").fetchall()
        scored = []
        for r in rows:
            vec = _unpack(r["vector"])
            if len(vec) != len(query_vector):
                continue
            scored.append((_cosine(vec, query_vector), r["fact_id"]))
        scored.sort(reverse=True)
        facts = []
        for score, fid in scored[:limit]:
            if score <= 0.2:
                continue
            with self._lock:
                row = self._conn.execute("SELECT * FROM facts WHERE id=?", (fid,)).fetchone()
            if row:
                f = Fact(**dict(row))
                facts.append(f)
        return facts

    # ----------------------------------------------------------------- misc
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            facts = self._conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"]
            turns = self._conn.execute("SELECT COUNT(*) c FROM conversations").fetchone()["c"]
            tasks = self._conn.execute("SELECT COUNT(*) c FROM tasks WHERE status='open'").fetchone()["c"]
            prefs = self._conn.execute("SELECT COUNT(*) c FROM prefs").fetchone()["c"]
            embeddings = self._conn.execute("SELECT COUNT(*) c FROM embeddings").fetchone()["c"]
        return {
            "facts": facts,
            "conversation_turns": turns,
            "open_tasks": tasks,
            "preferences": prefs,
            "embeddings": embeddings,
            "fts_enabled": self._fts,
            "db_path": str(self.path),
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fts_query(raw: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression."""
    tokens = re.findall(r"[\w\u0600-\u06FF]+", raw)
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens[:8])


def _human(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _pack(vec: Iterable[float]) -> bytes:
    import struct

    values = list(vec)
    return struct.pack(f"<{len(values)}f", *values)


def _unpack(blob: bytes) -> List[float]:
    import struct

    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
