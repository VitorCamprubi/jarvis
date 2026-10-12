"""What every tool provides (ADR-020): a description and a parameter schema (for the LLM in
Phase 3), router patterns in both languages, and the action itself."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar

from pydantic import BaseModel

from jarvis.i18n import Language, Translator


@dataclass(frozen=True)
class Intent:
    """One phrasing of a command: a regular expression that must match the whole normalised
    utterance, with named groups for arguments, plus fixed arguments."""

    pattern: str
    args: Mapping[str, object] = field(default_factory=dict)


def phrasings(*, pt: Sequence[Intent], en: Sequence[Intent]) -> Mapping[Language, Sequence[Intent]]:
    """A tool's phrasings, required in both languages; read-only once declared."""
    return MappingProxyType({Language.PT: tuple(pt), Language.EN: tuple(en)})


@dataclass(frozen=True)
class Reply:
    """What to say, as an i18n key plus its parameters. A parameter may itself be a Reply,
    rendered in the same language first (e.g. a weather condition inside a forecast)."""

    key: str
    params: Mapping[str, object] = field(default_factory=dict)
    # Measurements and free text make too many variants to be worth caching.
    cacheable: bool = True


def render(reply: Reply, translator: Translator, language: Language) -> str:
    params = {
        name: render(value, translator, language) if isinstance(value, Reply) else value
        for name, value in reply.params.items()
    }
    return translator.text(reply.key, language, **params)


@dataclass(frozen=True)
class ToolResult:
    reply: Reply
    details: str | None = None  # the full picture, for the HUD (Phase 5); logged for now
    # Set when the action needs a spoken "yes" first (ADR-025): it runs only once confirmed.
    on_confirm: Callable[[], Awaitable[ToolResult]] | None = None
    # Facts for the LLM to answer from. When the LLM called the tool and this is set, the LLM
    # words the reply (e.g. "Will it rain?"); otherwise the tool's own reply is spoken.
    model_data: str | None = None


class Tool[P: BaseModel](ABC):
    """Base class of every tool; ``P`` is the pydantic model of its parameters."""

    name: ClassVar[str]
    description: ClassVar[str]  # English, written for the LLM
    intents: ClassVar[Mapping[Language, Sequence[Intent]]]
    params_model: type[P]

    def accepts(self, args: Mapping[str, object]) -> bool:
        """Final say on a router match, for checks a regex cannot make (e.g. known sites)."""
        return True

    def parse(self, args: Mapping[str, object]) -> P:
        """Validate arguments from the router or, later, from the LLM."""
        return self.params_model.model_validate(args)

    @abstractmethod
    async def run(self, params: P) -> ToolResult: ...
