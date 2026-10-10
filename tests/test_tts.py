import asyncio
import io
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile
from fakes import FakeTts

from jarvis.i18n import Language
from jarvis.tts.base import TtsError
from jarvis.tts.cache import CachedTts
from jarvis.tts.edge import EdgeTts
from jarvis.tts.fallback import FallbackTts
from jarvis.tts.piper import ensure_voice, voice_url

VOICES = {Language.EN: "en-GB-RyanNeural", Language.PT: "pt-BR-AntonioNeural"}


# --- FallbackTts -----------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_primary_voice_is_used_when_it_works() -> None:
    primary, fallback = FakeTts(), FakeTts()
    tts = FallbackTts(primary, fallback, retry_primary_after_s=60)

    asyncio.run(tts.synthesize("Hello", Language.EN, cacheable=True))

    assert primary.spoken == [("Hello", Language.EN, True)]
    assert fallback.spoken == []


def test_failure_switches_to_the_fallback_for_a_while() -> None:
    primary, fallback, clock = FakeTts(error=TimeoutError()), FakeTts(), Clock()
    tts = FallbackTts(primary, fallback, retry_primary_after_s=60, clock=clock)

    async def scenario() -> None:
        await tts.synthesize("one", Language.EN)  # primary fails, fallback speaks
        clock.now = 30
        await tts.synthesize("two", Language.EN)  # primary still skipped
        clock.now = 61
        await tts.synthesize("three", Language.EN)  # primary retried

    asyncio.run(scenario())
    assert [text for text, _, _ in primary.spoken] == ["one", "three"]
    assert [text for text, _, _ in fallback.spoken] == ["one", "two", "three"]


# --- CachedTts -------------------------------------------------------------------------


def test_only_cacheable_phrases_are_written_to_disk(tmp_path: Path) -> None:
    inner = FakeTts()
    tts = CachedTts(inner, tmp_path, max_bytes=10_000_000)

    asyncio.run(tts.synthesize("You said: my secret", Language.EN, cacheable=False))

    assert list(tmp_path.iterdir()) == []


def test_cached_phrase_is_synthesised_once(tmp_path: Path) -> None:
    inner = FakeTts()
    tts = CachedTts(inner, tmp_path, max_bytes=10_000_000)

    async def scenario() -> None:
        first = await tts.synthesize("All systems online.", Language.EN, cacheable=True)
        second = await tts.synthesize("All systems online.", Language.EN, cacheable=True)
        assert np.allclose(first.samples, second.samples)
        assert first.sample_rate == second.sample_rate

    asyncio.run(scenario())
    assert len(inner.spoken) == 1


def test_changing_the_voice_does_not_replay_the_old_one(tmp_path: Path) -> None:
    async def scenario() -> None:
        await CachedTts(FakeTts(voice_name="a"), tmp_path, 10_000_000).synthesize(
            "Hi", Language.EN, cacheable=True
        )
        other = FakeTts(voice_name="b")
        await CachedTts(other, tmp_path, 10_000_000).synthesize("Hi", Language.EN, cacheable=True)
        assert len(other.spoken) == 1

    asyncio.run(scenario())


def test_cache_drops_the_oldest_phrases_over_its_size_limit(tmp_path: Path) -> None:
    tts = CachedTts(FakeTts(), tmp_path, max_bytes=1)

    async def scenario() -> None:
        await tts.synthesize("first", Language.EN, cacheable=True)
        await tts.synthesize("second", Language.EN, cacheable=True)

    asyncio.run(scenario())
    assert len(list(tmp_path.iterdir())) <= 1


# --- EdgeTts ---------------------------------------------------------------------------


def mp3_bytes(seconds: float = 0.5) -> bytes:
    buffer = io.BytesIO()
    tone = 0.2 * np.sin(np.linspace(0, 2 * np.pi * 440 * seconds, int(24_000 * seconds)))
    soundfile.write(buffer, tone.astype(np.float32), 24_000, format="MP3")
    return buffer.getvalue()


class FakeCommunicate:
    def __init__(self, chunks: list[dict[str, Any]], delay_s: float = 0.0) -> None:
        self._chunks = chunks
        self._delay_s = delay_s
        self.requests: list[tuple[str, str]] = []

    def __call__(self, text: str, voice: str) -> FakeCommunicate:
        self.requests.append((text, voice))
        return self

    async def stream(self) -> AsyncGenerator[dict[str, Any]]:
        await asyncio.sleep(self._delay_s)
        for chunk in self._chunks:
            yield chunk


def test_edge_decodes_the_streamed_mp3_with_the_language_voice() -> None:
    data = mp3_bytes()
    middle = len(data) // 2
    communicate = FakeCommunicate(
        [
            {"type": "SentenceBoundary", "text": "Olá"},
            {"type": "audio", "data": data[:middle]},
            {"type": "audio", "data": data[middle:]},
        ]
    )
    tts = EdgeTts(VOICES, first_audio_timeout_s=1, communicate=communicate)

    clip = asyncio.run(tts.synthesize("Olá", Language.PT))

    assert communicate.requests == [("Olá", "pt-BR-AntonioNeural")]
    assert clip.sample_rate == 24_000
    assert 0.4 < clip.duration_s < 0.7


def test_edge_gives_up_when_the_first_audio_is_late() -> None:
    communicate = FakeCommunicate([{"type": "audio", "data": mp3_bytes()}], delay_s=1.0)
    tts = EdgeTts(VOICES, first_audio_timeout_s=0.05, communicate=communicate)

    with pytest.raises(TimeoutError):
        asyncio.run(tts.synthesize("Hello", Language.EN))


def test_edge_without_audio_is_an_error() -> None:
    tts = EdgeTts(VOICES, 1, communicate=FakeCommunicate([{"type": "WordBoundary"}]))

    with pytest.raises(TtsError):
        asyncio.run(tts.synthesize("Hello", Language.EN))


# --- Piper voices ----------------------------------------------------------------------


def test_voice_url_follows_the_repository_layout() -> None:
    assert voice_url("en_GB-northern_english_male-medium", ".onnx") == (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium.onnx"
    )


def test_invalid_voice_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="voice name"):
        voice_url("alan", ".onnx")


def test_voice_files_are_downloaded_once(tmp_path: Path) -> None:
    downloads: list[str] = []

    def downloader(url: str, target: Path) -> None:
        downloads.append(url.rsplit("/", 1)[-1])
        target.write_bytes(b"model")

    model = ensure_voice("pt_BR-faber-medium", tmp_path, downloader)
    ensure_voice("pt_BR-faber-medium", tmp_path, downloader)

    assert model == tmp_path / "pt_BR-faber-medium.onnx"
    assert downloads == ["pt_BR-faber-medium.onnx.json", "pt_BR-faber-medium.onnx"]
    assert not list(tmp_path.glob("*.part"))
