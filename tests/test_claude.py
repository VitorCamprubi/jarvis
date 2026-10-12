import asyncio
from typing import Any

import anthropic
import httpx2
import pytest

from jarvis.brain.claude import ClaudeProvider, build_request, parse_response, to_native
from jarvis.brain.provider import (
    AssistantMessage,
    LlmAuthError,
    LlmError,
    LlmUnavailableError,
    ToolCall,
    ToolOutcome,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from jarvis.config import BrainConfig

CONFIG = BrainConfig(
    model="claude-haiku-5-5",
    effort="low",
    thinking="adaptive",
    max_tokens=1024,
    max_tool_rounds=4,
    request_timeout_s=20,
    memory_turns=6,
    memory_minutes=10,
)
TOOL = ToolSpec("weather", "Weather for a city.", {"type": "object", "properties": {}})
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

RESPONSE = anthropic.types.Message.model_validate(
    {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": "Checking, sir."},
            {"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"when": "tomorrow"}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 2400,
        },
    }
)


def test_request_caches_the_system_prompt_and_sets_thinking_and_effort() -> None:
    request = build_request(CONFIG, "You are JARVIS.", [UserMessage("Oi")], [TOOL])

    assert request["model"] == "claude-haiku-5-5"
    assert request["system"] == [
        {"type": "text", "text": "You are JARVIS.", "cache_control": {"type": "ephemeral"}}
    ]
    assert request["tools"][0]["name"] == "weather"
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"] == {"effort": "low"}
    assert request["messages"] == [{"role": "user", "content": "Oi"}]


def test_remembered_replies_are_text_and_turn_replies_are_replayed_unchanged() -> None:
    native = [{"type": "thinking", "thinking": "", "signature": "sig"}]

    assert to_native(AssistantMessage("Olá, senhor.")) == {
        "role": "assistant",
        "content": [{"type": "text", "text": "Olá, senhor."}],
    }
    assert to_native(AssistantMessage("", native=native)) == {
        "role": "assistant",
        "content": native,
    }


def test_tool_results_become_a_user_message() -> None:
    message = ToolResultsMessage((ToolOutcome("toolu_1", "Sunny", False),))

    assert to_native(message) == {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "Sunny", "is_error": False}
        ],
    }


def test_response_is_read_by_block_type() -> None:
    completion = parse_response(RESPONSE)

    assert completion.message.text == "Checking, sir."
    assert completion.message.tool_calls == (ToolCall("toolu_1", "weather", {"when": "tomorrow"}),)
    assert completion.stop_reason == "tool_use"
    assert completion.usage.cache_read_tokens == 2400
    # The original blocks, thinking included, travel along to be replayed within the turn.
    assert [block.type for block in completion.message.native] == ["thinking", "text", "tool_use"]


class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.messages = FakeMessages(outcome)


def provider(outcome: Any) -> ClaudeProvider:
    return ClaudeProvider(FakeClient(outcome), CONFIG)  # type: ignore[arg-type]


def status_error(cls: type[anthropic.APIStatusError], status: int, text: str = "") -> Exception:
    return cls(text, response=httpx2.Response(status, request=REQUEST), body=None)


def test_successful_completion() -> None:
    completion = asyncio.run(provider(RESPONSE).complete("system", [UserMessage("Oi")], [TOOL]))

    assert completion.message.text == "Checking, sir."


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(anthropic.AuthenticationError, 401), LlmAuthError),
        (
            status_error(
                anthropic.BadRequestError, 400, "anthropic-workspace-id is required for this key"
            ),
            LlmAuthError,
        ),
        (anthropic.APIConnectionError(request=REQUEST), LlmUnavailableError),
        (status_error(anthropic.RateLimitError, 429), LlmUnavailableError),
        (status_error(anthropic.InternalServerError, 529), LlmUnavailableError),
        (status_error(anthropic.BadRequestError, 400, "messages: invalid"), LlmError),
    ],
)
def test_sdk_errors_map_to_brain_errors(error: Exception, expected: type[Exception]) -> None:
    with pytest.raises(expected):
        asyncio.run(provider(error).complete("system", [UserMessage("Oi")], [TOOL]))
