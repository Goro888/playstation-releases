"""Tool registry: registration, schemas, error handling, platform gating."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.config import JarvisConfig
from jarvis.tools import build_context, build_registry
from jarvis.tools.base import Risk, ToolContext, ToolResult, ToolSpec


@pytest.fixture
def ctx(cfg: JarvisConfig) -> ToolContext:
    return build_context(cfg, platform="windows")


def test_all_categories_register(cfg):
    registry = build_registry(cfg)
    categories = {s.category for s in registry.specs()}
    assert {"system", "files", "clipboard", "ui", "screen", "web", "memory", "misc"} <= categories
    assert len(registry.names()) > 20


def test_enabled_filter(tmp_home):
    cfg = JarvisConfig()
    cfg.tools.enabled = ["system"]
    cfg.memory.db_path = str(tmp_home / "m.db")
    registry = build_registry(cfg)
    assert {s.category for s in registry.specs()} == {"system"}


def test_openai_schema_shape(registry):
    schema = registry.get("open_application").openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "open_application"
    assert schema["function"]["parameters"]["required"] == ["name"]


def test_unknown_tool(registry, ctx):
    result = asyncio.run(registry.execute("nope", {}, ctx))
    assert result.ok is False and "unknown tool" in result.output


def test_missing_required_argument(registry, ctx):
    result = asyncio.run(registry.execute("open_application", {}, ctx))
    assert result.ok is False and "missing required argument" in result.output


def test_platform_gating(registry, ctx):
    result = asyncio.run(registry.execute("type_text", {"text": "hi"}, build_context(ctx.cfg, platform="linux")))
    assert result.ok is False and "only available on" in result.output


def test_handler_exception_is_captured(cfg, ctx):
    registry = build_registry(cfg)

    async def boom(args, context):
        raise RuntimeError("kaboom")

    registry.register(
        ToolSpec(name="boom", description="explodes", parameters={"type": "object", "properties": {}}, handler=boom)
    )
    result = asyncio.run(registry.execute("boom", {}, ctx))
    assert result.ok is False and "kaboom" in result.output


def test_result_normalisation(cfg, ctx):
    registry = build_registry(cfg)

    async def as_dict(args, context):
        return {"ok": True, "output": "hello", "extra": 1}

    async def as_str(args, context):
        return "plain"

    async def as_list(args, context):
        return ["a", "b"]

    registry.register(ToolSpec(name="d", description="", handler=as_dict))
    registry.register(ToolSpec(name="s", description="", handler=as_str))
    registry.register(ToolSpec(name="l", description="", handler=as_list))

    d = asyncio.run(registry.execute("d", {}, ctx))
    assert d.ok and d.output == "hello" and d.data == {"extra": 1}
    assert asyncio.run(registry.execute("s", {}, ctx)).output == "plain"
    assert asyncio.run(registry.execute("l", {}, ctx)).output == "a\nb"


def test_error_dict_uses_error_as_output(cfg, ctx):
    """A dict result with only an ``error`` key must surface that error."""
    registry = build_registry(cfg)

    async def failing(args, context):
        return {"ok": False, "error": "outside the allowed roots"}

    registry.register(ToolSpec(name="f", description="", handler=failing))
    result = asyncio.run(registry.execute("f", {}, ctx))
    assert result.ok is False
    assert result.output == "outside the allowed roots"


def test_describe_marks_availability(registry):
    described = {t["name"]: t for t in registry.describe(system="windows")}
    assert described["open_application"]["available"] is True
    assert described["type_text"]["available"] is True
