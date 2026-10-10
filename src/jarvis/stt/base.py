"""Speech-to-text interface."""

from dataclasses import dataclass
from typing import Protocol

from jarvis.audio.clip import Samples
from jarvis.i18n import Language


@dataclass(frozen=True)
class Transcript:
    text: str
    language: Language
    language_confidence: float  # pt-vs-en confidence, 0.5 to 1.0


class SpeechToText(Protocol):
    async def transcribe(self, audio: Samples, previous_language: Language) -> Transcript:
        """Transcribe 16 kHz mono audio; ``previous_language`` breaks uncertain detections."""
        ...
