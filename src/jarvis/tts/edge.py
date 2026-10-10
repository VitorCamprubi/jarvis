"""Online text-to-speech with Microsoft Edge's neural voices, through edge-tts (ADR-017)."""

import asyncio
import io
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any

import edge_tts
import numpy as np
import soundfile

from jarvis.audio.clip import AudioClip
from jarvis.i18n import Language
from jarvis.tts.base import TtsError

Chunks = AsyncGenerator[dict[str, Any]]
# Builds the object whose .stream() yields edge-tts chunks; replaced by a fake in tests.
CommunicateFactory = Callable[[str, str], Any]


class EdgeTts:
    engine = "edge-tts"

    def __init__(
        self,
        voices: Mapping[Language, str],
        first_audio_timeout_s: float,
        communicate: CommunicateFactory = edge_tts.Communicate,
    ) -> None:
        self._voices = voices
        self._first_audio_timeout_s = first_audio_timeout_s
        self._communicate = communicate

    def voice(self, language: Language) -> str:
        return self._voices[language]

    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        chunks: Chunks = self._communicate(text, self.voice(language)).stream()
        try:
            # Only the wait for the first audio chunk is bounded: a slow or dead connection is
            # detected quickly, while long texts can still take as long as they need.
            async with asyncio.timeout(self._first_audio_timeout_s):
                mp3 = bytearray(await _next_audio(chunks))
            async for chunk in chunks:
                if chunk["type"] == "audio":
                    mp3.extend(chunk["data"])
        finally:
            await chunks.aclose()
        samples, sample_rate = soundfile.read(io.BytesIO(bytes(mp3)), dtype="float32")
        return AudioClip(np.asarray(samples, dtype=np.float32), int(sample_rate))


async def _next_audio(chunks: Chunks) -> bytes:
    async for chunk in chunks:
        if chunk["type"] == "audio":
            return bytes(chunk["data"])
    raise TtsError("edge-tts returned no audio")
