"""Offline text-to-speech with Piper on the CPU (ADR-017).

Voices are downloaded on first use from the official Piper voices repository into
data/voices. Voice names follow ``<lang>_<REGION>-<speaker>-<quality>``.
"""

import asyncio
import logging
import shutil
import threading
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.audio.clip import AudioClip
from jarvis.i18n import Language
from jarvis.tts.base import TtsError

log = logging.getLogger(__name__)

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DOWNLOAD_TIMEOUT_S = 60

Downloader = Callable[[str, Path], None]


def voice_url(name: str, suffix: str) -> str:
    """URL of a voice file, e.g. en_GB-alan-medium + .onnx -> .../en/en_GB/alan/medium/..."""
    try:
        locale_code, speaker, quality = name.split("-")
    except ValueError:
        raise ValueError(f"Invalid Piper voice name: {name!r}") from None
    family = locale_code.split("_")[0]
    return f"{VOICES_URL}/{family}/{locale_code}/{speaker}/{quality}/{name}{suffix}"


def download(url: str, target: Path) -> None:
    with (
        urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response,
        target.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)


def ensure_voice(name: str, voices_dir: Path, downloader: Downloader = download) -> Path:
    """Return the voice's .onnx path, downloading the model and its config if missing."""
    voices_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx.json", ".onnx"):
        target = voices_dir / f"{name}{suffix}"
        if target.exists():
            continue
        log.info("Downloading offline voice file %s", target.name)
        partial = target.with_name(target.name + ".part")
        downloader(voice_url(name, suffix), partial)
        partial.replace(target)  # only complete files get the final name
    return voices_dir / f"{name}.onnx"


class PiperTts:
    engine = "piper"

    def __init__(
        self,
        voices: Mapping[Language, str],
        voices_dir: Path,
        downloader: Downloader = download,
    ) -> None:
        self._voices = voices
        self._voices_dir = voices_dir
        self._downloader = downloader
        self._loaded: dict[Language, Any] = {}
        self._lock = threading.Lock()

    def voice(self, language: Language) -> str:
        return self._voices[language]

    def prepare(self) -> None:
        """Download and load every voice now (blocking), so the fallback is ready offline."""
        for language in self._voices:
            self._load(language)

    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        # Piper takes ~0.1 s, so its output is never cached.
        return await asyncio.to_thread(self._synthesize, text, language)

    def _synthesize(self, text: str, language: Language) -> AudioClip:
        voice = self._load(language)
        chunks = list(voice.synthesize(text))
        if not chunks:
            raise TtsError(f"Piper produced no audio for {text!r}")
        samples = np.concatenate([chunk.audio_float_array for chunk in chunks])
        return AudioClip(samples.astype(np.float32), int(chunks[0].sample_rate))

    def _load(self, language: Language) -> Any:
        with self._lock:
            if language not in self._loaded:
                from piper import PiperVoice

                model = ensure_voice(self._voices[language], self._voices_dir, self._downloader)
                self._loaded[language] = PiperVoice.load(model)
            return self._loaded[language]
