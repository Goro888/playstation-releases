"""Bridge API smoke tests (FastAPI TestClient, no network)."""

from __future__ import annotations

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    pytest.skip("fastapi testclient unavailable", allow_module_level=True)

from jarvis.bridge import create_app
from jarvis.core.agent import JarvisAgent
from jarvis.events import EventBus


@pytest.fixture
def client(cfg) -> TestClient:
    bus = EventBus()
    agent = JarvisAgent.create(cfg, bus)
    app = create_app(cfg, agent, bus)
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    assert client.get("/api/health").json()["ok"] is True


def test_status_is_complete(client: TestClient):
    body = client.get("/api/status").json()
    for key in ("local", "cloud", "tools", "memory", "voice", "security"):
        assert key in body


def test_chat_runs_a_tool(client: TestClient):
    body = client.post("/api/chat", json={"message": "system status", "session": "tests"}).json()
    assert body["ok"] is True
    assert "CPU" in body["reply"]


def test_chat_requires_a_message(client: TestClient):
    assert client.post("/api/chat", json={}).status_code == 400


def test_tools_endpoint(client: TestClient):
    tools = client.get("/api/tools").json()["tools"]
    assert any(t["name"] == "open_application" for t in tools)


def test_tool_call_endpoint(client: TestClient):
    body = client.post("/api/tools/call", json={"name": "get_time", "args": {}}).json()
    assert body["ok"] is True


def test_permission_flow_over_http(client: TestClient):
    """A tool call parked for confirmation can be approved over HTTP."""
    import asyncio

    from jarvis.core.permissions import Risk

    agent = client.app.state.agent
    pm = agent.permissions
    loop = asyncio.new_event_loop()

    def start():
        task = loop.create_task(pm.gate("delete_file", {"path": "x"}, Risk.DANGEROUS))
        loop.run_until_complete(asyncio.sleep(0.05))
        return task

    try:
        task = start()
        pending = client.get("/api/permissions").json()["pending"]
        assert pending and pending[0]["tool"] == "delete_file"
        assert client.post(f"/api/permissions/{pending[0]['id']}/approve").json()["ok"] is True
        assert loop.run_until_complete(task)[0] is True
    finally:
        loop.close()


def test_memory_endpoints(client: TestClient):
    created = client.post("/api/memory", json={"content": "test fact", "kind": "note"}).json()
    assert created["ok"] is True
    found = client.get("/api/memory?q=test").json()
    assert any("test fact" in f["content"] for f in found["facts"])
    fact_id = created["fact"]["id"]
    assert client.delete(f"/api/memory/{fact_id}").json()["ok"] is True


def test_task_endpoints(client: TestClient):
    task = client.post("/api/tasks", json={"title": "write tests"}).json()["task"]
    assert task["title"] == "write tests"
    assert client.get("/api/tasks").json()["tasks"]
    assert client.post(f"/api/tasks/{task['id']}/done").json()["ok"] is True


def test_system_endpoint(client: TestClient):
    body = client.get("/api/system").json()
    assert "cpu_percent" in body and "ram_total_gb" in body


def test_voice_status_endpoint(client: TestClient):
    body = client.get("/api/voice/status").json()
    assert "running" in body and "stt" in body


def test_config_endpoint_redacts_cloud(client: TestClient):
    body = client.get("/api/config").json()
    assert "base_url" not in body["cloud"]
    assert body["local"]["model"]


def test_events_history_endpoint(client: TestClient):
    client.post("/api/chat", json={"message": "what time is it", "session": "tests"})
    events = client.get("/api/history?limit=10").json()["events"]
    assert any(e["type"] == "message" for e in events)


def test_conversation_endpoint(client: TestClient):
    client.post("/api/chat", json={"message": "system status", "session": "conv"})
    messages = client.get("/api/conversation?session=conv").json()["messages"]
    assert any(m["role"] == "assistant" for m in messages)
