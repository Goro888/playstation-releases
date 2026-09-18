"""Speech-to-text (Whisper family).

Engines:
* ``whisper_cpp``    — local, CPU/GPU/NPU, uses the ``whisper-cli`` binary + a ggml model
* ``faster_whisper`` — local, CTranslate2 builds (also Windows-friendly)
* ``openai``         — cloud fallback (``whisper-1``)

Whisper supports Arabic natively, which is why it sits at the centre of the
hearing layer for this project.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..config import VoiceConfig

log = logging.getLogger("jarvis.voice.stt")


class Transcriber:
    """Turns a WAV file into text using whichever engine is installed."""

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self._fw_model = None

    # -- availability -----------------------------------------------------
    def probe(self) -> Dict[str, Any]:
        engine = (self.cfg.stt_engine or "none").lower()
        binary = shutil.which(self.cfg.stt_binary or "whisper-cli")
        model_path = self._ggml_model_path()
        if engine == "whisper_cpp":
            missing = [x for x, ok in (("whisper.cpp binary", bool(binary)),) if not ok]
            if not model_path:
                missing.append(f"ggml model ggml-{self.cfg.stt_model}.bin in {self.cfg.models_dir}")
            return {
                "engine": engine,
                "available": not missing,
                "binary": binary,
                "model_path": str(model_path) if model_path else "",
                "missing": missing,
                "hint": "download whisper.cpp + a ggml model into ~/.jarvis/models (see docs/WINDOWS_SETUP.md)",
            }
        if engine == "faster_whisper":
            ok = _importable("faster_whisper")
            return {
                "engine": engine,
                "available": ok,
                "model": self.cfg.stt_model,
                "missing": [] if ok else ["faster-whisper"],
                "hint": "pip install faster-whisper" if not ok else "",
            }
        if engine == "openai":
            ok = bool(os.environ.get("OPENAI_API_KEY"))
            return {
                "engine": engine,
                "available": ok,
                "missing": [] if ok else ["OPENAI_API_KEY"],
                "hint": "set OPENAI_API_KEY to use the cloud transcription tier",
            }
        return {"engine": "none", "available": False, "missing": [], "hint": ""}

    @property
    def available(self) -> bool:
        return bool(self.probe()["available"])

    def _ggml_model_path(self) -> Optional[Path]:
        base = Path(os.path.expanduser(self.cfg.models_dir))
        for candidate in (
            base / f"ggml-{self.cfg.stt_model}.bin",
            base / f"ggml-{self.cfg.stt_model}.en.bin",
            base / self.cfg.stt_model,
        ):
            if candidate.exists():
                return candidate
        return None

    async def transcribe(self, wav_path: str, language: Optional[str] = None) -> str:
        """Transcribe ``wav_path`` and return the text ('' on failure)."""
        engine = (self.cfg.stt_engine or "none").lower()
        lang = language or self.cfg.stt_language or ""
        if engine == "whisper_cpp":
            return await asyncio.to_thread(self._whisper_cpp, wav_path, lang)
        if engine == "faster_whisper":
            return await asyncio.to_thread(self._faster_whisper, wav_path, lang)
        if engine == "openai":
            return await self._openai(wav_path, lang)
        raise RuntimeError("no speech-to-text engine configured (voice.stt_engine)")

    # -- engines ----------------------------------------------------------
    def _whisper_cpp(self, wav_path: str, language: str) -> str:
        binary = shutil.which(self.cfg.stt_binary or "whisper-cli")
        model = self._ggml_model_path()
        if not binary:
            raise RuntimeError(
                f"whisper.cpp binary '{self.cfg.stt_binary}' not found on PATH — see docs/WINDOWS_SETUP.md"
            )
        if not model:
            raise RuntimeError(f"no ggml model for '{self.cfg.stt_model}' in {self.cfg.models_dir}")

        with tempfile.TemporaryDirectory() as tmp:
            cmd = [
                binary,
                "-m",
                str(model),
                "-f",
                wav_path,
                "--no-timestamps",
                "-otxt",
                "-of",
                os.path.join(tmp, "out"),
            ]
            if language:
                cmd += ["-l", language]
            try:
                subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
            except subprocess.TimeoutExpired:
                raise RuntimeError("whisper.cpp timed out") from None
            out_file = Path(tmp) / "out.txt"
            if not out_file.exists():
                raise RuntimeError("whisper.cpp produced no transcript")
            text = out_file.read_text(encoding="utf-8", errors="replace").strip()
        return _clean(text)

    def _faster_whisper(self, wav_path: str, language: str) -> str:
        from faster_whisper import WhisperModel  # type: ignore

        if self._fw_model is None:
            self._fw_model = WhisperModel(self.cfg.stt_model, device="auto", compute_type="auto")
        segments, _info = self._fw_model.transcribe(wav_path, language=language or None, beam_size=5)
        return _clean(" ".join(s.text for s in segments))

    async def _openai(self, wav_path: str, language: str) -> str:
        import httpx

        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        async with httpx.AsyncClient(timeout=120) as client:
            with open(wav_path, "rb") as fh:
                files = {"file": (os.path.basename(wav_path), fh, "audio/wav")}
                data = {"model": "whisper-1"}
                if language:
                    data["language"] = language
                r = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    files=files,
                    data=data,
                )
        r.raise_for_status()
        return _clean(r.json().get("text", ""))


def _clean(text: str) -> str:
    """Strip Whisper artefacts such as ``[BLANK_AUDIO]`` and bracketed tags."""
    import re

    text = re.sub(r"\[[^\]]+\]", " ", text or "")
    text = re.sub(r"<\|[^|]+\|>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False
