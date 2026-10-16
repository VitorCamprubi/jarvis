"""Test doubles for microphone audio."""

import threading
from typing import Any

import numpy as np

from jarvis.audio.clip import Samples
from jarvis.audio.microphone import Microphone
from jarvis.audio.vad import FRAME_SAMPLES


class FakeInputStream:
    """Stands in for sd.InputStream: a thread delivers the given frames to the callback. It
    can pause before frame ``pause_after`` until ``resume()``."""

    def __init__(
        self, frames: list[Samples], pause_after: int | None = None, **settings: Any
    ) -> None:
        self.settings = settings
        self._frames = frames
        self._pause_after = pause_after
        self.paused = threading.Event()
        self._resume = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._deliver)
        self.closed = False
        self.finished = threading.Event()  # every frame was delivered

    def start(self) -> None:
        self._thread.start()

    def resume(self) -> None:
        self._resume.set()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()
        self._thread.join()

    def close(self) -> None:
        self.closed = True

    def _deliver(self) -> None:
        for index, frame in enumerate(self._frames):
            if index == self._pause_after:
                self.paused.set()
                self._resume.wait()
            if self._stop.is_set():
                return
            self.settings["callback"](frame.reshape(-1, 1), len(frame), None, None)
        self.finished.set()


class ScriptedVad:
    def __init__(self, probabilities: list[float]) -> None:
        self._probabilities = probabilities
        self._index = 0

    def reset(self) -> None:
        self._index = 0

    def __call__(self, frame: Samples) -> float:
        probability = self._probabilities[min(self._index, len(self._probabilities) - 1)]
        self._index += 1
        return probability


def frames(count: int, amplitude: float = 0.1) -> list[Samples]:
    return [np.full(FRAME_SAMPLES, amplitude, dtype=np.float32) for _ in range(count)]


def microphone_for(
    audio_frames: list[Samples], pause_after: int | None = None
) -> tuple[Microphone, list[FakeInputStream]]:
    streams: list[FakeInputStream] = []

    def factory(**settings: Any) -> FakeInputStream:
        stream = FakeInputStream(audio_frames, pause_after, **settings)
        streams.append(stream)
        return stream

    return Microphone(lambda: 3, history_s=5, stream_factory=factory), streams
