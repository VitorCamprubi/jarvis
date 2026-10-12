import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fakes import FakeProvider, call, calls, says
from pydantic import BaseModel, Field

from jarvis.brain import Brain, BrainAnswer, BudgetGuard, ConversationMemory
from jarvis.brain.provider import (
    LlmAuthError,
    LlmUnavailableError,
    TokenUsage,
    ToolCall,
    ToolResultsMessage,
    UserMessage,
)
from jarvis.config import BudgetConfig
from jarvis.i18n import Language, Translator
from jarvis.storage import Database, UsageStore
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

NOW = datetime(2026, 10, 12, 14, 5, tzinfo=timezone(timedelta(hours=-3)))
KEYS = [
    "brain.say", "brain.budget_exhausted", "brain.refused", "brain.unavailable",
    "brain.auth_failed", "errors.generic", "test.greeted", "test.facts", "test.confirm",
]  # fmt: skip
TEXTS = {
    Language.EN: {key: ["{text}" if key == "brain.say" else key] for key in KEYS},
    Language.PT: {key: ["{text}" if key == "brain.say" else key] for key in KEYS},
}


class NoParams(BaseModel):
    pass


class CountParams(BaseModel):
    count: int = Field(ge=1)


class GreetTool(Tool[NoParams]):
    name = "greet"
    description = "Say hello."
    params_model = NoParams
    intents = phrasings(pt=(Intent("oi"),), en=(Intent("hi"),))

    async def run(self, params: NoParams) -> ToolResult:
        return ToolResult(Reply("test.greeted"))


class FactsTool(Tool[CountParams]):
    name = "facts"
    description = "Return some facts for the model to word."
    params_model = CountParams
    intents = phrasings(pt=(), en=())

    async def run(self, params: CountParams) -> ToolResult:
        return ToolResult(Reply("test.facts"), model_data=f"{params.count} facts: sky is blue")


class ConfirmTool(Tool[NoParams]):
    name = "dangerous"
    description = "Needs a spoken yes."
    params_model = NoParams
    intents = phrasings(pt=(), en=())

    async def run(self, params: NoParams) -> ToolResult:
        async def execute() -> ToolResult:
            return ToolResult(Reply("test.greeted"))

        return ToolResult(Reply("test.confirm"), on_confirm=execute)


def budget_config(warn: float = 4.0, stop: float = 4.9) -> BudgetConfig:
    return BudgetConfig(
        warn_usd=warn,
        stop_usd=stop,
        input_per_mtok=0.10,
        output_per_mtok=0.50,
        cache_write_per_mtok=0.125,
        cache_read_per_mtok=0.01,
    )


class Setup:
    def __init__(self, llm: FakeProvider, warn: float = 4.0, stop: float = 4.9) -> None:
        self.llm = llm
        self.store = UsageStore(Database(":memory:"))
        self.memory = ConversationMemory(max_exchanges=6, ttl_s=600)
        self.brain = Brain(
            provider=llm,
            tools=[GreetTool(), FactsTool(), ConfirmTool()],
            budget=BudgetGuard(self.store, budget_config(warn, stop), clock=lambda: NOW),
            memory=self.memory,
            translator=Translator(TEXTS),
            system="You are JARVIS.",
            max_tool_rounds=3,
            clock=lambda: NOW,
        )

    def answer(self, text: str = "pergunta", language: Language = Language.PT) -> BrainAnswer:
        return asyncio.run(self.brain.answer(text, language))


def keys(answer: BrainAnswer) -> list[str]:
    return [result.reply.key for result in answer.results]


def test_plain_answer_is_spoken_and_never_cached() -> None:
    setup = Setup(FakeProvider(says("Às suas ordens.")))

    answer = setup.answer("Tudo bem?")

    reply = answer.results[0].reply
    assert (reply.key, reply.params, reply.cacheable) == (
        "brain.say",
        {"text": "Às suas ordens."},
        False,
    )
    system, messages, tools = setup.llm.requests[0]
    assert system == "You are JARVIS."
    assert [tool.name for tool in tools] == ["greet", "facts", "dangerous"]
    note = messages[-1]
    assert isinstance(note, UserMessage)
    assert "Monday, 12 October 2026, 14:05" in note.text
    assert "Reply in Brazilian Portuguese" in note.text
    assert note.text.endswith("Tudo bem?")


def test_action_tool_speaks_for_itself_without_a_second_call() -> None:
    setup = Setup(FakeProvider(calls(call("greet"))))

    assert keys(setup.answer()) == ["test.greeted"]
    assert len(setup.llm.requests) == 1


def test_facts_go_back_to_the_model_which_words_the_answer() -> None:
    setup = Setup(FakeProvider(calls(call("facts", count=2)), says("O céu está azul, senhor.")))

    answer = setup.answer("De que cor é o céu?")

    assert answer.results[0].reply.params == {"text": "O céu está azul, senhor."}
    _, messages, _ = setup.llm.requests[1]
    results = messages[-1]
    assert isinstance(results, ToolResultsMessage)
    assert results.results[0].content == "2 facts: sky is blue"
    assert not results.results[0].is_error


@pytest.mark.parametrize(
    ("bad_call", "error"),
    [
        (call("format_disk"), "There is no tool named 'format_disk'"),
        (call("facts", count=0), "Invalid arguments"),
    ],
)
def test_unknown_tools_and_bad_arguments_are_reported_to_the_model(
    bad_call: ToolCall, error: str
) -> None:
    setup = Setup(FakeProvider(calls(bad_call), says("Não consegui, senhor.")))

    answer = setup.answer()

    assert answer.results[0].reply.params == {"text": "Não consegui, senhor."}
    _, messages, _ = setup.llm.requests[1]
    results = messages[-1]
    assert isinstance(results, ToolResultsMessage)
    assert results.results[0].is_error
    assert error in results.results[0].content


def test_dangerous_tool_comes_back_for_spoken_confirmation() -> None:
    setup = Setup(FakeProvider(calls(call("dangerous"))))

    answer = setup.answer()

    assert keys(answer) == ["test.confirm"]
    assert answer.results[0].on_confirm is not None
    assert len(setup.llm.requests) == 1


def test_exhausted_budget_stops_before_calling_the_model() -> None:
    llm = FakeProvider()
    setup = Setup(llm, warn=0.5, stop=1.0)
    asyncio.run(setup.store.add(NOW, "claude-haiku-5-5", (0, 0, 0, 0), cost_usd=1.0))

    assert keys(setup.answer()) == ["brain.budget_exhausted"]
    assert llm.requests == []


def test_usage_is_priced_and_crossing_the_warning_is_reported() -> None:
    usage = TokenUsage(input_tokens=2_000_000, output_tokens=200_000)  # 0.20 + 0.10 = US$ 0.30
    setup = Setup(FakeProvider(says("Ok.", usage=usage)), warn=0.25)

    answer = setup.answer()

    assert answer.budget_warning
    assert asyncio.run(setup.store.total_cost()) == pytest.approx(0.30)


def test_refusal_is_answered_in_character() -> None:
    setup = Setup(FakeProvider(says("", stop="refusal")))

    assert keys(setup.answer()) == ["brain.refused"]


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (LlmUnavailableError("offline"), "brain.unavailable"),
        (LlmAuthError("bad key"), "brain.auth_failed"),
    ],
)
def test_llm_failures_are_answered_in_character(error: Exception, key: str) -> None:
    assert keys(Setup(FakeProvider(error)).answer()) == [key]


def test_endless_tool_loops_give_up() -> None:
    loop = [calls(call("facts", call_id=f"c{i}", count=1)) for i in range(3)]
    setup = Setup(FakeProvider(*loop))

    assert keys(setup.answer()) == ["errors.generic"]
    assert len(setup.llm.requests) == 3


def test_remembered_exchanges_come_before_the_new_request() -> None:
    setup = Setup(FakeProvider(says("Amanhã também, senhor.")))
    setup.memory.add("Vai chover hoje?", "Hoje não, senhor.")

    setup.answer("E amanhã?")

    _, messages, _ = setup.llm.requests[0]
    assert [type(m).__name__ for m in messages] == [
        "UserMessage",
        "AssistantMessage",
        "UserMessage",
    ]
