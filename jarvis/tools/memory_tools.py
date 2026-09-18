"""Memory tools — the model's own long-term store."""

from __future__ import annotations

from typing import Any, Dict, List

from .base import Risk as RiskLevel
from .base import ToolContext, ToolSpec


def _memory(ctx: ToolContext):
    if ctx.memory is None:
        raise RuntimeError("memory is disabled in this configuration")
    return ctx.memory


async def _remember(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    content = str(args.get("content") or "").strip()
    kind = str(args.get("kind") or "note")
    subject = str(args.get("subject") or "")
    tags = args.get("tags") or []
    importance = int(args.get("importance") or 3)
    fact = mem.remember(content, kind=kind, subject=subject, tags=tags, importance=importance, source="assistant")
    return {
        "ok": True,
        "content": content,
        "id": fact.id,
        "kind": kind,
        "output": f"remembered (id {fact.id}): {content}",
    }


async def _recall(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    query = str(args.get("query") or "").strip()
    limit = int(args.get("limit") or ctx.cfg.memory.recall_limit)
    facts = mem.recall(query, limit=limit) if query else mem.recent(limit)
    if not facts:
        return {"ok": True, "query": query, "facts": [], "output": "I have nothing stored about that yet."}
    lines = [f"• [{f.kind}] {f.content}" for f in facts]
    return {"ok": True, "query": query, "facts": [f.to_dict() for f in facts], "output": "\n".join(lines)}


async def _add_task(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    title = str(args.get("title") or "").strip()
    notes = str(args.get("notes") or "")
    task = mem.add_task(title, notes)
    return {"ok": True, "title": title, "id": task["id"], "output": f"task #{task['id']}: {title}"}


async def _list_tasks(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    status = str(args.get("status") or "open")
    tasks = mem.list_tasks(status)
    if not tasks:
        return {"ok": True, "tasks": [], "output": "No tasks with that status."}
    lines = [f"#{t['id']} {t['title']}" + (f" — {t['notes']}" if t.get("notes") else "") for t in tasks]
    return {"ok": True, "tasks": tasks, "output": "\n".join(lines)}


async def _complete_task(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    task_id = int(args.get("id") or 0)
    ok = mem.complete_task(task_id)
    return {"ok": ok, "id": task_id, "output": f"task #{task_id} completed" if ok else f"task #{task_id} not found"}


async def _set_preference(args: Dict[str, Any], ctx: ToolContext) -> Dict[str, Any]:
    mem = _memory(ctx)
    key = str(args.get("key") or "").strip()
    value = args.get("value")
    mem.set_pref(key, value)
    return {"ok": True, "key": key, "value": value, "output": f"preference '{key}' saved"}


def specs() -> List[ToolSpec]:
    return [
        ToolSpec(
            name="remember",
            description="Store a durable fact, preference or project note in long-term memory.",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The fact to remember."},
                    "kind": {"type": "string", "description": "note | preference | project | person | task"},
                    "subject": {"type": "string", "description": "Optional short subject label."},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
                    "importance": {"type": "integer", "description": "1 (low) to 5 (critical)."},
                },
                "required": ["content"],
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_remember,
        ),
        ToolSpec(
            name="recall",
            description="Search long-term memory for facts, preferences or past conversations.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "limit": {"type": "integer", "description": "Maximum facts to return."},
                },
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_recall,
        ),
        ToolSpec(
            name="add_task",
            description="Add a task or reminder to the task list.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title."},
                    "notes": {"type": "string", "description": "Optional notes."},
                },
                "required": ["title"],
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_add_task,
        ),
        ToolSpec(
            name="list_tasks",
            description="List tasks, optionally filtered by status (open | done).",
            parameters={
                "type": "object",
                "properties": {"status": {"type": "string", "description": "open (default) | done"}},
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_list_tasks,
        ),
        ToolSpec(
            name="complete_task",
            description="Mark a task as done.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "integer", "description": "Task id."}},
                "required": ["id"],
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_complete_task,
        ),
        ToolSpec(
            name="set_preference",
            description="Persist a user preference as a key/value pair.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Preference name."},
                    "value": {"type": "string", "description": "Preference value."},
                },
                "required": ["key", "value"],
            },
            risk=RiskLevel.SAFE,
            category="memory",
            handler=_set_preference,
        ),
    ]
