"""The full voice loop: wake word -> record -> transcribe -> agent -> speak."""

from __future__ import annotations

import asyncio
import logging
import os
import time
import wave
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from ..config import VoiceConfig
from ..events import EventBus
from .stt import Transcriber
from .tts import Speaker
from .wake_word import WakeWordListener

log = logging.getLogger("jarvis.voice.pipeline")


class VoicePipeline:
    """Owns the microphone, the wake-word loop and the speech I/O."""

    def __init__(
        self,
        cfg: VoiceConfig,
        bus: Optional[EventBus] = None,
        *,
        transcriber: Optional[Transcriber] = None,
        speaker: Optional[Speaker] = None,
        wake: Optional[WakeWordListener] = None,
    ) -> None:
        self.cfg = cfg
        self.bus = bus
        self.transcriber = transcriber or Transcriber(cfg)
        self.speaker = speaker or Speaker(cfg)
        self.wake = wake or WakeWordListener(cfg, bus)
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.audio_dir = Path(os.path.expanduser(cfg.models_dir)).parent / "recordings"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    # -- status -----------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Never raises — a broken voice layer must not take the API down."""
        return {
            "enabled": bool(self.cfg.enabled),
            "running": self.running,
            "wake": _safe(self.wake.probe, "wake"),
            "stt": _safe(self.transcriber.probe, "stt"),
            "tts": _safe(self.speaker.probe, "tts"),
            "capture": _capture_probe(),
        }

    # -- recording --------------------------------------------------------
    async def record_until_silence(self, path: Optional[str] = None) -> str:
        """Record from the default microphone until the user stops speaking."""
        import asyncio as _a

        target = Path(path) if path else self.audio_dir / f"utt_{int(time.time() * 1000)}.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        return await _a.get_running_loop().run_in_executor(None, self._record, str(target))

    def _record(self, path: str) -> str:
        try:
            import numpy as np  # type: ignore
            import sounddevice as sd  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("microphone capture needs: pip install sounddevice numpy") from exc

        sr = self.cfg.sample_rate
        chunk = max(1, int(sr * 0.1))  # 100 ms blocks
        frames = []
        silence_start: Optional[float] = None
        speech_start: Optional[float] = None
        deadline = time.time() + max(self.cfg.listen_timeout, 1.0)
        max_end = time.time() + max(self.cfg.phrase_max_seconds, 1.0)

        with sd.InputStream(
            samplerate=sr,
            channels=self.cfg.channels,
            dtype="int16",
            device=self.cfg.device or None,
        ) as stream:
            while time.time() < max_end:
                data, _overflowed = stream.read(chunk)
                rms = float(np.sqrt(np.mean(data.astype(np.float32) ** 2))) / 32768.0
                frames.append(data.copy())
                if rms >= self.cfg.silence_rms:
                    silence_start = None
                    if speech_start is None:
                        speech_start = time.time()
                        if self.bus:
                            self.bus.publish("status", {"state": "listening", "level": round(rms, 4)})
                else:
                    if speech_start is not None:
                        silence_start = silence_start or time.time()
                        if time.time() - silence_start >= self.cfg.silence_seconds:
                            break
                    elif time.time() > deadline:
                        break
                if self.bus:
                    self.bus.publish("audio_level", {"level": round(min(rms * 8, 1.0), 3)})

        if not frames:
            raise RuntimeError("no audio captured")
        audio = np.concatenate(frames, axis=0)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(self.cfg.channels)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
        return path

    # -- one utterance ----------------------------------------------------
    async def listen_once(self, path: Optional[str] = None) -> str:
        """Record and transcribe a single utterance. Returns the text."""
        if self.bus:
            self.bus.publish("status", {"state": "listening"})
        wav = await self.record_until_silence(path)
        if self.bus:
            self.bus.publish("status", {"state": "transcribing"})
        text = await self.transcriber.transcribe(wav, self.cfg.stt_language or None)
        if self.bus:
            self.bus.publish("transcript", {"text": text, "wav": wav})
        return text

    async def say(self, text: str) -> Dict[str, Any]:
        if self.bus:
            self.bus.publish("status", {"state": "speaking"})
        result = await self.speaker.speak(text)
        if self.bus:
            self.bus.publish("spoken", result)
        return result

    # -- continuous loop --------------------------------------------------
    async def run(
        self,
        handler: Callable[[str], Awaitable[str]],
        *,
        wake_word: bool = True,
        speak: bool = True,
    ) -> None:
        """Listen forever: wake word -> utterance -> ``handler`` -> voice reply."""
        self.running = True
        self._stop.clear()
        log.info("voice loop started (wake_word=%s)", wake_word)
        try:
            while not self._stop.is_set():
                if wake_word:
                    probe = self.wake.probe()
                    if not probe["available"]:
                        log.warning("wake word unavailable (%s) — press Enter to speak", probe.get("hint") or "missing deps")
                        await _wait_for_enter()
                    else:
                        try:
                            heard = await self.wake.wait_for_wake(timeout=1.0)
                        except RuntimeError as exc:
                            log.warning("wake word disabled: %s", exc)
                            wake_word = False
                            continue
                        if not heard:
                            continue
                        if self.bus:
                            self.bus.publish("status", {"state": "listening"})
                        if speak:
                            await self.say(_ack())
                try:
                    text = await self.listen_once()
                except RuntimeError as exc:
                    log.warning("listening failed: %s", exc)
                    continue
                if not text:
                    continue
                try:
                    reply = await handler(text)
                except Exception as exc:  # noqa: BLE001
                    log.exception("agent failed during voice turn")
                    reply = f"I hit an error: {exc}"
                if speak and reply:
                    await self.say(reply)
        finally:
            self.running = False
            if self.bus:
                self.bus.publish("status", {"state": "idle"})

    def start(self, handler: Callable[[str], Awaitable[str]], **kwargs: Any) -> asyncio.Task:
        """Run the loop in the background."""
        if self._task and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run(handler, **kwargs))
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        self.wake.stop()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.running = False


def _safe(fn, name: str) -> Dict[str, Any]:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        log.warning("%s probe failed: %s", name, exc)
        return {"available": False, "error": str(exc), "engine": name}


def _capture_probe() -> Dict[str, Any]:
    try:
        import sounddevice  # type: ignore  # noqa: F401

        return {"available": True, "devices": _device_names()}
    except ImportError:
        return {"available": False, "hint": "pip install sounddevice", "devices": []}


def _device_names() -> list:
    try:
        import sounddevice as sd  # type: ignore

        return [d.get("name", "") for d in sd.query_devices()]
    except Exception:  # noqa: BLE001
        return []


async def _wait_for_enter() -> None:  # pragma: no cover - interactive fallback
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, input, "\n[press Enter to speak] ")


def _ack() -> str:
    return "Yes, sir."
