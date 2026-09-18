"""Process / application / system tools (the "computer control" layer)."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List

import psutil

from . import platform_utils as pu
from .base import Risk as RiskLevel
from .base import ToolContext, ToolResult, ToolSpec


async def _open_application(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    name = str(args.get("name") or "").strip()
    arguments = str(args.get("args") or "")
    result = await asyncio.to_thread(pu.launch, name, ctx.cfg.tools.app_aliases, arguments)
    if not result.get("ok"):
        return result
    # give the OS a moment, then confirm the process actually exists
    await asyncio.sleep(1.2)
    lowered = name.lower()
    running = any(
        lowered in (p.info.get("name") or "").lower() or lowered in " ".join(p.info.get("cmdline") or []).lower()
        for p in psutil.process_iter(["name", "cmdline"])
    )
    result["confirmed_running"] = bool(running)
    result["output"] = f"launched {name}" + ("" if running else " (could not confirm the process yet)")
    return result


async def _close_application(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    name = str(args.get("name") or "").strip()
    return await asyncio.to_thread(pu.terminate, name)


async def _list_processes(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    limit = int(args.get("limit") or 12)
    procs: List[Dict[str, Any]] = []
    for p in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
        try:
            info = p.info
            procs.append(
                {
                    "pid": p.pid,
                    "name": info.get("name") or "",
                    "mem_mb": round((info.get("memory_info").rss if info.get("memory_info") else 0) / 1048576, 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):  # pragma: no cover
            continue
    procs.sort(key=lambda x: x["mem_mb"], reverse=True)
    top = procs[:limit]
    lines = [f"{p['name']} (pid {p['pid']}, {p['mem_mb']} MB)" for p in top]
    return {
        "ok": True,
        "count": len(procs),
        "top": top,
        "output": f"{len(procs)} processes running. Top by memory:\n" + "\n".join(lines),
    }


async def _system_status(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    import time

    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.expanduser("~"))
    boot = psutil.boot_time()
    battery = None
    try:
        batt = psutil.sensors_battery()
        if batt:
            battery = {"percent": round(batt.percent, 1), "plugged": bool(batt.power_plugged)}
    except Exception:  # noqa: BLE001
        battery = None
    data = {
        "cpu_percent": psutil.cpu_percent(interval=0.4),
        "cpu_cores": psutil.cpu_count(logical=True) or 0,
        "ram_percent": vm.percent,
        "ram_used_gb": round(vm.used / 1073741824, 1),
        "ram_total_gb": round(vm.total / 1073741824, 1),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1073741824, 1),
        "uptime_hours": round((time.time() - boot) / 3600, 1),
        "battery": battery,
        "platform": f"{os.name}/{__import__('platform').system()} {__import__('platform').release()}",
    }
    text = (
        f"CPU {data['cpu_percent']}% of {data['cpu_cores']} cores · "
        f"RAM {data['ram_used_gb']}/{data['ram_total_gb']} GB ({data['ram_percent']}%) · "
        f"disk {data['disk_free_gb']} GB free · uptime {data['uptime_hours']} h"
    )
    return {"ok": True, "data": data, "output": text, "summary": text}


async def _run_command(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    command = str(args.get("command") or "").strip()
    timeout = float(args.get("timeout") or 30)
    if not ctx.cfg.security.allow_shell and ctx.permissions is None:
        return {"ok": False, "error": "shell execution is disabled (security.allow_shell=false)"}
    if len(command) > ctx.cfg.agent.max_tool_output_chars:
        return {"ok": False, "error": "command too long"}
    code, out, err = await asyncio.to_thread(pu.shell, command, timeout)
    combined = "\n".join(part for part in (out, err) if part)[:4000]
    return {"ok": code == 0, "exit_code": code, "output": combined or f"(exit {code}, no output)", "command": command}


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="open_application",
            description="Open or launch a desktop application, file or URL. Examples: 'chrome', 'visual studio code', 'C:\\reports\\q3.pdf'.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name, path or URL to open."},
                    "args": {"type": "string", "description": "Optional command-line arguments."},
                },
                "required": ["name"],
            },
            risk=RiskLevel.SAFE,
            category="system",
            handler=_open_application,
        ),
        ToolSpec(
            name="close_application",
            description="Close or kill a running application by name.",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Application or process name to close."}},
                "required": ["name"],
            },
            risk=RiskLevel.SENSITIVE,
            category="system",
            handler=_close_application,
        ),
        ToolSpec(
            name="list_processes",
            description="List running processes with memory usage, heaviest first.",
            parameters={
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "How many processes to show (default 12)."}},
            },
            risk=RiskLevel.SAFE,
            category="system",
            handler=_list_processes,
        ),
        ToolSpec(
            name="system_status",
            description="Report CPU, RAM, disk, battery and uptime for this machine.",
            parameters={"type": "object", "properties": {}},
            risk=RiskLevel.SAFE,
            category="system",
            handler=_system_status,
        ),
        ToolSpec(
            name="run_command",
            description="Run a shell command (PowerShell on Windows). Requires shell access to be enabled.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."},
                    "timeout": {"type": "number", "description": "Timeout in seconds (default 30)."},
                },
                "required": ["command"],
            },
            risk=RiskLevel.DANGEROUS,
            category="system",
            handler=_run_command,
        ),
    ]
