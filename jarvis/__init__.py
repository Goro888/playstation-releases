"""JARVIS — a layered, local-first AI operating assistant.

Layers (bottom -> top)::

    Windows control    jarvis.tools.*      (apps, files, UI Automation, screen, clipboard)
    Memory             jarvis.core.memory  (SQLite + FTS5 + optional embeddings)
    AI brain           jarvis.models.*     (Ollama/Qwen local, OpenAI-compatible cloud, offline fallback)
    Agent core         jarvis.core.agent   (planning, tool loop, permissions)
    Voice              jarvis.voice.*      (openWakeWord -> Whisper -> Piper)
    API bridge         jarvis.bridge       (FastAPI + SSE)
    HUD                hud/                (React dark HUD)

Everything degrades gracefully: if Ollama is not running, the offline brain
still answers and still drives real tools. If Piper is missing, the reply is
returned as text. That makes the system usable from day one on a fresh Windows
box and progressively upgradeable as models are downloaded.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
