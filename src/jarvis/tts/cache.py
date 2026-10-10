"""Disk cache of synthesised phrases, so repeated replies play without waiting (ADR-017)."""

import hashlib
import logging
import os
from pathlib import Path

import numpy as np
import soundfile

from jarvis.audio.clip import AudioClip
from jarvis.i18n import Language
from jarvis.tts.base import NamedVoiceTts

log = logging.getLogger(__name__)

SUFFIX = ".flac"  # lossless and about half the size of WAV


class CachedTts:
    def __init__(self, inner: NamedVoiceTts, cache_dir: Path, max_bytes: int) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._max_bytes = max_bytes

    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        if not cacheable:
            return await self._inner.synthesize(text, language)
        path = self._path(text, language)
        if path.exists():
            os.utime(path)  # mark as recently used, for pruning
            samples, sample_rate = soundfile.read(path, dtype="float32")
            return AudioClip(np.asarray(samples, dtype=np.float32), int(sample_rate))

        clip = await self._inner.synthesize(text, language)
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            soundfile.write(path, clip.samples, clip.sample_rate)
            self._prune()
        except OSError as exc:  # a full or read-only disk only costs the cache
            log.warning("Could not cache a phrase: %s", exc)
        return clip

    def _path(self, text: str, language: Language) -> Path:
        # The voice is part of the key: changing it in the config must not replay the old one.
        key = f"{self._inner.engine}|{self._inner.voice(language)}|{text}"
        return self._cache_dir / (hashlib.sha256(key.encode("utf-8")).hexdigest()[:32] + SUFFIX)

    def _prune(self) -> None:
        """Delete the least recently used phrases while the cache is over its size limit."""
        files = sorted(self._cache_dir.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= self._max_bytes:
                break
            total -= path.stat().st_size
            path.unlink(missing_ok=True)
