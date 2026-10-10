"""Microphone capture from the activation until the end of speech."""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import sounddevice as sd

from jarvis.audio.clip import Samples
from jarvis.audio.vad import (
    FRAME_MS,
    FRAME_SAMPLES,
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


class MicrophoneError(RuntimeError):
    """The microphone could not be opened or stopped sending audio."""


@dataclass(frozen=True, eq=False)
class Utterance:
    audio: Samples  # 16 kHz mono
    ended_at: float  # time.perf_counter() when the end of speech was detected

    @property
    def duration_s(self) -> float:
        return len(self.audio) / SAMPLE_RATE


class Listener(Protocol):
    async def listen(self) -> Utterance | None:
        """Record until the end of speech; None if nothing was said."""
        ...


class Vad(Protocol):
    def reset(self) -> None: ...

    def __call__(self, frame: Samples) -> float: ...


# sd.InputStream, or a test double with the same constructor; used as a context manager.
StreamFactory = Callable[..., Any]


class MicrophoneListener:
    def __init__(
        self,
        config: VadConfig,
        vad: Vad,
        device: int | None = None,
        stream_factory: StreamFactory = sd.InputStream,
    ) -> None:
        self._config = config
        self._vad = vad
        self._device = device
        self._stream_factory = stream_factory

    async def listen(self) -> Utterance | None:
        loop = asyncio.get_running_loop()
        frames: asyncio.Queue[Samples] = asyncio.Queue()

        def on_audio(indata: Any, frame_count: int, time_info: Any, status: Any) -> None:
            # Runs on PortAudio's thread: hand a copy of the frame over to the event loop.
            if status:
                log.debug("Microphone status: %s", status)
            loop.call_soon_threadsafe(frames.put_nowait, indata[:, 0].copy())

        self._vad.reset()
        detector = EndpointDetector(self._config)
        # Frames kept from before speech is confirmed, so the first syllable is not lost: the
        # pre-roll plus the speech frames that preceded the confirming one.
        recent: deque[Samples] = deque(
            maxlen=round(self._config.pre_roll_ms / FRAME_MS) + MIN_SPEECH_FRAMES - 1
        )
        captured: list[Samples] = []
        try:
            stream = self._stream_factory(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME_SAMPLES,
                device=self._device,
                callback=on_audio,
            )
        except Exception as exc:
            raise MicrophoneError(f"Cannot open the microphone: {exc}") from exc

        with stream:
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

        log.debug("Listening ended: %s", endpoint)
        if endpoint is Endpoint.NO_SPEECH or not captured:
            return None
        extra_silence = detector.silent_run - round(TRAILING_SILENCE_MS / FRAME_MS)
        if extra_silence > 0:
            captured = captured[:-extra_silence]
        return Utterance(np.concatenate(captured), ended_at)
