"""Screen capture + vision ("JARVIS, what's on my screen?")."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List

from . import platform_utils as pu
from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


def _shot_path(ctx: ToolContext) -> Path:
    directory = Path(ctx.cfg.tools.screenshot_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"jarvis_{time.strftime('%Y%m%d-%H%M%S')}.png"


async def _capture_screen(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    target = str(args.get("path") or "") or str(_shot_path(ctx))
    result = await asyncio.to_thread(pu.screenshot, target)
    if result.get("ok"):
        result["output"] = f"screenshot saved to {result['path']}"
    else:
        result["output"] = result.get("error", "screenshot failed")
    return result


async def _analyze_screen(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    question = str(args.get("question") or "Describe what is on this screen concisely.")
    shot = await asyncio.to_thread(pu.screenshot, str(_shot_path(ctx)))
    if not shot.get("ok"):
        return {"ok": False, "output": shot.get("error", "could not capture the screen"), "error": shot.get("error")}
    path = shot["path"]
    if ctx.vision is None:
        return {
            "ok": True,
            "path": path,
            "output": (
                f"Screenshot captured at {path}, but no vision model is configured. "
                "Install a multimodal model (e.g. `ollama pull qwen2.5vl:7b`) or enable the cloud tier."
            ),
        }
    try:
        answer = await ctx.vision(question, path)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "path": path, "output": f"vision model failed: {exc}", "error": str(exc)}
    return {"ok": True, "path": path, "output": answer or "(the vision model returned nothing)", "answer": answer}


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="capture_screen",
            description="Take a screenshot of the whole desktop and save it as a PNG.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Optional output path."}},
            },
            risk=RiskLevel.SAFE,
            category="screen",
            handler=_capture_screen,
        ),
        ToolSpec(
            name="analyze_screen",
            description="Screenshot the desktop and ask a vision model what is on it.",
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "What to look for on screen."},
                },
            },
            risk=RiskLevel.SAFE,
            category="screen",
            handler=_analyze_screen,
        ),
    ]
