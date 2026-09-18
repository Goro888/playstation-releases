"""Permission manager — the gate between the model and the operating system.

Design rule from the build plan: the model never executes an arbitrary shell
command. It may only request a *named* tool, and every request passes through
:meth:`PermissionManager.gate`:

* ``safe``      -> executed immediately (open Chrome, read weather, read a file)
* ``sensitive`` -> parked until the user confirms (delete file, send message)
* ``dangerous`` -> denied unless explicitly auto-approved (shell, install, admin)

Confirmations surface in the HUD and in the API (``/api/permissions/*``).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..config import SecurityConfig
from ..events import EventBus


class Risk(str, Enum):
    SAFE = "safe"
    SENSITIVE = "sensitive"
    DANGEROUS = "dangerous"


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


@dataclass
class PermissionRequest:
    id: str
    tool: str
    args: Dict[str, Any]
    risk: str
    reason: str
    created_at: float = field(default_factory=time.time)
    future: Optional[asyncio.Future] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool": self.tool,
            "args": self.args,
            "risk": self.risk,
            "reason": self.reason,
            "created_at": self.created_at,
            "age": round(time.time() - self.created_at, 1),
        }


class PermissionManager:
    """Evaluates and (when needed) parks tool calls until a human approves."""

    def __init__(self, cfg: SecurityConfig, bus: Optional[EventBus] = None) -> None:
        self.cfg = cfg
        self.bus = bus
        self._pending: Dict[str, PermissionRequest] = {}
        self._session_approved: set[str] = set()

    # -- policy -----------------------------------------------------------
    def evaluate(self, tool_name: str, risk: Risk | str = Risk.SAFE) -> Tuple[Decision, str]:
        risk = Risk(risk) if not isinstance(risk, Risk) else risk
        if tool_name in self.cfg.denied:
            return Decision.DENY, f"'{tool_name}' is on the denied list"
        if tool_name in self._session_approved:
            return Decision.ALLOW, "approved for this session"
        if tool_name in self.cfg.auto_approve:
            return Decision.ALLOW, "auto-approved by policy"
        if tool_name in self.cfg.require_confirm:
            return Decision.CONFIRM, "explicit confirmation required by policy"

        mode = (self.cfg.mode or "confirm-sensitive").lower()
        if mode == "allow-all":
            if risk is Risk.DANGEROUS and not self.cfg.allow_shell:
                return Decision.DENY, "dangerous tool blocked (security.allow_shell=false)"
            return Decision.ALLOW, "mode=allow-all"
        if mode == "deny-sensitive":
            if risk in (Risk.SENSITIVE, Risk.DANGEROUS):
                return Decision.DENY, f"mode=deny-sensitive blocks {risk.value} tools"
            return Decision.ALLOW, "safe tool"

        # default: confirm-sensitive
        if risk is Risk.SAFE:
            return Decision.ALLOW, "safe tool"
        if risk is Risk.DANGEROUS and not self.cfg.allow_shell:
            return Decision.CONFIRM, "dangerous tool — confirmation required"
        return Decision.CONFIRM, f"{risk.value} tool — confirmation required"

    # -- gating -----------------------------------------------------------
    async def gate(
        self,
        tool_name: str,
        args: Dict[str, Any] | None = None,
        risk: Risk | str = Risk.SAFE,
        reason: str = "",
        timeout: float | None = None,
    ) -> Tuple[bool, str]:
        """Return ``(allowed, reason)``. Blocks while awaiting confirmation."""
        decision, why = self.evaluate(tool_name, risk)
        if decision is Decision.ALLOW:
            return True, why
        if decision is Decision.DENY:
            if self.bus:
                self.bus.publish("permission_denied", {"tool": tool_name, "risk": str(risk), "reason": why})
            return False, why

        loop = asyncio.get_running_loop()
        req = PermissionRequest(
            id=uuid.uuid4().hex[:8],
            tool=tool_name,
            args=dict(args or {}),
            risk=str(risk),
            reason=reason or why,
            future=loop.create_future(),
        )
        self._pending[req.id] = req
        if self.bus:
            self.bus.publish("permission_request", req.to_dict())

        try:
            approved = await asyncio.wait_for(asyncio.shield(req.future), timeout or self.cfg.confirm_timeout)
        except (asyncio.TimeoutError, TimeoutError):
            self._pending.pop(req.id, None)
            if self.bus:
                self.bus.publish("permission_expired", {"id": req.id, "tool": tool_name})
            return False, "confirmation timed out"

        self._pending.pop(req.id, None)
        if approved:
            self._session_approved.add(tool_name)
            if self.bus:
                self.bus.publish("permission_granted", {"id": req.id, "tool": tool_name})
            return True, "user approved"
        if self.bus:
            self.bus.publish("permission_denied", {"id": req.id, "tool": tool_name, "reason": "user declined"})
        return False, "user declined"

    # -- resolution -------------------------------------------------------
    def pending(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._pending.values()]

    def resolve(self, request_id: str, approved: bool, remember: bool = False) -> bool:
        req = self._pending.get(request_id)
        if req is None or req.future is None:
            return False
        if remember and approved:
            self._session_approved.add(req.tool)
        if not req.future.done():
            req.future.set_result(bool(approved))
        return True

    def approve_all(self) -> int:
        count = 0
        for req in list(self._pending.values()):
            if req.future and not req.future.done():
                req.future.set_result(True)
                count += 1
        return count

    def deny_all(self) -> int:
        count = 0
        for req in list(self._pending.values()):
            if req.future and not req.future.done():
                req.future.set_result(False)
                count += 1
        return count
