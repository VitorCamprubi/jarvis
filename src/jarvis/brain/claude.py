"""Claude through the official Anthropic SDK (ADR-009, ADR-026, ADR-027, ADR-034)."""

import re
from collections.abc import Sequence
from typing import Any

import anthropic

from jarvis.brain.provider import (
    AssistantMessage,
    Completion,
    LlmAuthError,
    LlmError,
    LlmUnavailableError,
    Message,
    Source,
    TokenUsage,
    ToolCall,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
    WebSearch,
)
from jarvis.config import BrainConfig

WEB_SEARCH_TOOL = "web_search_20250305"  # basic search: Haiku 5.5 has no programmatic tool calls
SEARCH_RESULT = "web_search_tool_result"


class ClaudeProvider:
    def __init__(self, client: anthropic.AsyncAnthropic, config: BrainConfig) -> None:
        self._client = client
        self._config = config

    @property
    def model(self) -> str:
        return self._config.model

    async def complete(
        self,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
        web_search: WebSearch | None = None,
    ) -> Completion:
        try:
            response = await self._client.messages.create(
                **build_request(self._config, system, messages, tools, web_search)
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise LlmAuthError(str(exc)) from exc
        except anthropic.BadRequestError as exc:
            if "anthropic-workspace-id" in str(exc):
                raise LlmAuthError(
                    "the API key is not tied to a workspace; create it inside the 'jarvis' "
                    "workspace"
                ) from exc
            raise LlmError(str(exc)) from exc
        except (
            anthropic.APIConnectionError,  # includes timeouts
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ) as exc:
            raise LlmUnavailableError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            raise LlmError(str(exc)) from exc
        return parse_response(response)


def build_request(
    config: BrainConfig,
    system: str,
    messages: Sequence[Message],
    tools: Sequence[ToolSpec],
    web_search: WebSearch | None = None,
) -> dict[str, Any]:
    """Keyword arguments for messages.create(). Tools and system prompt rarely change between
    requests, so the cache breakpoint on the system prompt covers both (tools come first);
    web search goes last and only leaves when the day's searches run out."""
    native_tools: list[dict[str, Any]] = [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]
    if web_search is not None:
        native_tools.append(search_tool(web_search))
    request: dict[str, Any] = {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [to_native(message) for message in messages],
        "thinking": {"type": config.thinking},
        "output_config": {"effort": config.effort},
    }
    if native_tools:
        request["tools"] = native_tools
    return request


def search_tool(web_search: WebSearch) -> dict[str, Any]:
    return {
        "type": WEB_SEARCH_TOOL,
        "name": "web_search",
        "max_uses": web_search.max_uses,
        "user_location": {
            "type": "approximate",
            "city": web_search.city,
            "region": web_search.region,
            "country": web_search.country,
            "timezone": web_search.timezone,
        },
    }


def to_native(message: Message) -> dict[str, Any]:
    match message:
        case UserMessage(text=text):
            return {"role": "user", "content": text}
        case AssistantMessage(text=text, native=native):
            # Within a turn the original blocks go back unchanged (thinking included);
            # remembered exchanges are text only (ADR-028).
            content = native if native is not None else [{"type": "text", "text": text}]
            return {"role": "assistant", "content": content}
        case ToolResultsMessage(results=results):
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.call_id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                    for result in results
                ],
            }


def parse_response(response: Any) -> Completion:
    blocks = list(response.content)
    # Text written before a search ("let me look that up") is not part of the answer.
    last_search = max(
        (i for i, block in enumerate(blocks) if block.type == SEARCH_RESULT), default=-1
    )
    # Cited answers arrive split into several text blocks, spacing included.
    text = tidy(
        "".join(
            block.text
            for block in blocks[last_search + 1 :]
            if block.type == "text" and not is_pasted_quote(block)
        )
    )
    calls = tuple(
        ToolCall(block.id, block.name, dict(block.input))
        for block in blocks
        if block.type == "tool_use"
    )
    usage = response.usage
    server_tools = getattr(usage, "server_tool_use", None)
    return Completion(
        message=AssistantMessage(text, calls, native=blocks, sources=sources(blocks)),
        stop_reason=str(response.stop_reason),
        usage=TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            web_searches=(server_tools.web_search_requests or 0) if server_tools else 0,
        ),
    )


def is_pasted_quote(block: Any) -> bool:
    """A text block that only repeats the page it cites ("PLACAR FINAL: Flamengo 1 x 0 ...").
    Fine on a screen, nonsense when spoken; the model's own cited sentences are kept."""
    text = " ".join(block.text.split())
    return bool(text) and any(
        text in " ".join((getattr(citation, "cited_text", None) or "").split())
        for citation in getattr(block, "citations", None) or ()
    )


def tidy(text: str) -> str:
    """Single spaces, no space before punctuation, no punctuation left doubled by a removed
    quote ("centavo. . Como" -> "centavo. Como")."""
    text = " ".join(text.split())
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return re.sub(r"([.!?])[.,;:]+", r"\1", text)


def sources(blocks: Sequence[Any]) -> tuple[Source, ...]:
    """The pages cited in the answer; failing that, every search result."""
    cited = [
        (citation.title, citation.url)
        for block in blocks
        if block.type == "text"
        for citation in getattr(block, "citations", None) or ()
        if getattr(citation, "url", None)
    ]
    found = cited or [
        (result.title, result.url)
        for block in blocks
        if block.type == SEARCH_RESULT and isinstance(block.content, list)  # else an error
        for result in block.content
    ]
    unique: dict[str, Source] = {}
    for title, url in found:
        unique.setdefault(url, Source(title or url, url))
    return tuple(unique.values())
