"""Abstractions shared by every inference backend."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """A request from the model to run a named tool."""

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class Message:
    """A chat message. ``images`` holds local file paths (encoded on the wire)."""

    role: str  # system | user | assistant | tool
    content: str = ""
    images: List[str] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "images": self.images,
            "tool_calls": [t.to_dict() for t in self.tool_calls],
            "tool_call_id": self.tool_call_id,
            "name": self.name,
        }


@dataclass
class ModelReply:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    model: str = ""
    backend: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class ModelBackend:
    """Base class for inference backends (Ollama, OpenAI-compatible, offline)."""

    name = "base"
    supports_tools = False
    supports_vision = False
    model = ""
    base_url = ""

    async def available(self) -> bool:
        return True

    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> ModelReply:  # pragma: no cover - interface
        raise NotImplementedError

    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError("this backend does not provide embeddings")


def encode_image(path: str) -> str:
    """Return base64 (no data-URI prefix) for an image file."""
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def to_message_dicts(messages: List[Message], *, with_images: bool = False) -> List[Dict[str, Any]]:
    """Convert :class:`Message` objects into provider-neutral wire dicts."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        item: Dict[str, Any] = {"role": m.role, "content": m.content}
        if with_images and m.images:
            try:
                item["images"] = [encode_image(p) for p in m.images]
            except OSError:
                item["images"] = []
        if m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": t.id,
                    "type": "function",
                    "function": {"name": t.name, "arguments": t.arguments},
                }
                for t in m.tool_calls
            ]
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.name:
            item["name"] = m.name
        out.append(item)
    return out
