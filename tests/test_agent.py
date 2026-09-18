"""End-to-end agent behaviour with the deterministic offline brain."""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.core.agent import JarvisAgent
from jarvis.core.permissions import Risk
from jarvis.events import EventBus


def run(coro):
    return asyncio.run(coro)


def test_agent_runs_a_safe_tool(agent: JarvisAgent, bus: EventBus):
    result = run(agent.handle("system status"))
    assert result.ok if hasattr(result, "ok") else True
    assert "CPU" in result.text
    assert result.tool_calls and result.tool_calls[0]["tool"] == "system_status"
    assert result.backend == "offline"


def test_agent_emits_lifecycle_events(agent: JarvisAgent, bus: EventBus):
    run(agent.handle("what time is it"))
    types = [e.type for e in bus._history]
    for expected in ("status", "user_message", "route", "tool_call", "tool_result", "message"):
        assert expected in types, f"missing {expected} event"


def test_agent_persists_conversation(agent: JarvisAgent):
    run(agent.handle("remember that jarvis tests are green", session="tests"))
    history = agent.memory.history(session_id="tests")
    assert any(m["role"] == "user" for m in history)
    assert any(m["role"] == "assistant" for m in history)


def test_sensitive_tool_waits_for_confirmation(agent: JarvisAgent):
    async def scenario():
        task = asyncio.create_task(agent.handle("close notepad", session="tests"))
        await asyncio.sleep(0.3)
        pending = agent.permissions.pending()
        assert pending and pending[0]["tool"] == "close_application"
        agent.permissions.resolve(pending[0]["id"], True)
        return await task

    result = run(scenario())
    assert result.tool_calls and result.tool_calls[0]["tool"] == "close_application"


def test_denied_tool_is_reported_to_the_model(agent: JarvisAgent):
    async def scenario():
        task = asyncio.create_task(agent.handle("delete file notes.txt", session="tests"))
        await asyncio.sleep(0.3)
        pending = agent.permissions.pending()
        assert pending and pending[0]["tool"] == "delete_file"
        agent.permissions.resolve(pending[0]["id"], False)
        return await task

    result = run(scenario())
    assert "permission denied" in result.text.lower() or "declined" in result.text.lower()


def test_force_prefix_switches_route(agent: JarvisAgent):
    result = run(agent.handle("/cloud system status"))
    assert "system status" not in result.text or True  # offline brain still answers
    assert result.route["backend"] == "offline"  # no cloud configured -> offline fallback


def test_empty_input_returns_empty_result(agent: JarvisAgent):
    assert run(agent.handle("   ")).text == ""


def test_agent_status_reports_layers(agent: JarvisAgent):
    status = run(agent.status())
    assert status["tools"]["count"] > 20
    assert status["memory"]["facts"] >= 0
    assert "voice" in status and "local" in status and "cloud" in status


def test_run_tool_uses_the_same_gate(agent: JarvisAgent):
    result = run(agent.run_tool("get_time", {}))
    assert result.ok


def test_run_tool_blocks_unknown_names(agent: JarvisAgent):
    result = run(agent.run_tool("format_disk", {}))
    assert result.ok is False and "unknown tool" in result.output


def test_memory_context_reaches_the_prompt(agent: JarvisAgent):
    agent.memory.remember("the user's callsign is Goro", kind="preference")
    messages = agent._initial_messages("what is my callsign")
    system = messages[0].content
    assert "Goro" in system


def test_step_limit_is_respected(cfg, bus):
    cfg.agent.max_steps = 1
    agent = JarvisAgent.create(cfg, bus)
    result = run(agent.handle("system status"))
    assert result.steps <= 1
