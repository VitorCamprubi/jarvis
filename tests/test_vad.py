from pathlib import Path

import numpy as np
import pytest
import soundfile

from jarvis.audio.vad import FRAME_SAMPLES, Endpoint, EndpointDetector, SileroVad, level_dbfs
from jarvis.config import VadConfig

FIXTURE = Path(__file__).parent / "fixtures" / "speech_pt.wav"
LOUD = -20.0  # dBFS, a voice close to the microphone
FAINT = -60.0  # dBFS, a voice across the room

CONFIG = VadConfig(
    threshold=0.5,
    min_speech_level_dbfs=-45.0,
    silence_ms=160,  # 5 frames
    no_speech_timeout_s=0.32,  # 10 frames
    max_utterance_s=1.6,  # 50 frames
    pre_roll_ms=64,
)


def feed(detector: EndpointDetector, probabilities: list[float], level: float = LOUD) -> Endpoint:
    result = Endpoint.CONTINUE
    for probability in probabilities:
        result = detector.update(probability, level)
        if result is not Endpoint.CONTINUE:
            break
    return result


def test_speech_followed_by_silence_ends_the_utterance() -> None:
    detector = EndpointDetector(CONFIG)

    assert feed(detector, [0.9] * 5 + [0.1] * 4) is Endpoint.CONTINUE
    assert detector.update(0.1, LOUD) is Endpoint.SPEECH_ENDED


def test_nothing_said_times_out() -> None:
    detector = EndpointDetector(CONFIG)

    assert feed(detector, [0.1] * 9) is Endpoint.CONTINUE
    assert detector.update(0.1, LOUD) is Endpoint.NO_SPEECH


def test_faint_voices_in_the_background_are_ignored() -> None:
    detector = EndpointDetector(CONFIG)

    assert feed(detector, [0.95] * 10, level=FAINT) is Endpoint.NO_SPEECH


def test_a_click_does_not_start_an_utterance() -> None:
    detector = EndpointDetector(CONFIG)

    assert feed(detector, [0.9, 0.9] + [0.1] * 8) is Endpoint.NO_SPEECH


def test_soft_syllables_do_not_end_the_utterance() -> None:
    detector = EndpointDetector(CONFIG)
    # 0.4 is below the threshold but above threshold - hysteresis: still part of speech.
    pattern = [0.9] * 3 + [0.1] * 4 + [0.4] + [0.1] * 4

    assert feed(detector, pattern) is Endpoint.CONTINUE


def test_endless_talking_stops_at_the_limit() -> None:
    detector = EndpointDetector(CONFIG)

    assert feed(detector, [0.9] * 60) is Endpoint.MAX_LENGTH
    assert detector.update(0.9, LOUD) is not Endpoint.CONTINUE


def test_level_dbfs() -> None:
    assert level_dbfs(np.full(FRAME_SAMPLES, 0.1, dtype=np.float32)) == pytest.approx(-20.0)
    assert level_dbfs(np.zeros(FRAME_SAMPLES, dtype=np.float32)) == pytest.approx(-200.0)


def test_silero_scores_silence_low_and_speech_high() -> None:
    vad = SileroVad()
    silence = np.zeros(FRAME_SAMPLES * 10, dtype=np.float32).reshape(-1, FRAME_SAMPLES)
    speech, _ = soundfile.read(FIXTURE, dtype="float32")
    usable = len(speech) // FRAME_SAMPLES * FRAME_SAMPLES

    assert max(vad(frame) for frame in silence) < 0.2
    vad.reset()
    assert max(vad(frame) for frame in speech[:usable].reshape(-1, FRAME_SAMPLES)) > 0.8


def test_silero_rejects_frames_of_the_wrong_size() -> None:
    with pytest.raises(ValueError, match="512"):
        SileroVad()(np.zeros(100, dtype=np.float32))
