"""The offline brain — JARVIS without any LLM installed.

This backend exists so the assistant is useful on a clean machine: it maps
bilingual (English / Arabic) phrasing directly onto the same tool schemas the
LLM uses, then narrates the results. It is also the automatic fallback when
Ollama is not running or no model has been pulled yet, so the HUD, the tool
layer, memory and permissions all stay exercisable during setup.

It is intentionally *not* a replacement for Qwen — it is a safety net.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Pattern, Sequence

from ..config import PersonaConfig
from .base import Message, ModelBackend, ModelReply, ToolCall

ARABIC_RE = re.compile(r"[\u0600-\u06FF]")


def is_arabic(text: str) -> bool:
    return bool(ARABIC_RE.search(text or ""))


@dataclass
class Intent:
    name: str
    tool: str
    pattern: Pattern[str]
    build: Callable[[re.Match], Dict[str, Any]]
    allow_empty: bool = False

    def match(self, text: str) -> Optional[re.Match]:
        return self.pattern.search(text)


def _clean_target(raw: str) -> str:
    raw = (raw or "").strip()
    raw = re.sub(r"^(the|a|an)\s+", "", raw, flags=re.I)
    for tail in (" please", " for me", " now", " app", " application", " من فضلك", " لو سمحت", " الآن"):
        if raw.lower().endswith(tail):
            raw = raw[: -len(tail)]
    return raw.strip(" .!?؟،,\"'")


def _after(text: str, *markers: str) -> str:
    low = text.lower()
    for m in markers:
        idx = low.find(m)
        if idx >= 0:
            return _clean_target(text[idx + len(m) :])
    return ""


_PREPOSITIONS = (
    "in the ",
    "in ",
    "inside ",
    "under ",
    "within ",
    "from ",
    "at ",
    "on ",
    "of ",
    "for ",
    "about ",
    "الخاصة بـ ",
    "في ",
    "عن ",
    "من ",
    "حول ",
)


def _strip_preposition(raw: str) -> str:
    """Drop a leading preposition: 'in jarvis' -> 'jarvis'."""
    text = _clean_target(raw)
    low = text.lower()
    for prep in _PREPOSITIONS:
        if low.startswith(prep):
            return _clean_target(text[len(prep) :])
    return text


# --------------------------------------------------------------------------
# intent table (ordered — first match wins)
# --------------------------------------------------------------------------
INTENTS: List[Intent] = [
    # --- files & folders ------------------------------------------------
    Intent(
        "list_directory",
        "list_directory",
        re.compile(
            r"(?:list|show|open)\s+(?:the\s+)?(?:files|contents(?:\s+of)?|folder|directory)\s*(.+)?"
            r"|اعرض\s+(?:ملفات|محتويات)?\s*(.+)?|افتح\s+المجلد\s*(.+)?",
            re.I,
        ),
        lambda m: {"path": _strip_preposition(m.group(1) or m.group(2) or m.group(3) or "~")},
    ),
    Intent(
        "read_file",
        "read_file",
        re.compile(
            r"(?:read|show|open|cat)\s+(?:the\s+)?file\s+(.+)|اقرأ\s+(?:الملف\s+)?(.+)|اعرض\s+الملف\s+(.+)", re.I
        ),
        lambda m: {"path": _clean_target(m.group(1) or m.group(2) or m.group(3))},
    ),
    Intent(
        "delete_file",
        "delete_file",
        re.compile(
            r"(?:delete|remove|trash)\s+(?:the\s+)?file\s+(.+)|احذف\s+(?:الملف\s+)?(.+)", re.I
        ),
        lambda m: {"path": _clean_target(m.group(1) or m.group(2))},
    ),
    Intent(
        "search_files",
        "search_files",
        re.compile(
            r"(?:find|search(?:\s+for)?|locate)\s+(?:the\s+)?file[s]?\s+(?:named\s+|called\s+)?(.+)"
            r"|ابحث\s+عن\s+ملف\s+(.+)|جد\s+ملف\s+(.+)",
            re.I,
        ),
        lambda m: {"pattern": _strip_preposition(m.group(1) or m.group(2) or m.group(3))},
    ),
    # --- screen & vision -------------------------------------------------
    Intent(
        "analyze_screen",
        "analyze_screen",
        re.compile(
            r"(?:what(?:'s| is)\s+(?:on|in)\s+my\s+screen|analyze|analyse|describe)\s*(?:my\s+)?(?:screen)?"
            r"|ماذا\s+(?:على|في)\s+الشاشة|حلل\s+الشاشة|اشرح\s+الشاشة",
            re.I,
        ),
        lambda m: {"question": ""},
        allow_empty=True,
    ),
    Intent(
        "capture_screen",
        "capture_screen",
        re.compile(r"(?:take\s+)?(?:a\s+)?screenshot|لقطة\s+شاشة|صورة\s+(?:ال)?شاشة|التقط\s+الشاشة", re.I),
        lambda m: {},
    ),
    # --- web -------------------------------------------------------------
    Intent(
        "web_search",
        "web_search",
        re.compile(
            r"(?:search(?:\s+the\s+web|\s+online)?|google|look\s+up|find\s+out)\s+(?:for\s+|about\s+)?(.+)"
            r"|ابحث\s+(?:في\s+الإنترنت\s+)?(?:عن\s+)?(.+)|دور\s+على\s+(.+)",
            re.I,
        ),
        lambda m: {"query": _strip_preposition(m.group(1) or m.group(2) or m.group(3))},
    ),
    Intent(
        "fetch_url",
        "fetch_url",
        re.compile(r"((?:https?://|www\.)\S+)", re.I),
        lambda m: {"url": m.group(1).rstrip(".,;")},
    ),
    # --- memory ----------------------------------------------------------
    # "recall" must be tested before "remember": "what do you remember about X"
    # contains the word "remember" but is a recall request.
    Intent(
        "recall",
        "recall",
        re.compile(
            r"(?:what\s+do\s+you\s+(?:know|remember)|do\s+you\s+remember|recall|remind\s+me\s+about)\s*(.+)?"
            r"|ماذا\s+تتذكر(?:\s+عن\s+(.+))?|هل\s+تتذكر\s*(.+)?|اذكر\s+(.+)",
            re.I,
        ),
        lambda m: {"query": _strip_preposition(m.group(1) or m.group(2) or m.group(3) or m.group(4) or "")},
        allow_empty=True,
    ),
    Intent(
        "remember",
        "remember",
        re.compile(
            r"^(?:remember|note(?:\s+that)?|keep\s+in\s+mind|don'?t\s+forget)\s+(?:that\s+)?(.+)"
            r"|^تذكر\s+(?:أن\s+)?(.+)|^احفظ\s+(.+)",
            re.I,
        ),
        lambda m: {"content": _clean_target(m.group(1) or m.group(2) or m.group(3))},
    ),
    Intent(
        "add_task",
        "add_task",
        re.compile(
            r"(?:add\s+(?:a\s+)?task|remind\s+me\s+to|todo|to-?do)\s+(.+)|ذكرني\s+(?:أن\s+)?(.+)|أضف\s+مهمة\s+(.+)",
            re.I,
        ),
        lambda m: {"title": _clean_target(m.group(1) or m.group(2) or m.group(3))},
    ),
    Intent(
        "list_tasks",
        "list_tasks",
        re.compile(r"(?:list|show|my)\s+tasks?|what(?:'s|\s+is)\s+on\s+my\s+(?:list|todo)|مهامي|اعرض\s+المهام", re.I),
        lambda m: {},
    ),
    # --- apps & system ----------------------------------------------------
    Intent(
        "close_application",
        "close_application",
        re.compile(
            r"(?:close|quit|kill|exit|stop|end)\s+(?:the\s+)?(.+?)(?:\s+app|\s+application)?$"
            r"|أغلق\s+(.+)|اقفل\s+(.+)|انه\s+(.+)",
            re.I,
        ),
        lambda m: {"name": _clean_target(m.group(1) or m.group(2) or m.group(3) or m.group(4))},
    ),
    Intent(
        "open_application",
        "open_application",
        re.compile(
            r"(?:open|launch|start|run)\s+(?:the\s+)?(.+?)(?:\s+app|\s+application)?$"
            r"|افتح\s+(.+)|شغّل\s+(.+)|شغل\s+(.+)",
            re.I,
        ),
        lambda m: {"name": _clean_target(m.group(1) or m.group(2) or m.group(3) or m.group(4))},
    ),
    Intent(
        "list_processes",
        "list_processes",
        re.compile(
            r"(?:list|show|what(?:'s|\s+is))\s+(?:the\s+)?(?:running\s+)?(?:processes|apps|applications|tasks)"
            r"|اعرض\s+العمليات|ما\s+هي\s+البرامج|العمليات",
            re.I,
        ),
        lambda m: {"limit": 12},
    ),
    Intent(
        "system_status",
        "system_status",
        re.compile(
            r"(?:system|machine|pc|computer)\s+(?:status|info|health|performance)"
            r"|(?:how(?:'s|\s+is)\s+my\s+(?:pc|computer|machine|system))"
            r"|(?:cpu|ram|memory|disk)\s+(?:usage|status|load)"
            r"|حالة\s+(?:الجهاز|النظام)|أداء\s+الجهاز|الذاكرة|المعالج",
            re.I,
        ),
        lambda m: {},
    ),
    Intent(
        "get_time",
        "get_time",
        re.compile(
            r"(?:what(?:'s|\s+is)\s+the\s+)?(?:current\s+)?(?:time|date|day)(?:\s+is\s+it)?"
            r"|الساعة(?:\s+كم)?|كم\s+الساعة|ما\s+(?:هو\s+)?(?:التاريخ|اليوم)|التاريخ",
            re.I,
        ),
        lambda m: {},
    ),
    Intent(
        "list_windows",
        "list_windows",
        re.compile(r"(?:list|show)\s+(?:the\s+)?(?:open\s+)?windows|النوافذ|اعرض\s+النوافذ", re.I),
        lambda m: {},
    ),
    Intent(
        "focus_window",
        "focus_window",
        re.compile(
            r"(?:focus|switch\s+to|bring\s+up)\s+(?:the\s+)?window\s+(.+)|ركز\s+على\s+(.+)|انتقل\s+إلى\s+(.+)", re.I
        ),
        lambda m: {"title": _strip_preposition(m.group(1) or m.group(2) or m.group(3))},
    ),
    Intent(
        "type_text",
        "type_text",
        re.compile(r"(?:type|write|enter)\s+(?:the\s+)?(?:text\s+)?[\"'](.+?)[\"']$", re.I),
        lambda m: {"text": m.group(1)},
    ),
    Intent(
        "get_clipboard",
        "get_clipboard",
        re.compile(r"(?:read|get|show)\s+(?:the\s+)?clipboard|what(?:'s|\s+is)\s+(?:on|in)\s+my\s+clipboard|الحافظة", re.I),
        lambda m: {},
    ),
]


# --------------------------------------------------------------------------
# narration templates
# --------------------------------------------------------------------------
def _done_templates(arabic: bool) -> Dict[str, str]:
    if arabic:
        return {
            "open_application": "تم فتح {name}.",
            "close_application": "تم إغلاق {name}.",
            "capture_screen": "التقطت صورة للشاشة: {path}",
            "remember": "حفظت في الذاكرة: {content}",
            "add_task": "أضفت المهمة: {title}",
            "delete_file": "تم حذف الملف {path}.",
            "write_file": "كتبت الملف {path}.",
        }
    return {
        "open_application": "Opened {name}.",
        "close_application": "Closed {name}.",
        "capture_screen": "Screenshot captured: {path}",
        "remember": "Remembered: {content}",
        "add_task": "Task added: {title}",
        "delete_file": "Deleted {path}.",
        "write_file": "Wrote {path}.",
    }


class OfflineBrain(ModelBackend):
    """Deterministic intent → tool-call brain with templated narration."""

    name = "offline"
    supports_tools = True
    supports_vision = False

    def __init__(self, persona: PersonaConfig, tool_names: Sequence[str] = ()) -> None:
        self.persona = persona
        self.tool_names = set(tool_names)
        self.model = "offline-intent-matcher"

    def set_tools(self, tool_names: Sequence[str]) -> None:
        self.tool_names = set(tool_names)

    async def available(self) -> bool:
        return True

    # ------------------------------------------------------------------
    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> ModelReply:
        # Collect tool results waiting to be narrated.
        pending_results = [m for m in messages if m.role == "tool"]
        if pending_results:
            return ModelReply(content=self.narrate(messages), backend=self.name, model=self.model)

        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if last_user is None:
            return ModelReply(content="", backend=self.name, model=self.model)

        text = (last_user.content or "").strip()
        call = self.route(text)
        if call is None:
            return ModelReply(content=self.fallback(text), backend=self.name, model=self.model)
        return ModelReply(content="", tool_calls=[call], backend=self.name, model=self.model)

    # ------------------------------------------------------------------
    def route(self, text: str) -> Optional[ToolCall]:
        """Map a user utterance onto a tool call, or ``None``."""
        lowered = text.strip()
        if not lowered:
            return None
        for intent in INTENTS:
            m = intent.match(lowered)
            if not m:
                continue
            if intent.tool not in self.tool_names:
                continue
            try:
                args = intent.build(m) or {}
            except Exception:  # pragma: no cover - defensive
                args = {}
            if _missing_required(args) and not intent.allow_empty:
                continue
            return ToolCall(id="offline_1", name=intent.tool, arguments=args)
        return None

    # ------------------------------------------------------------------
    def narrate(self, messages: List[Message]) -> str:
        """Turn the most recent tool results into a spoken answer."""
        arabic = any(is_arabic(m.content or "") for m in messages if m.role == "user")
        calls: Dict[str, str] = {}
        for m in messages:
            if m.role == "assistant":
                for tc in m.tool_calls:
                    calls[tc.id] = tc.name
        results = [m for m in messages if m.role == "tool"]
        if not results:
            return ""

        lines: List[str] = []
        for r in results[-4:]:
            tool = calls.get(r.tool_call_id, "") or r.name
            payload = _maybe_json(r.content)
            ok = True
            output: Any = r.content
            if isinstance(payload, dict):
                ok = payload.get("ok", True)
                output = payload.get("output") or payload.get("error") or payload.get("data") or ""
            out = str(output).strip()
            if len(out) > 600:
                out = out[:600] + "…"
            lines.append(_narrate_one(tool, ok, out, arabic))

        body = " ".join(line for line in lines if line)
        return body or ("" if arabic else "Done.")

    # ------------------------------------------------------------------
    def fallback(self, text: str) -> str:
        arabic = is_arabic(text)
        if arabic:
            return (
                "أعمل الآن في الوضع المحلي بدون نموذج لغوي. لقد فهمت طلبك لكنني أحتاج نموذجًا للرد بحرية.\n"
                "شغّل Ollama ثم نفّذ: ollama pull qwen3.5:4b — وسأتحول إلى العقل الكامل.\n"
                "الأوامر التي أستطيع تنفيذها الآن: افتح <برنامج>، أغلق <برنامج>، اعرض الملفات، اقرأ ملف، "
                "لقطة شاشة، ابحث عن <شيء>، تذكر <معلومة>، ماذا تتذكر، حالة الجهاز، الساعة."
            )
        return (
            "I'm running on the offline brain — no language model is attached yet, so I can execute "
            "commands but cannot hold an open-ended conversation.\n"
            "Start Ollama and run `ollama pull qwen3.5:4b`, then restart JARVIS for full reasoning.\n"
            "Commands I can run right now: open <app>, close <app>, list files in <folder>, read file <path>, "
            "take a screenshot, search the web for <topic>, remember <fact>, what do you remember, "
            "system status, what time is it."
        )


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _missing_required(args: Dict[str, Any]) -> bool:
    """Skip an intent when its key argument did not survive extraction."""
    for key, value in args.items():
        if isinstance(value, str) and not value.strip():
            return True
    return False


def _maybe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _narrate_one(tool: str, ok: bool, output: str, arabic: bool) -> str:
    if not ok:
        if arabic:
            return f"تعذّر تنفيذ {tool or 'الأداة'}: {output}"
        return f"I couldn't complete {tool or 'that'}: {output}"

    data = _maybe_json(output)
    if isinstance(data, dict):
        template = _done_templates(arabic).get(tool)
        if template:
            try:
                return template.format(**{k: v for k, v in data.items()})
            except (KeyError, IndexError):
                pass
        for key in ("summary", "text", "message", "answer", "result"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key].strip()
        output = json.dumps(data, ensure_ascii=False)

    if tool in ("system_status", "list_processes", "list_tasks", "recall", "list_directory", "search_files"):
        return output
    if not output or output in ("None", "null"):
        return "تم." if arabic else "Done."
    return output
