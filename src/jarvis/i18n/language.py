"""The two languages JARVIS speaks."""

from enum import StrEnum


class Language(StrEnum):
    """Values are Whisper's language codes; ``locale`` names the i18n file."""

    PT = "pt"
    EN = "en"

    @property
    def locale(self) -> str:
        return "pt-BR" if self is Language.PT else "en"
