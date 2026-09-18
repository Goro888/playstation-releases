"""Clipboard tools (read / write)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from . import platform_utils as pu
from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


async def _get_clipboard(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    result = await asyncio.to_thread(pu.clipboard_get)
    if result.get("ok"):
        text = (result.get("text") or "").strip()
        result["output"] = text[:2000] or "(clipboard is empty)"
    else:
        result["output"] = result.get("error", "clipboard unavailable")
    return result


async def _set_clipboard(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    text = str(args.get("text") or "")
    result = await asyncio.to_thread(pu.clipboard_set, text)
    if result.get("ok"):
        result["output"] = f"copied {len(text)} characters to the clipboard"
    else:
        result["output"] = result.get("error", "clipboard unavailable")
    return result


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="get_clipboard",
            description="Read the current clipboard contents.",
            parameters={"type": "object", "properties": {}},
            risk=RiskLevel.SAFE,
            category="clipboard",
            handler=_get_clipboard,
        ),
        ToolSpec(
            name="set_clipboard",
            description="Copy text onto the system clipboard.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to copy."}},
                "required": ["text"],
            },
            risk=RiskLevel.SAFE,
            category="clipboard",
            handler=_set_clipboard,
        ),
    ]
