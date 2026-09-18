"""Configuration loading and env overrides."""

from __future__ import annotations

import os

import pytest

from jarvis.config import JarvisConfig, _deep_merge, _normalize_base_url


def test_defaults_are_complete():
    cfg = JarvisConfig()
    assert cfg.persona.name == "JARVIS"
    assert cfg.router.mode == "hybrid"
    assert cfg.local.backend == "ollama"
    assert cfg.security.mode == "confirm-sensitive"
    assert cfg.bridge.port == 8770
    assert cfg.voice.wake_word == "hey jarvis"


def test_load_missing_file_returns_defaults(tmp_path):
    cfg = JarvisConfig.load(tmp_path / "nope.yaml")
    assert cfg.persona.name == "JARVIS"


def test_load_yaml_overrides(tmp_path):
    path = tmp_path / "jarvis.yaml"
    path.write_text(
        """
persona:
  name: JARVIS
  user_title: boss
local:
  model: custom-model:7b
router:
  mode: local
security:
  auto_approve: [open_application]
""",
        encoding="utf-8",
    )
    cfg = JarvisConfig.load(path)
    assert cfg.persona.user_title == "boss"
    assert cfg.local.model == "custom-model:7b"
    assert cfg.router.mode == "local"
    assert cfg.security.auto_approve == ["open_application"]


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "192.168.0.5:11434")
    monkeypatch.setenv("JARVIS_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("JARVIS_PORT", "9999")
    cfg = JarvisConfig.load()
    assert cfg.local.base_url == "http://192.168.0.5:11434"
    assert cfg.local.model == "qwen2.5:3b"
    assert cfg.bridge.port == 9999


def test_unknown_keys_are_ignored():
    cfg = JarvisConfig.from_dict({"local": {"not_a_field": 1}, "bogus_section": {"x": 1}})
    assert cfg.local.model == "qwen3.5:4b"


def test_deep_merge():
    merged = _deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}})
    assert merged == {"a": {"b": 1, "c": 3}}


def test_normalize_base_url():
    assert _normalize_base_url("localhost:11434/") == "http://localhost:11434"
    assert _normalize_base_url("http://x:1/") == "http://x:1"


def test_save_roundtrip(tmp_path):
    cfg = JarvisConfig()
    cfg.local.model = "saved-model"
    out = cfg.save(tmp_path / "config.yaml")
    assert out.exists()
    reloaded = JarvisConfig.load(out)
    assert reloaded.local.model == "saved-model"


def test_roundtrip_preserves_custom_paths(tmp_path):
    """A saved config must keep every field the docs tell users to set."""
    cfg = JarvisConfig()
    cfg.voice.piper_model_dir = str(tmp_path / "piper")
    cfg.tools.allowed_roots = [str(tmp_path)]
    out = cfg.save(tmp_path / "config.yaml")
    reloaded = JarvisConfig.load(out)
    assert reloaded.voice.piper_model_dir == str(tmp_path / "piper")
    assert reloaded.tools.allowed_roots == [str(tmp_path)]


@pytest.mark.parametrize("mode", ["offline", "local", "cloud", "hybrid"])
def test_router_modes_accepted(mode):
    cfg = JarvisConfig.from_dict({"router": {"mode": mode}})
    assert cfg.router.mode == mode
