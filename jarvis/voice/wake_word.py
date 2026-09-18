"""Wake-word detection ("Hey JARVIS") with openWakeWord.

openWakeWord ships a pre-trained ``hey_jarvis`` model and runs on ONNX Runtime,
which makes it a far better fit than keeping Whisper running continuously: the
microphone stream is only decoded after the wake word fires.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from ..config import VoiceConfig
from ..events import EventBus

log = logging.getLogger("jarvis.voice.wake")


class WakeWordListener:
    """Thin async wrapper around openWakeWord's streaming prediction loop."""

    def __init__(self, cfg: VoiceConfig, bus: Optional[EventBus] = None) -> None:
        self.cfg = cfg
        self.bus = bus
        self._model = None
        self._stop = threading.Event()
        self._last_score = 0.0
        self._detections = 0

    # -- availability -----------------------------------------------------
    def probe(self) -> Dict[str, Any]:
        missing = []
        for module in ("openwakeword", "sounddevice", "numpy"):
            try:
                __import__(module)
            except ImportError:
                missing.append(module)
        engine = (self.cfg.wake_engine or "none").lower()
        return {
            "available": not missing and engine != "none",
            "engine": self.cfg.wake_engine,
            "word": self.cfg.wake_word,
            "threshold": self.cfg.wake_threshold,
            "missing": missing,
            "hint": "pip install openwakeword sounddevice numpy" if missing else "",
        }

    @property
    def available(self) -> bool:
        return self.probe()["available"]

    # -- model ------------------------------------------------------------
    def _ensure_model(self):
        if self._model is not None:
            return self._model
        from openwakeword.model import Model  # type: ignore

        kwargs: Dict[str, Any] = {"inference_framework": "onnx"}
        if self.cfg.wake_model_path:
            kwargs["wakeword_models"] = [self.cfg.wake_model_path]
        else:
            kwargs["wakeword_models"] = ["hey_jarvis"]
        self._model = Model(**kwargs)
        return self._model

    def _model_key(self) -> str:
        if self._model is None:
            return ""
        return next(iter(getattr(self._model, "models", {}) or {"hey_jarvis": None}), "hey_jarvis")

    # -- detection --------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    async def wait_for_wake(self, timeout: Optional[float] = None, poll: float = 0.25) -> bool:
        """Block until the wake word is heard (or ``timeout`` elapses)."""
        import asyncio

        if not self.available:
            raise RuntimeError("openWakeWord is not installed — run: pip install openwakeword sounddevice numpy")
        self._stop.clear()
        if self.bus:
            self.bus.publish("status", {"state": "listening", "wake_word": self.cfg.wake_word})
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect, timeout, poll)

    def _detect(self, timeout: Optional[float], poll: float) -> bool:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore

        model = self._ensure_model()
        key_hint = self._model_key()
        detected = threading.Event()

        def callback(indata, frames, time_info, status):  # pragma: no cover - hardware
            audio = np.frombuffer(indata, dtype=np.int16)
            prediction = model.predict(audio)
            score = 0.0
            for name, value in prediction.items():
                score = max(score, float(value))
                if float(value) >= self.cfg.wake_threshold:
                    if not detected.is_set():
                        log.info("wake word detected (%s score=%.3f)", name, float(value))
                    detected.set()
            self._last_score = score
            if self.bus and score > 0.05:
                self.bus.publish("wake_score", {"score": round(score, 3), "threshold": self.cfg.wake_threshold})

        deadline = time.time() + timeout if timeout else None
        blocksize = 1280  # 80 ms @ 16 kHz — openWakeWord's expected frame size
        try:
            with sd.InputStream(
                samplerate=self.cfg.sample_rate,
                blocksize=blocksize,
                channels=1,
                dtype="int16",
                device=self.cfg.device or None,
                callback=callback,
            ):
                while not detected.is_set() and not self._stop.is_set():
                    if deadline and time.time() > deadline:
                        return False
                    time.sleep(poll)
        except Exception as exc:  # noqa: BLE001
            log.warning("wake-word stream error: %s", exc)
            raise RuntimeError(f"microphone unavailable: {exc}") from exc

        if detected.is_set():
            self._detections += 1
            if self.bus:
                self.bus.publish("wake_detected", {"word": self.cfg.wake_word, "model": key_hint})
        return detected.is_set()

    def stats(self) -> Dict[str, Any]:
        return {"detections": self._detections, "last_score": round(self._last_score, 3)}
