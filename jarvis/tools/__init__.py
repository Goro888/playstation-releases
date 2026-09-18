"""The tool layer — everything the assistant is allowed to *do*.

Each module returns a list of :class:`ToolSpec`. ``build_registry`` assembles
them into a :class:`ToolRegistry`, filtered by the enabled categories in
``tools.enabled``.
"""

from __future__ import annotations

from typing import Optional

from ..config import JarvisConfig
from ..core.memory import Memory
from ..core.permissions import PermissionManager
from ..events import EventBus
from .base import Risk, ToolContext, ToolResult, ToolSpec
from .clipboard_tools import specs as clipboard_specs
from .file_tools import specs as file_specs
from .memory_tools import specs as memory_specs
from .misc_tools import specs as misc_specs
from .registry import ToolRegistry, tool
from .screen_tools import specs as screen_specs
from .system_tools import specs as system_specs
from .ui_tools import specs as ui_specs
from .web_tools import specs as web_specs

__all__ = [
    "Risk",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "build_registry",
    "build_context",
]

_MODULES = (
    system_specs,
    file_specs,
    clipboard_specs,
    ui_specs,
    screen_specs,
    web_specs,
    memory_specs,
    misc_specs,
)


def build_registry(cfg: JarvisConfig) -> ToolRegistry:
    """Create a registry containing only the enabled tool categories."""
    enabled = set(cfg.tools.enabled or []) or {"system", "files", "clipboard", "ui", "screen", "web", "memory", "misc"}
    registry = ToolRegistry()
    for module in _MODULES:
        for spec in module():
            if spec.category in enabled:
                registry.register(spec)
    if not cfg.security.allow_shell:
        # keep the tool listed for transparency; the permission layer still blocks it
        run_spec = registry.get("run_command")
        if run_spec is not None:
            run_spec.description += " [currently blocked: security.allow_shell=false]"
    return registry


def build_context(
    cfg: JarvisConfig,
    *,
    memory: Optional[Memory] = None,
    permissions: Optional[PermissionManager] = None,
    bus: Optional[EventBus] = None,
    session: str = "default",
    platform: str = "",
    vision=None,
) -> ToolContext:
    import platform as _platform

    return ToolContext(
        cfg=cfg,
        memory=memory,
        permissions=permissions,
        bus=bus,
        session=session,
        platform=(platform or _platform.system()).lower(),
        vision=vision,
    )
