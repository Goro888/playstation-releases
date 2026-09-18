"""The tool registry — the only way the model can touch the machine."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import platform as _platform
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .base import ToolContext, ToolResult, ToolSpec

log = logging.getLogger("jarvis.tools")


class ToolRegistry:
    """Holds tool specs and executes them with uniform error handling."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    # -- registration -----------------------------------------------------
    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            log.debug("tool %s already registered — overwriting", spec.name)
        self._tools[spec.name] = spec
        return spec

    def register_many(self, specs: Iterable[ToolSpec]) -> None:
        for spec in specs:
            self.register(spec)

    # -- lookup -----------------------------------------------------------
    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def specs(self, categories: Optional[Sequence[str]] = None) -> List[ToolSpec]:
        items = list(self._tools.values())
        if categories is not None:
            wanted = set(categories)
            items = [t for t in items if t.category in wanted]
        return sorted(items, key=lambda t: (t.category, t.name))

    def available(self, categories: Optional[Sequence[str]] = None, system: str = "") -> List[ToolSpec]:
        system = system or _platform.system().lower()
        return [t for t in self.specs(categories) if t.platforms is None or system in t.platforms]

    def schemas(self, categories: Optional[Sequence[str]] = None, system: str = "") -> List[Dict[str, Any]]:
        return [t.openai_schema() for t in self.available(categories, system)]

    def describe(self, categories: Optional[Sequence[str]] = None, system: str = "") -> List[Dict[str, Any]]:
        out = []
        system = system or _platform.system().lower()
        for t in self.specs(categories):
            d = t.to_dict()
            d["available"] = t.platforms is None or system in t.platforms
            out.append(d)
        return out

    # -- execution --------------------------------------------------------
    async def execute(self, name: str, args: Optional[Dict[str, Any]], ctx: ToolContext) -> ToolResult:
        spec = self._tools.get(name)
        args = args or {}
        if spec is None:
            known = ", ".join(self.names())
            return ToolResult(ok=False, tool=name, output=f"unknown tool '{name}'", error=f"unknown tool; known tools: {known}")

        system = (ctx.platform or _platform.system()).lower()
        if spec.platforms is not None and system not in spec.platforms:
            msg = f"'{name}' is only available on {', '.join(spec.platforms)} (running {system})"
            return ToolResult(ok=False, tool=name, output=msg, error=msg)

        missing = [k for k in spec.required_params if k not in args or args[k] in (None, "")]
        if missing:
            msg = f"missing required argument(s): {', '.join(missing)}"
            return ToolResult(ok=False, tool=name, output=msg, error=msg)

        if spec.handler is None:
            return ToolResult(ok=False, tool=name, output=f"tool '{name}' has no handler", error="no handler")

        try:
            result = spec.handler(args, ctx)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=60)
        except asyncio.TimeoutError:
            return ToolResult(ok=False, tool=name, output=f"'{name}' timed out", error="timeout")
        except Exception as exc:  # noqa: BLE001 - tools must never crash the agent
            log.exception("tool %s failed", name)
            return ToolResult(ok=False, tool=name, output=f"{type(exc).__name__}: {exc}", error=str(exc))

        return _normalize(name, result)


def _normalize(name: str, result: Any) -> ToolResult:
    if isinstance(result, ToolResult):
        result.tool = result.tool or name
        return result
    if isinstance(result, str):
        return ToolResult(ok=True, tool=name, output=result)
    if isinstance(result, dict):
        ok = result.pop("ok", True) if "ok" in result else True
        output = result.pop("output", None)
        error = result.pop("error", None)
        data = result
        if output is None:
            if error:
                output = error
            else:
                output = json.dumps(data, ensure_ascii=False) if data else ""
        return ToolResult(ok=bool(ok), tool=name, output=str(output), data=data or None, error=error)
    if isinstance(result, (list, tuple)):
        text = "\n".join(str(x) for x in result)
        return ToolResult(ok=True, tool=name, output=text, data=list(result))
    return ToolResult(ok=True, tool=name, output=str(result), data=result)


# --------------------------------------------------------------------------
# decorator sugar
# --------------------------------------------------------------------------
def tool(
    name: str,
    description: str,
    *,
    properties: Optional[Dict[str, Any]] = None,
    required: Sequence[str] = (),
    risk: str = "safe",
    category: str = "misc",
    platforms: Optional[Sequence[str]] = None,
    requires: Sequence[str] = (),
):
    """Register an async function as a tool (used by ``build_registry``)."""

    def decorator(fn):
        fn.__tool_spec__ = ToolSpec(
            name=name,
            description=description,
            parameters={"type": "object", "properties": properties or {}, "required": list(required)},
            risk=risk,
            category=category,
            platforms=platforms,
            handler=fn,
            requires=requires,
        )
        return fn

    return decorator
