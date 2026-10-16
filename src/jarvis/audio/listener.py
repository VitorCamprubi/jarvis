"""Capturing one request: from the activation until the end of speech."""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from jarvis.audio.clip import Samples
from jarvis.audio.microphone import Microphone, MicrophoneError
from jarvis.audio.vad import (
    FRAME_MS,
    MIN_SPEECH_FRAMES,
    SAMPLE_RATE,
    Endpoint,
    EndpointDetector,
    level_dbfs,
)
from jarvis.config import VadConfig

log = logging.getLogger(__name__)

# Silence kept after the last word: enough for Whisper, without the whole silence window.
TRAILING_SILENCE_MS = 200
# No audio at all for this long means the microphone stopped delivering frames.
NO_AUDIO_TIMEOUT_S = 2.0

__all__ = ["Listener", "MicrophoneError", "MicrophoneListener", "Utterance"]


@dataclass(frozen=True, eq=False)
class Utterance:
    audio: Samples  # 16 kHz mono
    ended_at: float  # time.perf_counter() when the end of speech was detected

    @property
    def duration_s(self) -> float:
        return len(self.audio) / SAMPLE_RATE


class Listener(Protocol):
    async def listen(
        self, no_speech_timeout_s: float | None = None, backlog_s: float = 0.0
    ) -> Utterance | None:
        """Record until the end of speech; None if nothing was said in time (by default
        within the configured vad.no_speech_timeout_s). ``backlog_s`` seconds of audio from
        before the call are included: after the wake word, the request may already be under
        way."""
        ...


class Vad(Protocol):
    def reset(self) -> None: ...

    def __call__(self, frame: Samples) -> float: ...


class MicrophoneListener:
    def __init__(self, config: VadConfig, vad: Vad, microphone: Microphone) -> None:
        self._config = config
        self._vad = vad
        self._microphone = microphone

    async def listen(
        self, no_speech_timeout_s: float | None = None, backlog_s: float = 0.0
    ) -> Utterance | None:
        config = self._config
        if no_speech_timeout_s is not None:
            config = config.model_copy(update={"no_speech_timeout_s": no_speech_timeout_s})
        self._vad.reset()
        detector = EndpointDetector(config)
        # Frames kept from before speech is confirmed, so the first syllable is not lost: the
        # pre-roll plus the speech frames that preceded the confirming one.
        recent: deque[Samples] = deque(
            maxlen=round(config.pre_roll_ms / FRAME_MS) + MIN_SPEECH_FRAMES - 1
        )
        captured: list[Samples] = []
        frames = self._microphone.subscribe(backlog_s)
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(frames.get(), NO_AUDIO_TIMEOUT_S)
                except TimeoutError as exc:
                    raise MicrophoneError("The microphone stopped sending audio") from exc
                endpoint = detector.update(self._vad(frame), level_dbfs(frame))
                if detector.speech_started:
                    if not captured:
                        captured.extend(recent)
                    captured.append(frame)
                else:
                    recent.append(frame)
                if endpoint is not Endpoint.CONTINUE:
                    ended_at = time.perf_counter()
                    break
        finally:
            self._microphone.unsubscribe(frames)

        log.debug("Listening ended: %s", endpoint)
        if endpoint is Endpoint.NO_SPEECH or not captured:
            return None
        extra_silence = detector.silent_run - round(TRAILING_SILENCE_MS / FRAME_MS)
        if extra_silence > 0:
            captured = captured[:-extra_silence]
        return Utterance(np.concatenate(captured), ended_at)
