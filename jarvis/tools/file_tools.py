"""File and folder tools — always confined to ``tools.allowed_roots``."""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List

from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


def allowed_roots(ctx: ToolContext) -> List[Path]:
    roots = ctx.cfg.tools.allowed_roots or ["~"]
    return [Path(os.path.expandvars(os.path.expanduser(str(r)))).resolve() for r in roots]


def safe_path(ctx: ToolContext, raw: str) -> Path:
    """Resolve ``raw`` and confirm it lives under an allowed root."""
    raw = str(raw or "~").strip().strip('"').strip("'")
    expanded = Path(os.path.expandvars(os.path.expanduser(raw)))
    try:
        resolved = expanded.resolve()
    except OSError:  # pragma: no cover
        resolved = expanded
    roots = allowed_roots(ctx)
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise PermissionError(
        f"path '{raw}' is outside the allowed roots ({', '.join(str(r) for r in roots)}). "
        "Add it to tools.allowed_roots if you trust it."
    )


async def _list_directory(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    path = (args.get("path") or "~").strip()
    directory = safe_path(ctx, path)
    if not directory.exists():
        return {"ok": False, "error": f"no such folder: {directory}"}
    if not directory.is_dir():
        return {"ok": False, "error": f"not a folder: {directory}"}
    entries: List[Dict[str, Any]] = []

    def walk() -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:200]:
            try:
                stat = entry.stat()
                entries.append(
                    {
                        "name": entry.name,
                        "type": "dir" if entry.is_dir() else "file",
                        "size_kb": round(stat.st_size / 1024, 1) if entry.is_file() else 0,
                        "modified": __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(stat.st_mtime)),
                    }
                )
            except OSError:  # pragma: no cover
                continue

    await asyncio.to_thread(walk)
    listing = "\n".join(f"{'[DIR] ' if e['type'] == 'dir' else '      '}{e['name']}" for e in entries[:60])
    return {
        "ok": True,
        "path": str(directory),
        "entries": entries,
        "count": len(entries),
        "output": f"{directory} ({len(entries)} entries)\n{listing}",
    }


async def _read_file(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    path = (args.get("path") or "").strip()
    max_chars = int(args.get("max_chars") or 6000)
    target = safe_path(ctx, path)
    if not target.exists():
        return {"ok": False, "error": f"no such file: {target}"}
    if target.is_dir():
        return {"ok": False, "error": f"'{target}' is a folder — use list_directory"}

    def read() -> str:
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # pragma: no cover
            return f"[unreadable: {exc}]"

    content = await asyncio.to_thread(read)
    truncated = len(content) > max_chars
    body = content[:max_chars] + ("\n… (truncated)" if truncated else "")
    return {"ok": True, "path": str(target), "chars": len(content), "output": body, "truncated": truncated}


async def _write_file(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    path = (args.get("path") or "").strip()
    content = args.get("content", "")
    append = bool(args.get("append"))
    target = safe_path(ctx, path)
    target.parent.mkdir(parents=True, exist_ok=True)

    def write() -> int:
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as fh:
            fh.write(content)
        return len(content)

    chars = await asyncio.to_thread(write)
    return {"ok": True, "path": str(target), "chars": chars, "output": f"wrote {chars} characters to {target}"}


async def _delete_file(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    path = (args.get("path") or "").strip()
    target = safe_path(ctx, path)
    if not target.exists():
        return {"ok": False, "error": f"no such file: {target}"}

    def delete() -> None:
        if target.is_dir():
            for child in sorted(target.rglob("*"), reverse=True):
                try:
                    child.unlink()
                except (IsADirectoryError, PermissionError):  # pragma: no cover
                    pass
            target.rmdir()
        else:
            target.unlink()

    await asyncio.to_thread(delete)
    return {"ok": True, "path": str(target), "output": f"deleted {target}"}


async def _search_files(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    pattern = (args.get("pattern") or "").strip()
    root_raw = (args.get("path") or "~").strip()
    limit = int(args.get("limit") or 25)
    root = safe_path(ctx, root_raw)
    matches: List[Dict[str, Any]] = []

    def walk() -> None:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))][:40]
            for name in filenames + dirnames:
                if fnmatch.fnmatch(name.lower(), f"*{pattern.lower()}*"):
                    matches.append({"path": os.path.join(dirpath, name), "name": name})
                    if len(matches) >= limit:
                        return

    await asyncio.to_thread(walk)
    listing = "\n".join(m["path"] for m in matches[:20])
    return {
        "ok": True,
        "pattern": pattern,
        "count": len(matches),
        "matches": matches,
        "output": listing or f"no files matching '{pattern}' under {root}",
    }


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="list_directory",
            description="List the contents of a folder.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Folder path (default '~')."}},
                "required": ["path"],
            },
            risk=RiskLevel.SAFE,
            category="files",
            handler=_list_directory,
        ),
        ToolSpec(
            name="read_file",
            description="Read a text file's contents.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "max_chars": {"type": "integer", "description": "Maximum characters to return (default 6000)."},
                },
                "required": ["path"],
            },
            risk=RiskLevel.SAFE,
            category="files",
            handler=_read_file,
        ),
        ToolSpec(
            name="write_file",
            description="Create or overwrite a text file (or append to it).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path."},
                    "content": {"type": "string", "description": "Text to write."},
                    "append": {"type": "boolean", "description": "Append instead of overwrite."},
                },
                "required": ["path", "content"],
            },
            risk=RiskLevel.SENSITIVE,
            category="files",
            handler=_write_file,
        ),
        ToolSpec(
            name="delete_file",
            description="Delete a file or an empty folder. Always asks for confirmation first.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path to delete."}},
                "required": ["path"],
            },
            risk=RiskLevel.DANGEROUS,
            category="files",
            handler=_delete_file,
        ),
        ToolSpec(
            name="search_files",
            description="Find files whose name matches a pattern under a folder.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Name fragment or glob, e.g. '*.pdf' or 'report'."},
                    "path": {"type": "string", "description": "Folder to search (default '~')."},
                    "limit": {"type": "integer", "description": "Maximum results (default 25)."},
                },
                "required": ["pattern"],
            },
            risk=RiskLevel.SAFE,
            category="files",
            handler=_search_files,
        ),
    ]
