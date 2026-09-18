"""Shared pytest fixtures."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from jarvis.config import JarvisConfig, MemoryConfig, SecurityConfig
from jarvis.core.agent import JarvisAgent
from jarvis.core.memory import Memory
from jarvis.core.permissions import PermissionManager
from jarvis.events import EventBus
from jarvis.tools import build_registry


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Isolate JARVIS_HOME so tests never touch the real machine."""
    home = tmp_path / "jarvis-home"
    home.mkdir()
    monkeypatch.setenv("JARVIS_HOME", str(home))
    return home


@pytest.fixture
def cfg(tmp_home) -> JarvisConfig:
    config = JarvisConfig()
    config.memory.db_path = str(tmp_home / "memory.db")
    config.memory.store_conversations = True
    config.tools.screenshot_dir = str(tmp_home / "shots")
    config.tools.allowed_roots = [str(tmp_home)]
    config.voice.models_dir = str(tmp_home / "models")
    config.voice.piper_model_dir = str(tmp_home / "models" / "piper")
    config.router.mode = "offline"  # deterministic: never reaches for a model
    config.local.base_url = "http://127.0.0.1:9"  # closed port -> instant refusal
    config.security.allow_shell = False
    return config


@pytest.fixture
def memory(cfg) -> Memory:
    return Memory(cfg.memory)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def permissions(cfg, bus) -> PermissionManager:
    return PermissionManager(cfg.security, bus)


@pytest.fixture
def registry(cfg):
    return build_registry(cfg)


@pytest.fixture
def agent(cfg, bus) -> JarvisAgent:
    return JarvisAgent.create(cfg, bus)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
