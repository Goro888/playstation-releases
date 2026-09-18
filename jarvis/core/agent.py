"""The agent core — planning, tool loop, permissions and memory in one place.

The loop is deliberately small and backend-agnostic:

    messages -> model -> tool_calls? -> permission gate -> tool -> messages -> model -> answer

Ollama/Qwen, the cloud tier and the offline brain all speak the same
"message + tool schema" language, so swapping brains changes nothing here.
"""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config import JarvisConfig
from ..core.memory import Memory
from ..core.permissions import PermissionManager, Risk
from ..core.prompts import build_system_prompt
from ..core.router import ModelRouter, TaskHint
from ..events import EventBus
from ..models.base import Message, ModelReply
from ..tools import build_context, build_registry
from ..tools.base import ToolContext, ToolResult
from ..tools.registry import ToolRegistry

log = logging.getLogger("jarvis.core.agent")


@dataclass
class AgentResult:
    text: str = ""
    backend: str = ""
    model: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    duration: float = 0.0
    route: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "backend": self.backend,
            "model": self.model,
            "tool_calls": self.tool_calls,
            "steps": self.steps,
            "duration": round(self.duration, 2),
            "route": self.route,
        }


class JarvisAgent:
    """Turns a user utterance into (possibly tool-driven) actions and an answer."""

    def __init__(
        self,
        cfg: JarvisConfig,
        *,
        bus: Optional[EventBus] = None,
        memory: Optional[Memory] = None,
        registry: Optional[ToolRegistry] = None,
        permissions: Optional[PermissionManager] = None,
        router: Optional[ModelRouter] = None,
    ) -> None:
        self.cfg = cfg
        self.bus = bus or EventBus()
        self.memory = memory
        self.registry = registry or build_registry(cfg)
        self.permissions = permissions or PermissionManager(cfg.security, self.bus)
        self.router = router or ModelRouter(cfg, self.bus, self.registry.names())
        self.router.set_tools(self.registry.names())
        self.system = platform.system().lower()

    # -- construction -----------------------------------------------------
    @classmethod
    def create(cls, cfg: JarvisConfig, bus: Optional[EventBus] = None) -> "JarvisAgent":
        """Build a fully wired agent (memory + tools + permissions + router)."""
        bus = bus or EventBus()
        memory = Memory(cfg.memory) if cfg.memory.enabled else None
        registry = build_registry(cfg)
        permissions = PermissionManager(cfg.security, bus)
        return cls(cfg, bus=bus, memory=memory, registry=registry, permissions=permissions)

    # -- public API -------------------------------------------------------
    async def handle(
        self,
        text: str,
        *,
        session: str = "default",
        images: Optional[List[str]] = None,
        force: Optional[str] = None,
        max_steps: Optional[int] = None,
    ) -> AgentResult:
        """Process one user utterance end-to-end."""
        started = time.time()
        text = (text or "").strip()
        if not text:
            return AgentResult(text="")

        # "/cloud ..." and "/local ..." prefixes override the router
        for prefix, mode in (
            (self.cfg.router.force_cloud_prefix, "cloud"),
            (self.cfg.router.force_local_prefix, "local"),
        ):
            if prefix and text.lower().startswith(prefix + " "):
                text = text[len(prefix) :].strip()
                force = mode
                break

        self.bus.publish("status", {"state": "planning", "session": session}, session=session)
        self.bus.publish("user_message", {"text": text, "images": images or []}, session=session)

        ctx = build_context(
            self.cfg,
            memory=self.memory,
            permissions=self.permissions,
            bus=self.bus,
            session=session,
            vision=self.router.vision,
        )
        messages = self._initial_messages(text, images=images)
        schemas = self.registry.schemas(system=self.system)

        steps = 0
        calls: List[Dict[str, Any]] = []
        answer = ""
        backend_name = ""
        model_name = ""
        limit = max_steps or self.cfg.agent.max_steps

        while steps < limit:
            steps += 1
            hint = TaskHint(text=text, needs_vision=bool(images), force=force, images=len(images or []), session=session)
            backend = await self.router.select(hint)
            backend_name, model_name = backend.name, getattr(backend, "model", "")

            self.bus.publish(
                "status",
                {"state": "thinking", "backend": backend_name, "model": model_name, "step": steps},
                session=session,
            )
            reply: ModelReply = await backend.chat(
                messages,
                tools=schemas or None,
                temperature=self.cfg.local.temperature,
                max_tokens=1024,
            )

            if not reply.tool_calls:
                answer = (reply.content or "").strip()
                break

            messages.append(Message(role="assistant", content=reply.content or "", tool_calls=reply.tool_calls))
            for call in reply.tool_calls:
                calls.append({"tool": call.name, "args": call.arguments})
                result = await self._run_tool(call.name, call.arguments, ctx, session)
                messages.append(
                    Message(role="tool", content=result.as_tool_message(call.id), tool_call_id=call.id, name=call.name)
                )
        else:
            answer = answer or "I reached my step limit before finishing that request."

        self.bus.publish("status", {"state": "idle"}, session=session)

        result = AgentResult(
            text=answer,
            backend=backend_name,
            model=model_name,
            tool_calls=calls,
            steps=steps,
            duration=time.time() - started,
            route=self.router.last_choice,
        )
        self._persist(session, text, answer)
        self.bus.publish("message", {"text": answer, **result.to_dict()}, session=session)
        return result

    async def run_tool(self, name: str, args: Dict[str, Any], *, session: str = "default") -> ToolResult:
        """Execute a single tool through the same permission gate as the agent."""
        ctx = build_context(
            self.cfg,
            memory=self.memory,
            permissions=self.permissions,
            bus=self.bus,
            session=session,
            vision=self.router.vision,
        )
        return await self._run_tool(name, args, ctx, session)

    # -- internals --------------------------------------------------------
    async def _run_tool(
        self, name: str, args: Dict[str, Any], ctx: ToolContext, session: str
    ) -> ToolResult:
        spec = self.registry.get(name)
        if spec is None:
            known = ", ".join(self.registry.names())
            unknown = ToolResult(ok=False, tool=name, output=f"unknown tool '{name}'", error=f"unknown tool; known tools: {known}")
            self.bus.publish("tool_result", {"tool": name, "ok": False, "output": unknown.output}, session=session)
            return unknown
        risk = spec.risk
        allowed, reason = await self.permissions.gate(name, args, risk)
        if not allowed:
            denied = ToolResult(ok=False, tool=name, output=f"permission denied — {reason}", error=reason)
            self.bus.publish(
                "tool_result", {"tool": name, "ok": False, "output": denied.output, "denied": True}, session=session
            )
            return denied

        self.bus.publish("tool_call", {"tool": name, "args": args, "risk": risk.value}, session=session)
        self.bus.publish("status", {"state": "acting", "tool": name}, session=session)
        result = await self.registry.execute(name, args, ctx)
        output = result.output or ""
        if len(output) > self.cfg.agent.max_tool_output_chars:
            output = output[: self.cfg.agent.max_tool_output_chars] + " …(truncated)"
            result.output = output
        self.bus.publish(
            "tool_result",
            {"tool": name, "ok": result.ok, "output": output, "data": result.data, "error": result.error},
            session=session,
        )
        self.bus.publish("status", {"state": "thinking"}, session=session)
        return result

    def _initial_messages(self, text: str, images: Optional[List[str]] = None) -> List[Message]:
        memory_block = self._memory_block(text)
        system_prompt = build_system_prompt(self.cfg, self.registry.specs(), memory_block)
        messages = [Message(role="system", content=system_prompt)]
        if self.memory:
            for turn in self.memory.history(limit=self.cfg.memory.history_limit):
                if turn["role"] in ("user", "assistant"):
                    messages.append(Message(role=turn["role"], content=turn["content"]))
        messages.append(Message(role="user", content=text, images=list(images or [])))
        return messages

    def _memory_block(self, query: str) -> str:
        if not self.memory:
            return "(memory disabled)"
        try:
            facts = self.memory.recall(query, limit=self.cfg.memory.recall_limit)
        except Exception:  # noqa: BLE001 - memory must never break a turn
            return "(memory unavailable)"
        if not facts:
            facts = self.memory.recent(limit=5)
        if not facts:
            return "(no memories stored yet)"
        lines = [f"• [{f.kind}] {f.content}" for f in facts]
        prefs = self.memory.all_prefs()
        if prefs:
            lines.append("• preferences: " + ", ".join(f"{k}={v}" for k, v in list(prefs.items())[:10]))
        return "\n".join(lines)

    def _persist(self, session: str, user_text: str, answer: str) -> None:
        if not self.memory or not self.cfg.memory.store_conversations:
            return
        try:
            self.memory.add_message("user", user_text, session)
            if answer:
                self.memory.add_message("assistant", answer, session)
        except Exception:  # noqa: BLE001
            log.exception("could not persist conversation turn")

    # -- diagnostics ------------------------------------------------------
    async def status(self) -> Dict[str, Any]:
        """Everything the HUD needs for its status strip."""
        from ..voice import voice_status

        local_ok = await self.router.local_available()
        cloud_ok = await self.router.cloud_available()
        return {
            "version": __import__("jarvis").__version__,
            "platform": platform.platform(),
            "system": platform.system(),
            "mode": self.cfg.router.mode,
            "persona": {"name": self.cfg.persona.name, "user_title": self.cfg.persona.user_title},
            "local": {
                "ok": local_ok,
                "backend": self.cfg.local.backend,
                "base_url": self.cfg.local.base_url,
                "model": self.router.local.model,
                "configured": self.cfg.local.model,
                "vision_model": self.cfg.local.vision_model,
            },
            "cloud": {
                "ok": cloud_ok,
                "enabled": self.cfg.cloud.enabled,
                "model": self.cfg.cloud.model,
                "base_url": self.cfg.cloud.base_url,
            },
            "tools": {
                "count": len(self.registry.names()),
                "categories": sorted({s.category for s in self.registry.specs()}),
            },
            "memory": self.memory.stats() if self.memory else {"enabled": False},
            "voice": voice_status(self.cfg.voice),
            "security": {
                "mode": self.cfg.security.mode,
                "allow_shell": self.cfg.security.allow_shell,
                "pending": self.permissions.pending(),
            },
            "config_path": self.cfg.config_path,
        }
