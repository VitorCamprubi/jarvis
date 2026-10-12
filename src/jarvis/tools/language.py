"""Lock the reply language, or go back to answering in the language spoken (ADR-033)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from jarvis.core.language import LanguagePolicy
from jarvis.i18n import Language
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

WORDS = {
    "portugues": "pt", "portuguese": "pt", "pt": "pt",
    "ingles": "en", "english": "en", "en": "en",
    "automatico": "auto", "automatica": "auto", "automatic": "auto", "auto": "auto",
}  # fmt: skip


class SetLanguageParams(BaseModel):
    language: Literal["pt", "en", "auto"] = Field(
        description="'pt' or 'en' to always reply in that language; 'auto' to reply in the "
        "language the user speaks"
    )

    @field_validator("language", mode="before")
    @classmethod
    def _spoken(cls, value: object) -> object:
        return WORDS.get(str(value).lower(), value)


class SetLanguageTool(Tool[SetLanguageParams]):
    name = "set_language"
    description = "Lock JARVIS's reply language to Portuguese or English, or unlock it (auto)."
    params_model = SetLanguageParams
    intents = phrasings(
        pt=(
            Intent(
                r"(?:fala|fale|falar|responde|responda|conversa|converse)(?: comigo)? em "
                r"(?P<language>portugues|ingles)"
            ),
            Intent(
                r"(?:volta|volte|muda|mude|troca|troque)(?: o idioma)? (?:para|pro|pra) "
                r"(?:o )?(?P<language>portugues|ingles|automatico)"
            ),
            Intent(
                r"(?:idioma|lingua) automatic[oa]|detecta(?:r)? o idioma(?: automaticamente)?",
                {"language": "auto"},
            ),
        ),
        en=(
            Intent(
                r"(?:speak|talk|answer|reply)(?: to me)?(?: in)? (?P<language>english|portuguese)"
            ),
            Intent(
                r"(?:switch|change)(?: the language)? to (?P<language>english|portuguese|automatic)"
            ),
            Intent(
                r"auto(?:matic)? language|detect (?:the )?language(?: automatically)?",
                {"language": "auto"},
            ),
        ),
    )

    def __init__(self, policy: LanguagePolicy) -> None:
        self._policy = policy

    async def run(self, params: SetLanguageParams) -> ToolResult:
        if params.language == "auto":
            await self._policy.lock(None)
            return ToolResult(Reply("language.auto"))
        await self._policy.lock(Language(params.language))
        # Spoken after the lock, so already in the new language.
        return ToolResult(Reply("language.locked"))
