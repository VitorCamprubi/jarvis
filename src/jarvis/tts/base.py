"""Text-to-speech interfaces."""

from typing import Protocol

from jarvis.audio.clip import AudioClip
from jarvis.i18n import Language


class TtsError(RuntimeError):
    """A text-to-speech engine could not produce audio."""


class TextToSpeech(Protocol):
    async def synthesize(
        self, text: str, language: Language, *, cacheable: bool = False
    ) -> AudioClip:
        """Speak ``text``. Only fixed phrases should be ``cacheable``: replies that contain
        what the user said, or generated text, are never written to disk."""
        ...


class NamedVoiceTts(TextToSpeech, Protocol):
    """An engine that can name the voice it uses, so its output can be cached."""

    @property
    def engine(self) -> str: ...

    def voice(self, language: Language) -> str: ...
