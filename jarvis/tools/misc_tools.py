"""Small utility tools."""

from __future__ import annotations

from typing import Any, Dict, List

from . import platform_utils as pu
from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


async def _get_time(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    info = pu.now_info()
    info["ok"] = True
    info["output"] = f"{info['time']} · {info['date']}"
    return info


async def _capabilities(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """Report what this JARVIS instance can currently do (used by the HUD)."""
    from ..voice import voice_status

    return {
        "ok": True,
        "platform": pu.platform.system(),
        "windows": pu.IS_WINDOWS,
        "voice": voice_status(ctx.cfg),
        "output": "capability report generated",
    }


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="get_time",
            description="Get the current date, time and timezone.",
            parameters={"type": "object", "properties": {}},
            risk=RiskLevel.SAFE,
            category="misc",
            handler=_get_time,
        ),
        ToolSpec(
            name="capabilities",
            description="Report which optional subsystems (voice, vision, UI automation) are available on this machine.",
            parameters={"type": "object", "properties": {}},
            risk=RiskLevel.SAFE,
            category="misc",
            handler=_capabilities,
        ),
    ]
