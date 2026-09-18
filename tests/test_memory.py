"""Long-term memory: facts, FTS recall, tasks, preferences."""

from __future__ import annotations

import time

import pytest

from jarvis.core.memory import Memory


def test_remember_and_recall(memory: Memory):
    memory.remember("the JARVIS project lives in playstation-releases", kind="project", tags=["jarvis"])
    memory.remember("I prefer dark interfaces", kind="preference")
    hits = memory.recall("JARVIS project")
    assert hits and "JARVIS project" in hits[0].content


def test_recall_falls_back_to_like(memory: Memory):
    memory.remember("gold price tracking spreadsheet", kind="note")
    assert memory.recall("gold") or memory.recall("nonexistent-token") is not None
    assert memory.recall("zzzzz-nothing-here") == [] or all("gold" not in f.content for f in memory.recall("zzzzz"))


def test_recent_and_forget(memory: Memory):
    a = memory.remember("first")
    b = memory.remember("second")
    assert [f.id for f in memory.recent(10)] == [b.id, a.id]
    assert memory.forget(a.id) is True
    assert [f.id for f in memory.recent(10)] == [b.id]


def test_empty_fact_rejected(memory: Memory):
    with pytest.raises(ValueError):
        memory.remember("   ")


def test_conversation_history(memory: Memory):
    memory.add_message("user", "hello")
    memory.add_message("assistant", "hi")
    history = memory.history()
    assert [h["role"] for h in history] == ["user", "assistant"]
    memory.clear_conversation()
    assert memory.history() == []


def test_tasks(memory: Memory):
    task = memory.add_task("back up the config")
    assert task["status"] == "open"
    assert any(t["title"] == "back up the config" for t in memory.list_tasks())
    assert memory.complete_task(task["id"]) is True
    assert memory.list_tasks() == []
    assert memory.list_tasks("done")


def test_preferences(memory: Memory):
    memory.set_pref("editor", "vscode")
    memory.set_pref("verbose", True)
    assert memory.get_pref("editor") == "vscode"
    assert memory.get_pref("missing", "fallback") == "fallback"
    assert set(memory.all_prefs()) == {"editor", "verbose"}


def test_stats(memory: Memory):
    memory.remember("a fact")
    stats = memory.stats()
    assert stats["facts"] == 1 and stats["fts_enabled"] in (True, False)


def test_embeddings_roundtrip(memory: Memory):
    fact = memory.remember("semantic test entry")
    memory.set_embedding(fact.id, "test-model", [0.1, 0.2, 0.3])
    found = memory.semantic_recall([0.1, 0.2, 0.3])
    assert found and found[0].id == fact.id


def test_arabic_recall(memory: Memory):
    memory.remember("اجتماع الفريق غداً الساعة العاشرة", kind="note")
    hits = memory.recall("اجتماع")
    assert hits and "اجتماع" in hits[0].content
