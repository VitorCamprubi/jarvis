from typing import Any

import numpy as np
import pytest

from jarvis.audio.calibration import FrameStats, calibrate
from jarvis.audio.devices import DeviceNotFoundError, find_device
from jarvis.audio.tones import SAMPLE_RATE, FeedbackSounds, tone_sequence

HOST_APIS = [{"name": "MME"}, {"name": "Windows WASAPI"}]
DEVICES: list[dict[str, Any]] = [
    {
        "name": "Microfone (fifine Headset)",
        "hostapi": 1,
        "max_input_channels": 2,
        "max_output_channels": 0,
    },
    {
        "name": "Microfone (fifine Headset)",
        "hostapi": 0,
        "max_input_channels": 1,
        "max_output_channels": 0,
    },
    {
        "name": "Alto-falantes (fifine Headset)",
        "hostapi": 0,
        "max_input_channels": 0,
        "max_output_channels": 2,
    },
    {
        "name": "Microfone (Iriun Webcam)",
        "hostapi": 0,
        "max_input_channels": 2,
        "max_output_channels": 0,
    },
]


def test_empty_device_name_means_windows_default() -> None:
    assert find_device("", "input", DEVICES, HOST_APIS) is None


def test_device_match_is_case_insensitive_and_prefers_mme() -> None:
    assert find_device("FIFINE", "input", DEVICES, HOST_APIS) == 1


def test_device_match_respects_the_kind() -> None:
    assert find_device("fifine", "output", DEVICES, HOST_APIS) == 2


def test_unknown_device_lists_the_available_ones() -> None:
    with pytest.raises(DeviceNotFoundError, match="Iriun"):
        find_device("usb mic", "input", DEVICES, HOST_APIS)


def test_tones_are_short_quiet_and_click_free() -> None:
    tone = tone_sequence([660.0, 880.0], volume=0.25)

    assert tone.sample_rate == SAMPLE_RATE
    assert 0.1 < tone.duration_s < 0.2
    assert np.max(np.abs(tone.samples)) <= 0.25
    assert abs(tone.samples[0]) < 0.01 and abs(tone.samples[-1]) < 0.01


def test_start_and_stop_tones_differ() -> None:
    sounds = FeedbackSounds.create(0.2)

    assert not np.array_equal(sounds.start.samples, sounds.stop.samples)


def test_calibration_suggests_a_level_between_background_and_voice() -> None:
    quiet = [FrameStats(-60.0, 0.1)] * 50
    speaking = [FrameStats(-60.0, 0.1)] * 10 + [FrameStats(-30.0, 0.9)] * 40

    result = calibrate(quiet, speaking, threshold=0.5)

    assert result.background_dbfs == pytest.approx(-60.0)
    assert result.speech_dbfs == pytest.approx(-30.0)
    assert result.suggested_min_level_dbfs == -45.0
    assert not result.background_speech


def test_calibration_flags_background_speech_and_missing_voice() -> None:
    quiet = [FrameStats(-55.0, 0.8)] * 20
    speaking = [FrameStats(-55.0, 0.2)] * 20

    result = calibrate(quiet, speaking, threshold=0.5)

    assert result.background_speech
    assert result.speech_dbfs is None
    assert result.suggested_min_level_dbfs is None
