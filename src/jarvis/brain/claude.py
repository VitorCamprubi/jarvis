"""Claude through the official Anthropic SDK (ADR-009, ADR-026, ADR-027)."""

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
    TokenUsage,
    ToolCall,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from jarvis.config import BrainConfig


class ClaudeProvider:
    def __init__(self, client: anthropic.AsyncAnthropic, config: BrainConfig) -> None:
        self._client = client
        self._config = config

    @property
    def model(self) -> str:
        return self._config.model

    async def complete(
        self, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
    ) -> Completion:
        try:
            response = await self._client.messages.create(
                **build_request(self._config, system, messages, tools)
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
    config: BrainConfig, system: str, messages: Sequence[Message], tools: Sequence[ToolSpec]
) -> dict[str, Any]:
    """Keyword arguments for messages.create(). Tools and system prompt never change between
    requests, so the cache breakpoint on the system prompt covers both (tools come first)."""
    return {
        "model": config.model,
        "max_tokens": config.max_tokens,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "tools": [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in tools
        ],
        "messages": [to_native(message) for message in messages],
        "thinking": {"type": config.thinking},
        "output_config": {"effort": config.effort},
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
    text = " ".join(block.text for block in response.content if block.type == "text").strip()
    calls = tuple(
        ToolCall(block.id, block.name, dict(block.input))
        for block in response.content
        if block.type == "tool_use"
    )
    usage = response.usage
    return Completion(
        message=AssistantMessage(text, calls, native=list(response.content)),
        stop_reason=str(response.stop_reason),
        usage=TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
        ),
    )
