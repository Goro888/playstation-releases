"""OpenAI-compatible backend.

Used for the optional cloud tier (OpenAI, Azure, Groq, Together, OpenRouter)
and for **Foundry Local** — Microsoft's local OpenAI-compatible runtime, whose
endpoint is simply another ``base_url`` here.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from ..config import CloudConfig
from .base import Message, ModelBackend, ModelReply, ToolCall

log = logging.getLogger("jarvis.models.openai")


class OpenAICompatibleBackend(ModelBackend):
    name = "openai-compatible"
    supports_tools = True
    supports_vision = True

    def __init__(self, cfg: CloudConfig, model: Optional[str] = None) -> None:
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")
        self.model = model or cfg.model
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def api_key(self) -> str:
        return os.environ.get(self.cfg.api_key_env, "") or os.environ.get("OPENAI_API_KEY", "")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.cfg.timeout, connect=5.0))
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def available(self) -> bool:
        if not self.cfg.enabled:
            return False
        if not self.api_key and "api.openai.com" in self.base_url:
            return False
        try:
            r = await self.client.get(
                f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}
            )
            return r.status_code < 500
        except Exception as exc:
            log.debug("cloud backend unreachable: %s", exc)
            return False

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
            "messages": [self._wire(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            r = await self.client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            log.warning("cloud chat failed: %s", exc)
            return ModelReply(content=f"[cloud error] {exc}", backend=self.name, model=self.model)

        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls: List[ToolCall] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args or "{}")
                except ValueError:
                    args = {"_raw": raw_args}
            else:
                args = raw_args or {}
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name") or "", arguments=args))
        return ModelReply(
            content=msg.get("content") or "",
            tool_calls=calls,
            raw=data,
            model=data.get("model", self.model),
            backend=self.name,
        )

    # -- helpers ----------------------------------------------------------
    def _wire(self, m: Message) -> Dict[str, Any]:
        item: Dict[str, Any] = {"role": m.role, "content": m.content}
        if m.images:
            from .base import encode_image

            content: List[Dict[str, Any]] = [{"type": "text", "text": m.content}]
            for p in m.images:
                try:
                    content.append(
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encode_image(p)}"}}
                    )
                except OSError:
                    continue
            item["content"] = content
        if m.tool_calls:
            item["tool_calls"] = [
                {"id": t.id, "type": "function", "function": {"name": t.name, "arguments": json.dumps(t.arguments)}}
                for t in m.tool_calls
            ]
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.name:
            item["name"] = m.name
        if not item.get("content") and not m.tool_calls:
            item["content"] = ""
        return item

    async def embed(self, text: str) -> List[float]:
        r = await self.client.post(
            f"{self.base_url}/embeddings",
            json={"model": self.cfg.model, "input": text},
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        r.raise_for_status()
        return ((r.json().get("data") or [{}])[0]).get("embedding") or []
