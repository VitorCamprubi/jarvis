"""One microphone stream shared by everyone who listens (ADR-040).

The wake word watches the microphone all the time and a turn's listener reads from it at the
same time; both subscribe here instead of opening their own stream. The last seconds are
kept, so a request said in one breath after "Ei Jarvis" is not cut. The stream is open while
anyone subscribes, and reopened if the microphone stops sending audio (unplugged headset).
Lives on the core event loop.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np
import sounddevice as sd

from jarvis.audio.clip import Samples
from jarvis.audio.vad import FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE

log = logging.getLogger(__name__)

STALL_S = 2.0  # no audio for this long: the stream is dead
CHECK_EVERY_S = 1.0
RETRY_S = 3.0  # between attempts while the microphone is missing

# sd.InputStream, or a test double with the same constructor, start(), stop() and close().
StreamFactory = Callable[..., Any]


class MicrophoneError(RuntimeError):
    """The microphone could not be opened or stopped sending audio."""


def refresh_devices() -> None:
    """PortAudio lists devices once; a headset plugged in again gets a new entry."""
    sd._terminate()
    sd._initialize()


class Microphone:
    def __init__(
        self,
        device: Callable[[], int | None],  # looked up again at every (re)open
        history_s: float,
        stream_factory: StreamFactory = sd.InputStream,
        rescan: Callable[[], None] = refresh_devices,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._device = device
        self._stream_factory = stream_factory
        self._rescan = rescan
        self._clock = clock
        self._history: deque[Samples] = deque(maxlen=round(history_s * 1000 / FRAME_MS))
        self._subscribers: set[asyncio.Queue[Samples]] = set()
        self._stream: Any = None
        self._last_frame = 0.0

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    def subscribe(self, backlog_s: float = 0.0) -> asyncio.Queue[Samples]:
        """A queue of the frames from now on, starting with the last ``backlog_s`` seconds."""
        if self._stream is None:
            self._open()
        frames: asyncio.Queue[Samples] = asyncio.Queue()
        if backlog_s > 0:
            for frame in list(self._history)[-round(backlog_s * 1000 / FRAME_MS) :]:
                frames.put_nowait(frame)
        self._subscribers.add(frames)
        return frames

    def recent(self, seconds: float) -> Samples:
        """The last ``seconds`` of audio, as one clip."""
        frames = list(self._history)[-round(seconds * 1000 / FRAME_MS) :]
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)

    def unsubscribe(self, frames: asyncio.Queue[Samples]) -> None:
        self._subscribers.discard(frames)
        if not self._subscribers:
            self.close()

    def close(self) -> None:
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.stop()
                stream.close()
            except Exception as exc:  # an unplugged device may refuse even to close
                log.debug("Closing the microphone: %s", exc)
            self._history.clear()

    async def keep_alive(self) -> None:
        """Reopen the stream whenever it goes silent while someone is listening."""
        while True:
            await asyncio.sleep(CHECK_EVERY_S)
            if not self._subscribers or self._clock() - self._last_frame < STALL_S:
                continue
            log.warning("The microphone stopped sending audio; reopening it")
            self.close()
            try:
                self._rescan()
                self._open()
            except MicrophoneError as exc:
                log.warning("%s; trying again in %.0f s", exc, RETRY_S)
                await asyncio.sleep(RETRY_S)

    def _open(self) -> None:
        loop = asyncio.get_running_loop()

        def on_audio(indata: Any, frame_count: int, time_info: Any, status: Any) -> None:
            # Runs on PortAudio's thread: hand a copy of the frame over to the event loop.
            if status:
                log.debug("Microphone status: %s", status)
            loop.call_soon_threadsafe(self._push, indata[:, 0].copy())

        try:
            stream = self._stream_factory(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=FRAME_SAMPLES,
                device=self._device(),
                callback=on_audio,
            )
            stream.start()
        except Exception as exc:
            raise MicrophoneError(f"Cannot open the microphone: {exc}") from exc
        self._stream = stream
        self._last_frame = self._clock()  # give it time to deliver the first frame

    def _push(self, frame: Samples) -> None:
        if self._stream is None:
            return  # a frame still in flight after close()
        self._last_frame = self._clock()
        self._history.append(frame)
        for frames in self._subscribers:
            frames.put_nowait(frame)
