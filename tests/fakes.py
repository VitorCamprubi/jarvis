"""Test doubles shared by the pipeline and TTS tests (hand-written, no mocking library)."""

import asyncio

import numpy as np

from jarvis.audio.clip import AudioClip, Samples
from jarvis.audio.listener import Utterance
from jarvis.i18n import Language
from jarvis.stt.base import Transcript


def clip(seconds: float = 0.1, sample_rate: int = 16_000) -> AudioClip:
    return AudioClip(np.zeros(int(seconds * sample_rate), dtype=np.float32), sample_rate)


def utterance(seconds: float = 1.0) -> Utterance:
    return Utterance(np.zeros(int(seconds * 16_000), dtype=np.float32), ended_at=0.0)


class FakeListener:
    def __init__(self, *results: Utterance | None) -> None:
        self._results = list(results)
        self.calls = 0
        self.listening = asyncio.Event()

    async def listen(self) -> Utterance | None:
        self.calls += 1
        self.listening.set()
        if not self._results:
            await asyncio.Event().wait()  # listens forever, until cancelled
        return self._results.pop(0)


class FakeStt:
    def __init__(self, *results: Transcript | Exception) -> None:
        self._results = list(results)
        self.calls: list[Language] = []

    async def transcribe(self, audio: Samples, previous_language: Language) -> Transcript:
        self.calls.append(previous_language)
        await asyncio.sleep(0)  # like the real one, which waits for a worker thread
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeTts:
    engine = "fake"

    def __init__(self, error: Exception | None = None, voice_name: str = "voice") -> None:
        self.spoken: list[tuple[str, Language, bool]] = []
        self._error = error
        self._voice_name = voice_name

    def voice(self, language: Language) -> str:
        return f"{self._voice_name}-{language}"

    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        self.spoken.append((text, language, cacheable))
        if self._error is not None:
            raise self._error
        return clip(0.2, 24_000)


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[AudioClip] = []

    async def play(self, played: AudioClip) -> None:
        self.played.append(played)
        await asyncio.sleep(0)


class RejectEveryone:
    async def is_owner(self, audio: Samples) -> bool:
        return False
