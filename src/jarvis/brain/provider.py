"""The LLM interface (ADR-026), with provider-neutral messages.

The brain speaks in these types; each provider translates them to its own API. Content a
provider must get back unchanged within a turn (such as Claude's thinking blocks) travels in
``AssistantMessage.native``.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class WebSearch:
    """Lets the model search the web itself during a request (ADR-034)."""

    max_uses: int  # searches allowed in this request
    city: str  # approximate location, for local results
    region: str
    country: str  # ISO 3166-1 alpha-2
    timezone: str


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    native: Any = None  # provider-specific content, replayed as is within the same turn
    sources: tuple[Source, ...] = ()  # web pages the answer is based on


@dataclass(frozen=True)
class ToolResultsMessage:
    results: tuple[ToolOutcome, ...]


Message = UserMessage | AssistantMessage | ToolResultsMessage


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0


@dataclass(frozen=True)
class Completion:
    message: AssistantMessage
    stop_reason: str  # "end_turn", "tool_use", "pause_turn", "max_tokens", "refusal"...
    usage: TokenUsage = field(default_factory=TokenUsage)


class LlmError(Exception):
    """The LLM request failed."""


class LlmUnavailableError(LlmError):
    """Network trouble, overload or rate limit: worth trying again later."""


class LlmAuthError(LlmError):
    """The key is missing, invalid, or not allowed to use the model."""


class LLMProvider(Protocol):
    @property
    def model(self) -> str: ...

    async def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        web_search: WebSearch | None = None,
    ) -> Completion: ...
