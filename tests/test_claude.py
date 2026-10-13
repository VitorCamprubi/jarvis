import asyncio
from typing import Any

import anthropic
import httpx2
import pytest

from jarvis.brain.claude import ClaudeProvider, build_request, parse_response, tidy, to_native
from jarvis.brain.provider import (
    AssistantMessage,
    LlmAuthError,
    LlmError,
    LlmUnavailableError,
    Source,
    ToolCall,
    ToolOutcome,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
    WebSearch,
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


SEARCH = WebSearch(2, "Sorocaba", "SP", "BR", "America/Sao_Paulo")


def test_web_search_goes_last_with_the_users_location() -> None:
    request = build_request(CONFIG, "You are JARVIS.", [UserMessage("Oi")], [TOOL], SEARCH)

    assert [tool["name"] for tool in request["tools"]] == ["weather", "web_search"]
    assert request["tools"][1] == {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 2,
        "user_location": {
            "type": "approximate",
            "city": "Sorocaba",
            "region": "SP",
            "country": "BR",
            "timezone": "America/Sao_Paulo",
        },
    }


def test_a_request_without_tools_sends_none() -> None:
    assert "tools" not in build_request(CONFIG, "Summarise.", [UserMessage("Headlines")], [])


def search_response(citations: bool) -> Any:
    cited = [
        {
            "type": "web_search_result_location",
            "url": "https://ge.globo.com/palmeiras",
            "title": "Palmeiras vence",
            "encrypted_index": "idx",
            "cited_text": "O Palmeiras venceu por 2 a 0.",
        }
    ]
    return anthropic.types.Message.model_validate(
        {
            "id": "msg_2",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-5-5",
            "content": [
                {"type": "text", "text": "Vou pesquisar, senhor."},
                {
                    "type": "server_tool_use",
                    "id": "srvtoolu_1",
                    "name": "web_search",
                    "input": {"query": "último jogo Palmeiras"},
                },
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "srvtoolu_1",
                    "content": [
                        {
                            "type": "web_search_result",
                            "url": "https://ge.globo.com/palmeiras",
                            "title": "Palmeiras vence",
                            "encrypted_content": "enc",
                            "page_age": "October 12, 2026",
                        },
                        {
                            "type": "web_search_result",
                            "url": "https://espn.com.br/palmeiras",
                            "title": "Resultados do Palmeiras",
                            "encrypted_content": "enc",
                            "page_age": None,
                        },
                    ],
                },
                {"type": "text", "text": "O Palmeiras venceu ", "citations": None},
                {
                    "type": "text",
                    "text": " por dois a zero, senhor.",
                    "citations": cited if citations else None,
                },
            ],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 15000,
                "output_tokens": 80,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 2900,
                "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0},
            },
        }
    )


def test_search_answers_keep_only_the_text_after_the_search() -> None:
    completion = parse_response(search_response(citations=True))

    assert completion.message.text == "O Palmeiras venceu por dois a zero, senhor."
    assert completion.message.sources == (
        Source("Palmeiras vence", "https://ge.globo.com/palmeiras"),
    )
    assert completion.usage.web_searches == 1


def test_without_citations_every_search_result_is_a_source() -> None:
    sources = parse_response(search_response(citations=False)).message.sources

    assert [source.url for source in sources] == [
        "https://ge.globo.com/palmeiras",
        "https://espn.com.br/palmeiras",
    ]


def test_answers_without_search_count_no_searches() -> None:
    assert parse_response(RESPONSE).usage.web_searches == 0


def test_a_pasted_quote_of_the_page_is_not_spoken() -> None:
    response = search_response(citations=False).model_copy(deep=True)
    quote = "PLACAR FINAL: Palmeiras 2 x 0 Santos. FIM DE JOGO!"
    response.content[-1] = anthropic.types.TextBlock.model_validate(
        {
            "type": "text",
            "text": quote,
            "citations": [
                {
                    "type": "web_search_result_location",
                    "url": "https://ge.globo.com/palmeiras",
                    "title": "Palmeiras vence",
                    "encrypted_index": "idx",
                    "cited_text": f"{quote}\n\n",
                }
            ],
        }
    )
    response.content.append(anthropic.types.TextBlock(type="text", text=". Foi ontem, senhor."))

    text = parse_response(response).message.text

    assert text == "O Palmeiras venceu. Foi ontem, senhor."


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("Saiu em 9 October 2026 , four days ago.", "Saiu em 9 October 2026, four days ago."),
        ("um centavo.  . Como a fonte", "um centavo. Como a fonte"),
        ("Custa 5,01 reais e subiu 0.68 por cento.", "Custa 5,01 reais e subiu 0.68 por cento."),
    ],
)
def test_spoken_text_is_tidied(raw: str, spoken: str) -> None:
    assert tidy(raw) == spoken
