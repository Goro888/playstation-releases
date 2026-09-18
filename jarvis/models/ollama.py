"""Ollama backend — the local brain (Qwen family by default).

Talks to ``/api/chat`` with OpenAI-style ``tools`` so the model can ask JARVIS
to run real Windows actions instead of merely describing them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from ..config import LocalConfig
from .base import Message, ModelBackend, ModelReply, ToolCall, to_message_dicts

log = logging.getLogger("jarvis.models.ollama")


class OllamaBackend(ModelBackend):
    name = "ollama"
    supports_tools = True
    supports_vision = True

    def __init__(self, cfg: LocalConfig, model: Optional[str] = None) -> None:
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")
        self.model = model or cfg.model
        self.timeout = cfg.timeout
        self._client: Optional[httpx.AsyncClient] = None

    # -- plumbing ---------------------------------------------------------
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def available(self) -> bool:
        """True when the server answers *and* a usable model is present."""
        try:
            r = await self.client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
        except Exception as exc:
            log.debug("ollama not reachable at %s: %s", self.base_url, exc)
            return False
        names = [m.get("name", "") for m in (r.json().get("models") or [])]
        wanted = self.model
        if wanted in names:
            return True
        # fall back to any installed model from the configured fallback chain
        for candidate in [wanted, *self.cfg.fallback_models]:
            base = candidate.split(":")[0]
            for n in names:
                if n == candidate or n.split(":")[0] == base:
                    log.info("ollama model %s not found — using %s", wanted, n)
                    self.model = n
                    return True
        if names:
            self.model = names[0]
            log.info("ollama model %s not found — using first installed model %s", wanted, names[0])
            return True
        return False

    async def installed_models(self) -> List[str]:
        try:
            r = await self.client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            return [m.get("name", "") for m in (r.json().get("models") or [])]
        except Exception:
            return []

    # -- chat -------------------------------------------------------------
    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        *,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> ModelReply:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": to_message_dicts(messages, with_images=True),
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": max_tokens,
            },
        }
        if self.cfg.keep_alive:
            payload["keep_alive"] = self.cfg.keep_alive
        if tools:
            payload["tools"] = tools

        try:
            r = await self.client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("ollama chat failed: %s", exc)
            return ModelReply(content=f"[ollama error] {exc}", backend=self.name, model=self.model)

        msg = data.get("message") or {}
        content = msg.get("content") or ""
        calls: List[ToolCall] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    import json

                    args = json.loads(args or "{}")
                except ValueError:
                    args = {"_raw": args}
            calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn.get("name") or "",
                    arguments=args or {},
                )
            )
        return ModelReply(content=content, tool_calls=calls, raw=data, model=self.model, backend=self.name)

    # -- extra ------------------------------------------------------------
    async def embed(self, text: str) -> List[float]:
        r = await self.client.post(
            f"{self.base_url}/api/embeddings",
            json={"model": self.cfg.embed_model, "prompt": text},
        )
        r.raise_for_status()
        return r.json().get("embedding") or []

    async def generate_vision(self, model: str, prompt: str, image_b64: str) -> str:
        """One-shot vision call (used by the ``analyze_screen`` tool)."""
        payload = {
            "model": model or self.cfg.vision_model,
            "messages": [
                {"role": "user", "content": prompt, "images": [image_b64]},
            ],
            "stream": False,
        }
        r = await self.client.post(f"{self.base_url}/api/chat", json=payload)
        r.raise_for_status()
        return (r.json().get("message") or {}).get("content", "")

    async def ensure_model(self, model: str) -> bool:
        """Trigger ``ollama pull`` if the model is missing (best effort)."""
        try:
            async with self.client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": model, "stream": True},
                timeout=None,
            ) as resp:
                async for _ in resp.aiter_lines():
                    pass
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("ollama pull failed for %s: %s", model, exc)
            return False


async def probe(base_url: str, timeout: float = 3.0) -> bool:
    """Cheap reachability probe used by ``jarvis doctor``."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(f"{base_url.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def _sleep_forever() -> None:  # pragma: no cover - helper
    await asyncio.sleep(3600)
