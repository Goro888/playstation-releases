"""The local/cloud router (hybrid design).

    User -> JARVIS -> Router -- local Qwen (Ollama)
                            \\_ cloud model (OpenAI-compatible / Foundry Local)
                             \\_ offline brain (no model at all)

Routing is conservative: local first, cloud only when the request genuinely
needs it (vision that the local model cannot do, deep research, very long
context), and the offline brain whenever nothing else is reachable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config import JarvisConfig
from ..events import EventBus
from ..models.base import ModelBackend
from ..models.offline import OfflineBrain, is_arabic
from ..models.ollama import OllamaBackend
from ..models.openai_compatible import OpenAICompatibleBackend

log = logging.getLogger("jarvis.core.router")


@dataclass
class TaskHint:
    text: str = ""
    needs_vision: bool = False
    force: Optional[str] = None  # "local" | "cloud" | "offline"
    images: int = 0
    session: str = "default"

    @property
    def length(self) -> int:
        return len(self.text or "")


class ModelRouter:
    """Owns backend instances and picks one per request."""

    def __init__(self, cfg: JarvisConfig, bus: Optional[EventBus] = None, tool_names=()) -> None:
        self.cfg = cfg
        self.bus = bus
        self.local = OllamaBackend(cfg.local)
        self.cloud = OpenAICompatibleBackend(cfg.cloud)
        self.offline = OfflineBrain(cfg.persona, tool_names)
        self._local_ok: Optional[bool] = None
        self._cloud_ok: Optional[bool] = None
        self.last_choice: Dict[str, Any] = {}

    def set_tools(self, tool_names) -> None:
        self.offline.set_tools(tool_names)

    async def refresh(self) -> Dict[str, bool]:
        self._local_ok = await self.local.available()
        self._cloud_ok = await self.cloud.available()
        return {"local": bool(self._local_ok), "cloud": bool(self._cloud_ok)}

    async def local_available(self) -> bool:
        if self._local_ok is None:
            self._local_ok = await self.local.available()
        return bool(self._local_ok)

    async def cloud_available(self) -> bool:
        if self._cloud_ok is None:
            self._cloud_ok = await self.cloud.available()
        return bool(self._cloud_ok)

    # -- selection --------------------------------------------------------
    def wants_cloud(self, hint: TaskHint) -> bool:
        text = (hint.text or "").lower()
        if len(text) >= self.cfg.router.cloud_min_chars:
            return True
        return any(k.lower() in text for k in self.cfg.router.cloud_keywords)

    async def select(self, hint: TaskHint) -> ModelBackend:
        mode = (self.cfg.router.mode or "hybrid").lower()
        reason = ""

        if hint.force == "offline" or mode == "offline":
            backend, reason = self.offline, "offline mode"
        elif hint.force == "local":
            backend, reason = (self.local if await self.local_available() else self.offline), "forced local"
        elif hint.force == "cloud":
            backend = self.cloud if await self.cloud_available() else (self.local if await self.local_available() else self.offline)
            reason = "forced cloud"
        elif mode == "local":
            backend = self.local if await self.local_available() else self.offline
            reason = "local-only mode"
        elif mode == "cloud":
            backend = self.cloud if await self.cloud_available() else (self.local if await self.local_available() else self.offline)
            reason = "cloud-first mode"
        else:  # hybrid
            local_ok = await self.local_available()
            cloud_ok = await self.cloud_available()
            if hint.needs_vision and not local_ok and cloud_ok and self.cfg.router.allow_vision_cloud:
                backend, reason = self.cloud, "vision request with no local vision model"
            elif cloud_ok and self.wants_cloud(hint):
                backend, reason = self.cloud, "complex or long request"
            elif local_ok:
                backend, reason = self.local, "local by default"
            elif cloud_ok:
                backend, reason = self.cloud, "no local model reachable"
            else:
                backend, reason = self.offline, "no model reachable"

        self.last_choice = {
            "backend": backend.name,
            "model": getattr(backend, "model", ""),
            "reason": reason,
            "local_ready": await self.local_available(),
            "cloud_ready": await self.cloud_available(),
            "hint": {
                "chars": hint.length,
                "needs_vision": hint.needs_vision,
                "force": hint.force,
                "arabic": is_arabic(hint.text),
            },
        }
        if self.bus:
            self.bus.publish("route", self.last_choice)
        return backend

    # -- vision -----------------------------------------------------------
    async def vision(self, prompt: str, image_path: str) -> str:
        """Send an image to a multimodal model (local first, cloud fallback)."""
        from ..models.base import Message, encode_image

        if await self.local_available():
            try:
                return await self.local.generate_vision(self.cfg.local.vision_model, prompt, encode_image(image_path))
            except Exception as exc:  # noqa: BLE001
                log.warning("local vision failed: %s", exc)
        if await self.cloud_available():
            try:
                reply = await self.cloud.chat(
                    [Message(role="user", content=prompt, images=[image_path])],
                    temperature=0.2,
                    max_tokens=800,
                )
                return reply.content
            except Exception as exc:  # noqa: BLE001
                log.warning("cloud vision failed: %s", exc)
        raise RuntimeError("no vision model available (pull a multimodal model or enable the cloud tier)")

    async def close(self) -> None:
        await self.local.close()
        await self.cloud.close()
