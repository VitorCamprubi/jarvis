"""Microphone calibration for `uv run jarvis --mic-test`: background level vs. speech level.

Nothing is recorded to disk: only per-frame loudness and speech probability are kept.
"""

import queue
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

import numpy as np
import sounddevice as sd

from jarvis.audio.vad import FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE, SileroVad, level_dbfs


class FrameStats(NamedTuple):
    level_dbfs: float
    speech_probability: float


@dataclass(frozen=True)
class Calibration:
    background_dbfs: float  # 90th percentile of loudness while the user was quiet
    speech_dbfs: float | None  # median loudness of speech frames while the user spoke
    background_speech: bool  # speech-like sound while the user was quiet (TV, people)

    @property
    def suggested_min_level_dbfs(self) -> float | None:
        """Halfway between the background and the user's voice."""
        if self.speech_dbfs is None:
            return None
        return float(round((self.background_dbfs + self.speech_dbfs) / 2))


def calibrate(
    quiet: Sequence[FrameStats], speaking: Sequence[FrameStats], threshold: float
) -> Calibration:
    background = float(np.percentile([frame.level_dbfs for frame in quiet], 90))
    voiced = [frame.level_dbfs for frame in speaking if frame.speech_probability >= threshold]
    return Calibration(
        background_dbfs=background,
        speech_dbfs=statistics.median(voiced) if voiced else None,
        background_speech=any(frame.speech_probability >= threshold for frame in quiet),
    )


def measure(seconds: float, device: int | None, vad: SileroVad) -> list[FrameStats]:
    """Loudness and speech probability of each microphone frame for ``seconds``."""
    frames: queue.Queue[Any] = queue.Queue()

    def on_audio(indata: Any, frame_count: int, time_info: Any, status: Any) -> None:
        frames.put(indata[:, 0].copy())

    vad.reset()
    stats: list[FrameStats] = []
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=FRAME_SAMPLES,
        device=device,
        callback=on_audio,
    ):
        for _ in range(round(seconds * 1000 / FRAME_MS)):
            frame = frames.get(timeout=2)
            stats.append(FrameStats(level_dbfs(frame), vad(frame)))
    return stats
