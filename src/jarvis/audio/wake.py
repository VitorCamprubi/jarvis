"""The wake word, "Ei Jarvis" / "Hey Jarvis" (ADR-040).

openWakeWord's "hey jarvis" model scores every 80 ms of microphone audio, on the core loop
(about 1.6 ms of CPU each). A confident score wakes JARVIS at once. An uncertain one, which
is what a Brazilian accent tends to get, is checked by transcribing the last seconds with
Whisper: JARVIS wakes only if they contain "Jarvis".
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import numpy as np

from jarvis.audio.clip import Samples
from jarvis.audio.microphone import Microphone
from jarvis.config import WakeConfig

log = logging.getLogger(__name__)

CHUNK_SAMPLES = 1280  # 80 ms at 16 kHz, what openWakeWord expects
FAILED_CHECK_PAUSE_S = 1.5  # after Whisper said "no", let that phrase go by
# The score peaks as "Jarvis" ends: transcribed right then, the word is cut ("Ei, já vi-se").
LISTEN_ON_S = 0.5


class WakeModel(Protocol):
    def score(self, chunk: np.ndarray) -> float:
        """Probability that the wake word just ended, for 1280 int16 samples."""
        ...

    def reset(self) -> None: ...


class OpenWakeWord:
    def __init__(self, model_name: str) -> None:
        """Blocking: downloads the model once (a few MB from GitHub), then loads it."""
        import openwakeword.utils
        from openwakeword.model import Model

        openwakeword.utils.download_models([model_name])
        self._model: Any = Model(wakeword_models=[model_name], inference_framework="onnx")

    def score(self, chunk: np.ndarray) -> float:
        return float(max(self._model.predict(chunk).values()))

    def reset(self) -> None:
        self._model.reset()


def to_int16(frame: Samples) -> np.ndarray:
    return (np.clip(frame, -1.0, 1.0) * 32767).astype(np.int16)


class WakeWatcher:
    def __init__(
        self,
        microphone: Microphone,
        model: Callable[[], WakeModel],  # built on a worker thread when the watch starts
        config: WakeConfig,
        confirm: Callable[[Samples], Awaitable[bool]],  # does this audio contain "Jarvis"?
        on_wake: Callable[[], object],
        armed: Callable[[], bool],  # only while idle or speaking (to interrupt)
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._microphone = microphone
        self._load_model = model
        self._config = config
        self._confirm = confirm
        self._on_wake = on_wake
        self._armed = armed
        self._clock = clock
        self._model: WakeModel | None = None
        self._quiet_until = 0.0
        self._checking: asyncio.Task[None] | None = None

    async def run(self) -> None:
        self._model = await asyncio.to_thread(self._load_model)
        log.info('Wake word ready: say "Ei Jarvis" or "Hey Jarvis"')
        frames = self._microphone.subscribe()
        pending = np.empty(0, dtype=np.int16)
        was_armed = False
        try:
            while True:
                frame = await frames.get()
                armed = self._armed()
                if armed and not was_armed:
                    self._model.reset()  # forget what was heard while busy
                    pending = np.empty(0, dtype=np.int16)
                was_armed = armed
                if not armed:
                    continue
                pending = np.concatenate([pending, to_int16(frame)])
                while len(pending) >= CHUNK_SAMPLES:
                    chunk, pending = pending[:CHUNK_SAMPLES], pending[CHUNK_SAMPLES:]
                    self.consider(self._model.score(chunk))
        finally:
            self._microphone.unsubscribe(frames)

    def consider(self, score: float) -> None:
        if self._clock() < self._quiet_until:
            return
        if score >= self._config.threshold:
            self._wake()
        elif score >= self._config.confirm_threshold and self._checking is None:
            self._checking = asyncio.create_task(self._check())

    async def _check(self) -> None:
        try:
            await asyncio.sleep(LISTEN_ON_S)
            if await self._confirm(self._microphone.recent(self._config.confirm_s)):
                if self._armed():
                    self._wake()
            else:
                self._quiet_until = self._clock() + FAILED_CHECK_PAUSE_S
        except Exception:
            log.exception("Checking the wake word failed")
        finally:
            self._checking = None

    def _wake(self) -> None:
        log.info("Wake word heard")
        if self._model is not None:
            self._model.reset()
        self._quiet_until = self._clock() + self._config.cooldown_s
        self._on_wake()
