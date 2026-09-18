"""Text-to-speech — the JARVIS voice (Piper, local neural TTS).

Piper (``OHF-Voice/piper1-gpl``) runs entirely offline and ships a Python API,
a CLI and a server; here we drive the CLI because it is the easiest thing to
install on Windows. ``pyttsx3`` is the zero-download fallback so the assistant
can still speak on a machine with no voice model yet.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import VoiceConfig

log = logging.getLogger("jarvis.voice.tts")


class Speaker:
    """Synthesizes speech and plays it through the default output device."""

    def __init__(self, cfg: VoiceConfig) -> None:
        self.cfg = cfg
        self.out_dir = Path(os.path.expanduser(cfg.models_dir)).parent / "audio"
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # -- availability -----------------------------------------------------
    def probe(self) -> Dict[str, Any]:
        engine = (self.cfg.tts_engine or "none").lower()
        if engine == "piper":
            binary = shutil.which(self.cfg.piper_binary or "piper")
            voice = self._voice_model_path()
            missing = []
            if not binary:
                missing.append(f"piper binary '{self.cfg.piper_binary}'")
            if voice is None:
                missing.append(f"voice model {self.cfg.tts_voice}.onnx under {self.cfg.piper_model_dir}")
            return {
                "engine": "piper",
                "available": not missing,
                "binary": binary,
                "voice": self.cfg.tts_voice,
                "model_path": str(voice) if voice else "",
                "missing": missing,
                "hint": "download Piper + a voice .onnx into ~/.jarvis/models/piper (docs/WINDOWS_SETUP.md)",
            }
        if engine == "pyttsx3":
            ok = _importable("pyttsx3")
            return {
                "engine": "pyttsx3",
                "available": ok,
                "missing": [] if ok else ["pyttsx3"],
                "hint": "pip install pyttsx3" if not ok else "",
            }
        return {"engine": "none", "available": False, "missing": [], "hint": ""}

    @property
    def available(self) -> bool:
        return bool(self.probe()["available"])

    def _voice_model_path(self) -> Optional[Path]:
        base = Path(os.path.expanduser(self.cfg.piper_model_dir))
        for candidate in (
            base / f"{self.cfg.tts_voice}.onnx",
            base / self.cfg.tts_voice / f"{self.cfg.tts_voice}.onnx",
            base / self.cfg.tts_voice,
        ):
            if candidate.exists():
                return candidate
        # any installed voice is better than none
        if base.is_dir():
            for p in sorted(base.rglob("*.onnx")):
                return p
        return None

    # -- synthesis --------------------------------------------------------
    async def synthesize(self, text: str) -> Optional[str]:
        """Render ``text`` to a WAV file and return its path (None if quiet)."""
        text = (text or "").strip()
        if not text:
            return None
        engine = (self.cfg.tts_engine or "none").lower()
        if engine == "piper":
            return await asyncio.to_thread(self._piper, text)
        if engine == "pyttsx3":
            return await asyncio.to_thread(self._pyttsx3, text)
        return None

    async def speak(self, text: str) -> Dict[str, Any]:
        """Synthesize *and* play. Returns a status dict (never raises)."""
        try:
            path = await self.synthesize(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("TTS synthesis failed: %s", exc)
            return {"ok": False, "spoken": False, "error": str(exc)}
        if not path:
            return {"ok": True, "spoken": False, "reason": "no TTS engine configured"}
        played = await asyncio.to_thread(self._play, path)
        return {"ok": True, "spoken": played, "path": path, "chars": len(text)}

    # -- engines ----------------------------------------------------------
    def _piper(self, text: str) -> str:
        binary = shutil.which(self.cfg.piper_binary or "piper")
        model = self._voice_model_path()
        if not binary or model is None:
            raise RuntimeError("Piper is not installed — see docs/WINDOWS_SETUP.md")
        out = self.out_dir / f"jarvis_{int(time.time() * 1000)}.wav"
        cmd = [binary, "--model", str(model), "--output_file", str(out)]
        if self.cfg.piper_speaker:
            cmd += ["--speaker", str(self.cfg.piper_speaker)]
        if self.cfg.piper_length_scale and self.cfg.piper_length_scale != 1.0:
            cmd += ["--length_scale", str(self.cfg.piper_length_scale)]
        proc = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError((proc.stderr or "piper failed")[:300])
        return str(out)

    def _pyttsx3(self, text: str) -> Optional[str]:
        import pyttsx3  # type: ignore

        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
        return None

    # -- playback ---------------------------------------------------------
    def _play(self, path: str) -> bool:
        for player in ("ffplay", "paplay", "aplay", "afplay"):
            exe = shutil.which(player)
            if exe:
                args = [exe, path]
                if player == "ffplay":
                    args = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                try:
                    subprocess.run(args, capture_output=True, timeout=180, check=False)
                    return True
                except Exception:  # noqa: BLE001
                    continue
        try:
            import sounddevice as sd  # type: ignore
            import soundfile as sf  # type: ignore

            data, rate = sf.read(path, dtype="float32")
            sd.play(data, rate)
            sd.wait()
            return True
        except Exception:  # noqa: BLE001
            pass
        if os.name == "nt":  # pragma: no cover - Windows only
            try:
                subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Command",
                        f"(New-Object Media.SoundPlayer '{path}').PlaySync()",
                    ],
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                return True
            except Exception:  # noqa: BLE001
                return False
        return False


def _importable(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False
