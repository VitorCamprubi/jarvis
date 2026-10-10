"""Use the online voice when possible and the offline voice otherwise (ADR-017)."""

import logging
import time
from collections.abc import Callable

from jarvis.audio.clip import AudioClip
from jarvis.i18n import Language
from jarvis.tts.base import TextToSpeech

log = logging.getLogger(__name__)


class FallbackTts:
    def __init__(
        self,
        primary: TextToSpeech,
        fallback: TextToSpeech,
        retry_primary_after_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._retry_after_s = retry_primary_after_s
        self._clock = clock
        self._primary_blocked_until = float("-inf")

    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        if self._clock() >= self._primary_blocked_until:
            try:
                return await self._primary.synthesize(text, language, cacheable=cacheable)
            except Exception as exc:  # any failure of the online voice must not silence JARVIS
                log.warning(
                    "Online voice failed (%s: %s); using the offline voice for %.0f s",
                    type(exc).__name__,
                    exc,
                    self._retry_after_s,
                )
                # Skip the primary for a while, so every reply does not wait for a dead service.
                self._primary_blocked_until = self._clock() + self._retry_after_s
        return await self._fallback.synthesize(text, language, cacheable=cacheable)
