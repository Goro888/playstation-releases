"""A tiny in-process publish/subscribe event bus.

The HUD subscribes over SSE; the CLI prints events. Every layer publishes
through the same bus so the UI always reflects what the assistant is doing
(listening -> planning -> acting -> speaking).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Lifecycle / UI states
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_TRANSCRIBING = "transcribing"
STATE_PLANNING = "planning"
STATE_THINKING = "thinking"
STATE_ACTING = "acting"
STATE_SPEAKING = "speaking"
STATE_ERROR = "error"


@dataclass
class Event:
    """A single event emitted by any JARVIS layer."""

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "ts": self.ts,
            "session": self.session,
        }

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.type}] {self.payload}"


class EventBus:
    """Fan-out event bus with a short ring buffer for late subscribers."""

    def __init__(self, history_size: int = 200) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._history: List[Event] = []
        self._history_size = history_size

    # -- subscription -----------------------------------------------------
    def subscribe(self, maxsize: int = 256) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    # -- publishing -------------------------------------------------------
    def publish(
        self,
        type: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        session: Optional[str] = None,
    ) -> Event:
        event = Event(type=type, payload=payload or {}, session=session)
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size :]
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - race
                    pass
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:  # pragma: no cover - give up
                    pass
        return event

    # -- inspection -------------------------------------------------------
    def history(self, limit: int = 50, since: float = 0.0) -> List[Dict[str, Any]]:
        items = [e for e in self._history if e.ts >= since]
        return [e.to_dict() for e in items[-limit:]]


class ConsoleSink:
    """Prints events to stdout (used by the CLI)."""

    QUIET = {"system"}

    def __init__(self, bus: EventBus, verbose: bool = False) -> None:
        self.bus = bus
        self.verbose = verbose
        self._q = bus.subscribe()

    def drain(self) -> None:
        while True:
            try:
                event = self._q.get_nowait()
            except asyncio.QueueEmpty:
                return
            self.print(event)

    def print(self, event: Event) -> None:
        kind = event.type
        if kind in self.QUIET and not self.verbose:
            return
        payload = event.payload
        if kind == "message":
            return  # the caller prints the final answer
        elif kind == "tool_call":
            print(f"  -> {payload.get('tool')}({_brief(payload.get('args'))})")
        elif kind == "tool_result":
            ok = "ok" if payload.get("ok") else "error"
            print(f"  <- {payload.get('tool')}: {ok} {str(payload.get('output', ''))[:200]}")
        elif kind == "permission_request":
            print(f"  !! confirmation required: {payload.get('tool')} ({payload.get('risk')}) — {payload.get('reason')}")
        elif kind == "status":
            print(f"  [{payload.get('state')}]")
        elif kind == "error":
            print(f"  !! error: {payload.get('message')}")
        elif self.verbose:
            print(f"  . {kind}: {payload}")


def _brief(args: Any, limit: int = 90) -> str:
    if not isinstance(args, dict):
        return str(args)[:limit]
    parts = []
    for k, v in args.items():
        s = str(v)
        parts.append(f"{k}={s[:40]}")
    return ", ".join(parts)[:limit]
