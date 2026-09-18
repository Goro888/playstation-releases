"""Windows UI Automation tools — real interaction with app interfaces.

Behind the scenes these call UI Automation through the ``uiautomation`` or
``pywinauto`` package when installed, and fall back to PowerShell
(WScript.Shell / Get-Process) otherwise, so the tools still work on a clean
Windows install. On non-Windows hosts they report that they are unavailable
instead of failing silently.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from . import platform_utils as pu
from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


async def _list_windows(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    result = await asyncio.to_thread(pu.list_windows)
    if result.get("ok"):
        titles = [w.get("title", "") for w in result.get("windows", [])]
        result["output"] = "Open windows:\n" + "\n".join(f"• {t}" for t in titles if t)
    return result


async def _focus_window(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    return await asyncio.to_thread(pu.focus_window, str(args.get("title") or ""))


async def _click_control(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    return await asyncio.to_thread(
        pu.click_control, str(args.get("window") or ""), str(args.get("control") or "")
    )


async def _type_text(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    return await asyncio.to_thread(pu.type_text, str(args.get("text") or ""))


async def _send_hotkey(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    """Send a keyboard shortcut such as ``ctrl+s`` to the focused window."""
    keys = str(args.get("keys") or "").strip()
    if not pu.IS_WINDOWS:
        return {"ok": False, "error": "send_hotkey is Windows-only"}
    token = "+".join(f"{k.strip()}" for k in keys.replace("-", "+").split("+") if k.strip())
    mapping = {
        "ctrl": "^",
        "control": "^",
        "alt": "%",
        "shift": "+",
        "win": "^{Esc}",
        "enter": "{ENTER}",
        "tab": "{TAB}",
        "esc": "{ESC}",
        "escape": "{ESC}",
        "space": " ",
        "del": "{DEL}",
        "delete": "{DEL}",
    }
    parts = [mapping.get(p.lower(), p) for p in token.split("+")]
    sequence = "".join(parts if len(parts) == 1 else [f"({''.join(parts)})"])
    script = f"$ws = New-Object -ComObject WScript.Shell; $ws.SendKeys({pu.ps_quote(sequence)})"
    code, out, err = await asyncio.to_thread(pu.powershell, script)
    return {"ok": code == 0, "output": out or err or f"sent {keys}", "keys": keys}


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="list_windows",
            description="List open windows and their titles.",
            parameters={"type": "object", "properties": {}},
            risk=RiskLevel.SAFE,
            category="ui",
            handler=_list_windows,
            platforms=["windows", "linux"],
        ),
        ToolSpec(
            name="focus_window",
            description="Bring a window to the foreground by (partial) title.",
            parameters={
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Window title or part of it."}},
                "required": ["title"],
            },
            risk=RiskLevel.SAFE,
            category="ui",
            handler=_focus_window,
            platforms=["windows", "linux"],
        ),
        ToolSpec(
            name="click_control",
            description="Click a button or control inside a window using Windows UI Automation (needs `pip install uiautomation`).",
            parameters={
                "type": "object",
                "properties": {
                    "window": {"type": "string", "description": "Window title (partial match)."},
                    "control": {"type": "string", "description": "Control/button name (partial match)."},
                },
                "required": ["window", "control"],
            },
            risk=RiskLevel.SENSITIVE,
            category="ui",
            handler=_click_control,
            platforms=["windows"],
            requires=["uiautomation"],
        ),
        ToolSpec(
            name="type_text",
            description="Type text into the currently focused window.",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to type."}},
                "required": ["text"],
            },
            risk=RiskLevel.SENSITIVE,
            category="ui",
            handler=_type_text,
            platforms=["windows"],
        ),
        ToolSpec(
            name="send_hotkey",
            description="Send a keyboard shortcut to the focused window, e.g. 'ctrl+s' or 'alt+tab'.",
            parameters={
                "type": "object",
                "properties": {"keys": {"type": "string", "description": "Shortcut, e.g. 'ctrl+s'."}},
                "required": ["keys"],
            },
            risk=RiskLevel.SENSITIVE,
            category="ui",
            handler=_send_hotkey,
            platforms=["windows"],
        ),
    ]
