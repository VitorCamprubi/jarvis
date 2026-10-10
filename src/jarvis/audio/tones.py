"""Short feedback tones, synthesised at start-up (no third-party sound files)."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from jarvis.audio.clip import AudioClip

SAMPLE_RATE = 24_000
NOTE_S = 0.07
FADE_S = 0.008


def tone_sequence(frequencies: Sequence[float], volume: float) -> AudioClip:
    """Consecutive sine notes with short fades, so they start and stop without clicks."""
    samples_per_note = int(SAMPLE_RATE * NOTE_S)
    time = np.arange(samples_per_note) / SAMPLE_RATE
    fade = int(SAMPLE_RATE * FADE_S)
    envelope = np.ones(samples_per_note)
    ramp = np.linspace(0.0, 1.0, fade)
    envelope[:fade] = ramp
    envelope[-fade:] = ramp[::-1]
    notes = [np.sin(2 * np.pi * frequency * time) * envelope for frequency in frequencies]
    return AudioClip((np.concatenate(notes) * volume).astype(np.float32), SAMPLE_RATE)


@dataclass(frozen=True)
class FeedbackSounds:
    start: AudioClip  # rising: "I'm listening"
    stop: AudioClip  # falling: "got it"

    @classmethod
    def create(cls, volume: float) -> FeedbackSounds:
        return cls(
            start=tone_sequence([660.0, 880.0], volume),
            stop=tone_sequence([880.0, 660.0], volume),
        )
