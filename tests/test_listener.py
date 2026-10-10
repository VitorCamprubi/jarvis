import asyncio
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile

from jarvis.audio.clip import Samples
from jarvis.audio.listener import MicrophoneError, MicrophoneListener
from jarvis.audio.vad import FRAME_SAMPLES, SAMPLE_RATE, SileroVad
from jarvis.config import VadConfig

FIXTURE = Path(__file__).parent / "fixtures" / "speech_pt.wav"
CONFIG = VadConfig(
    threshold=0.5,
    min_speech_level_dbfs=-45.0,
    silence_ms=320,
    no_speech_timeout_s=1.0,
    max_utterance_s=5.0,
    pre_roll_ms=128,
)


class FakeInputStream:
    """Stands in for sd.InputStream: a thread delivers the given frames to the callback."""

    def __init__(self, frames: list[Samples], **settings: Any) -> None:
        self.settings = settings
        self._frames = frames
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._deliver)

    def __enter__(self) -> FakeInputStream:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join()

    def _deliver(self) -> None:
        for frame in self._frames:
            if self._stop.is_set():
                return
            self.settings["callback"](frame.reshape(-1, 1), len(frame), None, None)


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


def listener_for(audio_frames: list[Samples], vad: Any) -> tuple[MicrophoneListener, list[Any]]:
    streams: list[Any] = []

    def factory(**settings: Any) -> FakeInputStream:
        stream = FakeInputStream(audio_frames, **settings)
        streams.append(stream)
        return stream

    return MicrophoneListener(CONFIG, vad, device=3, stream_factory=factory), streams


def test_records_speech_with_pre_roll_and_trims_trailing_silence() -> None:
    probabilities = [0.0] * 10 + [0.9] * 20 + [0.0] * 30
    listener, streams = listener_for(frames(60), ScriptedVad(probabilities))

    utterance = asyncio.run(listener.listen())

    assert utterance is not None
    # 4 pre-roll frames + 20 speech frames + 200 ms (6 frames) of trailing silence
    assert len(utterance.audio) == (4 + 20 + 6) * FRAME_SAMPLES
    assert streams[0].settings["samplerate"] == SAMPLE_RATE
    assert streams[0].settings["device"] == 3


def test_returns_none_when_nothing_is_said() -> None:
    listener, _ = listener_for(frames(100), ScriptedVad([0.0]))

    assert asyncio.run(listener.listen()) is None


def test_real_speech_is_cut_after_the_silence_window() -> None:
    speech, _ = soundfile.read(FIXTURE, dtype="float32")
    silence = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    audio = np.concatenate([silence[:4800], speech, silence])
    audio_frames = list(
        audio[: len(audio) // FRAME_SAMPLES * FRAME_SAMPLES].reshape(-1, FRAME_SAMPLES)
    )
    listener, _ = listener_for(audio_frames, SileroVad())

    utterance = asyncio.run(listener.listen())

    assert utterance is not None
    assert 1.2 < utterance.duration_s < 2.5  # the 1.5 s phrase, give or take VAD edges


def test_microphone_that_cannot_open_raises_a_clear_error() -> None:
    def broken(**settings: Any) -> Any:
        raise OSError("device unavailable")

    listener = MicrophoneListener(CONFIG, ScriptedVad([0.0]), stream_factory=broken)

    with pytest.raises(MicrophoneError, match="device unavailable"):
        asyncio.run(listener.listen())
