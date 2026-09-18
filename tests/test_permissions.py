"""The permission layer: the model must never act un-gated."""

from __future__ import annotations

import asyncio

import pytest

from jarvis.config import SecurityConfig
from jarvis.core.permissions import Decision, PermissionManager, Risk
from jarvis.events import EventBus


def manager(**kwargs) -> PermissionManager:
    return PermissionManager(SecurityConfig(**kwargs))


def test_safe_tools_are_auto_approved():
    pm = manager()
    assert pm.evaluate("system_status", Risk.SAFE)[0] is Decision.ALLOW


def test_sensitive_tools_ask_for_confirmation():
    pm = manager()
    decision, reason = pm.evaluate("close_application", Risk.SENSITIVE)
    assert decision is Decision.CONFIRM
    assert "confirm" in reason


def test_dangerous_tools_without_shell_are_confirmed():
    pm = manager(allow_shell=False)
    assert pm.evaluate("run_command", Risk.DANGEROUS)[0] is Decision.CONFIRM
    pm2 = manager(allow_shell=True, mode="allow-all")
    assert pm2.evaluate("run_command", Risk.DANGEROUS)[0] is Decision.ALLOW


def test_denied_list_wins():
    pm = manager(denied=["delete_file"])
    assert pm.evaluate("delete_file", Risk.SAFE)[0] is Decision.DENY


def test_auto_approve_and_require_confirm():
    pm = manager(auto_approve=["write_file"], require_confirm=["open_application"])
    assert pm.evaluate("write_file", Risk.SENSITIVE)[0] is Decision.ALLOW
    assert pm.evaluate("open_application", Risk.SAFE)[0] is Decision.CONFIRM


def test_modes():
    assert manager(mode="allow-all").evaluate("x", Risk.SENSITIVE)[0] is Decision.ALLOW
    assert manager(mode="deny-sensitive").evaluate("x", Risk.SENSITIVE)[0] is Decision.DENY
    assert manager(mode="deny-sensitive").evaluate("x", Risk.SAFE)[0] is Decision.ALLOW


def test_gate_confirmation_flow():
    async def run():
        bus = EventBus()
        pm = PermissionManager(SecurityConfig(), bus)
        task = asyncio.create_task(pm.gate("delete_file", {"path": "x"}, Risk.DANGEROUS))
        await asyncio.sleep(0)
        pending = pm.pending()
        assert len(pending) == 1 and pending[0]["tool"] == "delete_file"
        assert bus.publish.__self__ is bus  # events were emitted
        pm.resolve(pending[0]["id"], True)
        allowed, reason = await task
        assert allowed and reason == "user approved"

    asyncio.run(run())


def test_gate_denial_flow():
    async def run():
        pm = manager()
        task = asyncio.create_task(pm.gate("delete_file", {}, Risk.DANGEROUS))
        await asyncio.sleep(0)
        pm.resolve(pm.pending()[0]["id"], False)
        allowed, reason = await task
        assert allowed is False and reason == "user declined"

    asyncio.run(run())


def test_gate_timeout():
    async def run():
        pm = manager(confirm_timeout=0.05)
        allowed, reason = await pm.gate("delete_file", {}, Risk.DANGEROUS, timeout=0.05)
        assert allowed is False and "timed out" in reason

    asyncio.run(run())


def test_remember_adds_session_approval():
    async def run():
        pm = manager()
        task = asyncio.create_task(pm.gate("write_file", {}, Risk.SENSITIVE))
        await asyncio.sleep(0)
        pm.resolve(pm.pending()[0]["id"], True, remember=True)
        await task
        assert pm.evaluate("write_file", Risk.SENSITIVE)[0] is Decision.ALLOW

    asyncio.run(run())


def test_approve_all_and_deny_all():
    async def run():
        pm = manager()
        t1 = asyncio.create_task(pm.gate("a", {}, Risk.SENSITIVE))
        t2 = asyncio.create_task(pm.gate("b", {}, Risk.SENSITIVE))
        await asyncio.sleep(0)
        assert pm.approve_all() == 2
        assert all(await asyncio.gather(t1, t2))

        t3 = asyncio.create_task(pm.gate("c", {}, Risk.SENSITIVE))
        await asyncio.sleep(0)
        assert pm.deny_all() == 1
        assert (await t3)[0] is False

    asyncio.run(run())


def test_resolve_unknown_request_returns_false():
    assert manager().resolve("nope", True) is False
