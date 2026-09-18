"""Tool primitives: context, spec, result."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional, Sequence

from ..config import JarvisConfig
from ..core.memory import Memory
from ..core.permissions import PermissionManager, Risk
from ..events import EventBus


# Tool modules import ``Risk`` as ``RiskLevel``; keep the alias.
RiskLevel = Risk


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch."""

    cfg: JarvisConfig
    memory: Optional[Memory] = None
    permissions: Optional[PermissionManager] = None
    bus: Optional[EventBus] = None
    session: str = "default"
    platform: str = ""
    # async callable(prompt: str, image_path: str) -> str  (vision model)
    vision: Optional[Callable[[str, str], Awaitable[str]]] = None

    def emit(self, event_type: str, **payload: Any) -> None:
        if self.bus:
            self.bus.publish(event_type, payload, session=self.session)


ToolHandler = Callable[[Dict[str, Any], ToolContext], Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk: Risk = Risk.SAFE
    category: str = "misc"
    platforms: Optional[Sequence[str]] = None  # None = everywhere
    handler: Optional[ToolHandler] = None
    requires: Sequence[str] = field(default_factory=tuple)  # pip packages needed

    @property
    def required_params(self) -> List[str]:
        return list((self.parameters or {}).get("required", []))

    def openai_schema(self) -> Dict[str, Any]:
        """Ollama and OpenAI-compatible servers accept the same shape."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": (self.parameters or {}).get("properties", {}),
                    "required": self.required_params,
                },
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk": self.risk.value,
            "platforms": list(self.platforms) if self.platforms else ["windows", "linux", "darwin"],
            "parameters": self.parameters,
            "required_params": self.required_params,
            "requires": list(self.requires),
        }


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    data: Any = None
    error: Optional[str] = None
    tool: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "output": self.output,
            "data": self.data,
            "error": self.error,
        }

    def as_tool_message(self, call_id: str = "") -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def unavailable(message: str) -> ToolResult:
    return ToolResult(ok=False, output=message, error=message)
