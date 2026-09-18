"""Voice layer: wake word -> speech-to-text -> text-to-speech.

Every stage is optional and degrades independently:

* **wake word**  openWakeWord (has a built-in ``hey jarvis`` model)
* **STT**        whisper.cpp / faster-whisper (local) or OpenAI (cloud)
* **TTS**        Piper (local neural voices) with a pyttsx3 fallback

Nothing here is imported eagerly — the assistant runs fine with all three
missing, and ``jarvis doctor`` tells you exactly which pieces to install.
"""

from __future__ import annotations

import shutil
from typing import Any, Dict

from ..config import VoiceConfig


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def voice_status(cfg: VoiceConfig) -> Dict[str, Any]:
    """Report which voice subsystems are usable right now."""
    piper = shutil.which(cfg.piper_binary or "piper") is not None
    whisper_bin = shutil.which(cfg.stt_binary or "whisper-cli") is not None
    fw = _importable("faster_whisper")
    oww = _importable("openwakeword")
    sd = _importable("sounddevice")
    pyttsx3 = _importable("pyttsx3")

    stt_engine = (cfg.stt_engine or "none").lower()
    stt_ready = (
        (stt_engine == "whisper_cpp" and whisper_bin)
        or (stt_engine == "faster_whisper" and fw)
        or (stt_engine == "openai" and bool(__import__("os").environ.get("OPENAI_API_KEY")))
    )
    tts_ready = (
        ((cfg.tts_engine or "none").lower() == "piper" and piper)
        or ((cfg.tts_engine or "none").lower() == "pyttsx3" and pyttsx3)
    )
    return {
        "enabled": bool(cfg.enabled),
        "wake_word": {
            "engine": cfg.wake_engine,
            "word": cfg.wake_word,
            "available": oww and sd,
            "missing": [m for m, ok in (("openwakeword", oww), ("sounddevice", sd)) if not ok],
        },
        "stt": {
            "engine": stt_engine,
            "model": cfg.stt_model,
            "language": cfg.stt_language or "auto",
            "available": bool(stt_ready),
            "whisper_cpp_binary": whisper_bin,
            "faster_whisper": fw,
        },
        "tts": {
            "engine": cfg.tts_engine,
            "voice": cfg.tts_voice,
            "available": bool(tts_ready),
            "piper_binary": piper,
            "pyttsx3": pyttsx3,
        },
        "capture": {"available": sd, "missing": [] if sd else ["sounddevice"]},
    }


from .pipeline import VoicePipeline  # noqa: E402  (after helpers)
from .stt import Transcriber  # noqa: E402
from .tts import Speaker  # noqa: E402
from .wake_word import WakeWordListener  # noqa: E402

__all__ = [
    "VoicePipeline",
    "WakeWordListener",
    "Transcriber",
    "Speaker",
    "voice_status",
]
