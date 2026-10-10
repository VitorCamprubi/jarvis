"""Voice activity detection: when does speech start and end (ADR-013).

``SileroVad`` scores one 32 ms frame at a time with the Silero VAD v6 model that ships
with faster-whisper. ``EndpointDetector`` turns those scores into decisions; it is pure
logic, so it is tested without audio.
"""

import math
from enum import StrEnum
from pathlib import Path

import numpy as np
import onnxruntime

from jarvis.audio.clip import Samples
from jarvis.config import VadConfig

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512  # 32 ms at 16 kHz, the frame size the model expects
FRAME_MS = FRAME_SAMPLES * 1000 / SAMPLE_RATE
CONTEXT_SAMPLES = 64  # tail of the previous frame, fed along with each new frame
STATE_SHAPE = (1, 1, 128)

# A frame below threshold - HYSTERESIS counts as silence; in between it keeps the current
# state. This avoids cutting the user off on soft syllables (same scheme Silero uses).
HYSTERESIS = 0.15
# Speech is confirmed only after this many speech frames (~100 ms), so a click or a
# keystroke does not start an utterance.
MIN_SPEECH_FRAMES = 3


def level_dbfs(frame: Samples) -> float:
    """Loudness of a frame in dB relative to full scale (0 dBFS is the loudest possible)."""
    rms = float(np.sqrt(np.mean(np.square(frame))))
    return 20 * math.log10(max(rms, 1e-10))


def default_model_path() -> Path:
    from faster_whisper.utils import get_assets_path

    return Path(get_assets_path()) / "silero_vad_v6.onnx"


class SileroVad:
    """Streaming speech probability for consecutive 512-sample frames at 16 kHz."""

    def __init__(self, model_path: Path | None = None) -> None:
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(model_path or default_model_path()),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.reset()

    def reset(self) -> None:
        """Forget previous audio; call before each new utterance."""
        self._h = np.zeros(STATE_SHAPE, dtype=np.float32)
        self._c = np.zeros(STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)

    def __call__(self, frame: Samples) -> float:
        if frame.shape != (FRAME_SAMPLES,):
            raise ValueError(f"Expected {FRAME_SAMPLES} samples, got {frame.shape}")
        model_input = np.concatenate([self._context, frame])[np.newaxis, :]
        probabilities, self._h, self._c = self._session.run(
            None, {"input": model_input, "h": self._h, "c": self._c}
        )
        self._context = frame[-CONTEXT_SAMPLES:]
        return float(probabilities[0])


class Endpoint(StrEnum):
    CONTINUE = "continue"
    SPEECH_ENDED = "speech_ended"  # speech followed by enough silence
    NO_SPEECH = "no_speech"  # nothing said before the timeout
    MAX_LENGTH = "max_length"  # still talking at the hard limit


class EndpointDetector:
    """Consumes one speech probability per frame and says when to stop listening.

    Silero recognises speech even when it is faint, so distant voices (a TV, a video on the
    speakers, people in the room) would keep the recording open. Frames quieter than
    ``min_speech_level_dbfs`` therefore count as silence: only speech close to the
    headset microphone matters.
    """

    def __init__(self, config: VadConfig) -> None:
        self._threshold = config.threshold
        self._min_level_dbfs = config.min_speech_level_dbfs
        self._silence_threshold = config.threshold - HYSTERESIS
        self._silence_frames = round(config.silence_ms / FRAME_MS)
        self._no_speech_frames = round(config.no_speech_timeout_s * 1000 / FRAME_MS)
        self._max_frames = round(config.max_utterance_s * 1000 / FRAME_MS)
        self._frames = 0
        self._speech_frames = 0
        self.silent_run = 0

    @property
    def speech_started(self) -> bool:
        return self._speech_frames >= MIN_SPEECH_FRAMES

    def update(self, probability: float, level_dbfs: float) -> Endpoint:
        self._frames += 1
        if level_dbfs < self._min_level_dbfs:
            probability = 0.0
        if probability >= self._threshold:
            self._speech_frames += 1
            self.silent_run = 0
        elif self.speech_started:
            if probability < self._silence_threshold:
                self.silent_run += 1
            else:
                self.silent_run = 0

        if self.speech_started and self.silent_run >= self._silence_frames:
            return Endpoint.SPEECH_ENDED
        if not self.speech_started and self._frames >= self._no_speech_frames:
            return Endpoint.NO_SPEECH
        if self._frames >= self._max_frames:
            return Endpoint.MAX_LENGTH
        return Endpoint.CONTINUE
