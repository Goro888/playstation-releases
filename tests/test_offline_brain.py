"""The offline brain — intent routing and narration (EN + AR)."""

from __future__ import annotations

import pytest

from jarvis.models.offline import OfflineBrain, is_arabic
from jarvis.tools import build_registry


@pytest.fixture
def brain(cfg) -> OfflineBrain:
    return OfflineBrain(cfg.persona, build_registry(cfg).names())


@pytest.mark.parametrize(
    "text,tool,arg_key,arg_value",
    [
        ("open chrome", "open_application", "name", "chrome"),
        ("open visual studio code", "open_application", "name", "visual studio code"),
        ("close notepad", "close_application", "name", "notepad"),
        ("list files in downloads", "list_directory", "path", "downloads"),
        ("read file notes.txt", "read_file", "path", "notes.txt"),
        ("search the web for gold prices", "web_search", "query", "gold prices"),
        ("what time is it", "get_time", None, None),
        ("system status", "system_status", None, None),
        ("take a screenshot", "capture_screen", None, None),
        ("what is on my screen", "analyze_screen", None, None),
        ("remember that my editor is vscode", "remember", "content", "my editor is vscode"),
        ("what do you remember about vscode", "recall", "query", "vscode"),
        ("remind me to call mum", "add_task", "title", "call mum"),
        ("list my tasks", "list_tasks", None, None),
    ],
)
def test_english_intents(brain: OfflineBrain, text, tool, arg_key, arg_value):
    call = brain.route(text)
    assert call is not None, f"no intent matched {text!r}"
    assert call.name == tool, f"{text!r} -> {call.name} (expected {tool})"
    if arg_key:
        assert call.arguments[arg_key].lower() == arg_value.lower()


@pytest.mark.parametrize(
    "text,tool",
    [
        ("افتح المتصفح", "open_application"),
        ("أغلق الحاسبة", "close_application"),
        ("اعرض الملفات", "list_directory"),
        ("ابحث عن سعر الذهب", "web_search"),
        ("تذكر أن الاجتماع غداً", "remember"),
        ("ماذا تتذكر", "recall"),
        ("حالة الجهاز", "system_status"),
        ("الساعة", "get_time"),
        ("لقطة شاشة", "capture_screen"),
        ("ماذا على الشاشة", "analyze_screen"),
    ],
)
def test_arabic_intents(brain: OfflineBrain, text, tool):
    call = brain.route(text)
    assert call is not None, f"no intent matched {text!r}"
    assert call.name == tool


def test_unknown_text_has_no_tool_call(brain: OfflineBrain):
    assert brain.route("tell me a story about the sea") is None


def test_is_arabic():
    assert is_arabic("مرحبا") is True
    assert is_arabic("hello") is False


def test_narration_uses_tool_results(brain: OfflineBrain):
    from jarvis.models.base import Message, ToolCall

    messages = [
        Message(role="user", content="open chrome"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="1", name="open_application", arguments={"name": "chrome"})]),
        Message(role="tool", content='{"ok": true, "output": "launched chrome"}', tool_call_id="1", name="open_application"),
    ]
    text = brain.narrate(messages)
    assert "chrome" in text.lower()


def test_narration_reports_failures(brain: OfflineBrain):
    from jarvis.models.base import Message, ToolCall

    messages = [
        Message(role="user", content="delete file x"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="1", name="delete_file", arguments={"path": "x"})]),
        Message(role="tool", content='{"ok": false, "output": "permission denied"}', tool_call_id="1", name="delete_file"),
    ]
    assert "permission denied" in brain.narrate(messages)


def test_fallback_message_mentions_offline_mode(brain: OfflineBrain):
    assert "offline" in brain.fallback("explain quantum physics").lower()
    assert "نموذج" in brain.fallback("اشرح لي الفيزياء")


def test_unregistered_tools_are_never_called(cfg):
    brain = OfflineBrain(cfg.persona, ["get_time"])
    assert brain.route("open chrome") is None
    assert brain.route("what time is it").name == "get_time"
