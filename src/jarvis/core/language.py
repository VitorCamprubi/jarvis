"""Which language JARVIS replies in (ADR-033).

By default it answers in the language the user spoke. "Speak English" / "fala em português"
locks the reply language until it is unlocked; the lock is stored, so it survives restarts.
Whisper keeps detecting what is spoken either way.
"""

from jarvis.i18n import Language
from jarvis.storage import SettingsStore

LOCK_KEY = "language_lock"


class LanguagePolicy:
    def __init__(self, settings: SettingsStore | None = None) -> None:
        self._settings = settings
        self._locked: Language | None = None

    @property
    def locked(self) -> Language | None:
        return self._locked

    async def load(self) -> None:
        if self._settings is not None:
            value = await self._settings.get(LOCK_KEY)
            self._locked = Language(value) if value in {lang.value for lang in Language} else None

    def reply_language(self, spoken: Language) -> Language:
        return self._locked or spoken

    async def lock(self, language: Language | None) -> None:
        """Lock replies to ``language``; None goes back to automatic."""
        self._locked = language
        if self._settings is None:
            return
        if language is None:
            await self._settings.delete(LOCK_KEY)
        else:
            await self._settings.set(LOCK_KEY, language.value)
