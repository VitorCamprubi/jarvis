import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fakes import (
    FakeListener,
    FakePlayer,
    FakeProvider,
    FakeStt,
    FakeTts,
    RejectEveryone,
    call,
    calls,
    says,
    utterance,
)
from pydantic import BaseModel

from jarvis.audio.listener import Utterance
from jarvis.audio.tones import FeedbackSounds
from jarvis.brain import Brain, BudgetGuard, ConversationMemory
from jarvis.brain.provider import TokenUsage
from jarvis.config import BudgetConfig
from jarvis.core.events import Event, JarvisSpoke, Shown, StateChanged, UserSpoke
from jarvis.core.language import LanguagePolicy
from jarvis.core.pipeline import Pipeline, greeting_key
from jarvis.core.state import State
from jarvis.core.verification import AcceptEveryone, SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.router import Router
from jarvis.storage import Database, UsageStore
from jarvis.stt.base import Transcript
from jarvis.tools.base import Intent, Link, Reply, Tool, ToolResult, phrasings

KEYS = {
    "startup.morning": ("Good morning, sir.", "Bom dia, senhor."),
    "startup.afternoon": ("Good afternoon, sir.", "Boa tarde, senhor."),
    "startup.evening": ("Good evening, sir.", "Boa noite, senhor."),
    "startup.night": ("Still up, sir?", "Ainda acordado, senhor?"),
    "pipeline.not_understood": ("Pardon, sir?", "Como, senhor?"),
    "router.unknown": ("Beyond me, sir.", "Não sei, senhor."),
    "brain.say": ("{text}", "{text}"),
    "brain.not_configured": ("No brain, sir.", "Sem cérebro, senhor."),
    "brain.budget_warning": ("Budget nearly spent, sir.", "Orçamento quase no fim, senhor."),
    "confirm.cancelled": ("Cancelled, sir.", "Cancelado, senhor."),
    "errors.generic": ("Something broke, sir.", "Algo quebrou, senhor."),
    "test.greeted": ("Hello, sir.", "Olá, senhor."),
    "test.confirm": ("Detonate, sir?", "Detonar, senhor?"),
    "test.done": ("Boom, sir.", "Bum, senhor."),
    "test.reminder": ("Reminder: {text}.", "Lembrete: {text}."),
}
TEXTS = {
    Language.EN: {key: [en] for key, (en, _) in KEYS.items()},
    Language.PT: {key: [pt] for key, (_, pt) in KEYS.items()},
}
CONFIRMATION_TIMEOUT_S = 6.0
MORNING = datetime(2026, 10, 12, 9, 0, tzinfo=timezone(timedelta(hours=-3)))


DOCS = Link("Manners", "https://example.com/manners", "web")


class NoParams(BaseModel):
    pass


class GreetTool(Tool[NoParams]):
    name = "greet"
    description = "Say hello."
    params_model = NoParams
    intents = phrasings(pt=(Intent("oi"),), en=(Intent("hello"),))

    async def run(self, params: NoParams) -> ToolResult:
        return ToolResult(Reply("test.greeted"), details="Greeted once.", links=(DOCS,))


class DetonateTool(Tool[NoParams]):
    name = "detonate"
    description = "Something that needs confirmation."
    params_model = NoParams
    intents = phrasings(pt=(Intent("explode"),), en=(Intent("blow up"),))

    def __init__(self) -> None:
        self.executed = False

    async def run(self, params: NoParams) -> ToolResult:
        async def execute() -> ToolResult:
            self.executed = True
            return ToolResult(Reply("test.done"))

        return ToolResult(Reply("test.confirm"), on_confirm=execute)


class BrokenTool(Tool[NoParams]):
    name = "broken"
    description = "Always fails."
    params_model = NoParams
    intents = phrasings(pt=(Intent("quebra"),), en=(Intent("break"),))

    async def run(self, params: NoParams) -> ToolResult:
        raise RuntimeError("tool on fire")


def said(text: str, language: Language = Language.PT) -> Transcript:
    return Transcript(text, language, 0.99)


class Harness:
    def __init__(
        self,
        listener: FakeListener,
        stt: FakeStt,
        verifier: SpeakerVerifier | None = None,
        llm: FakeProvider | None = None,
        warn_usd: float = 4.0,
    ) -> None:
        self.listener = listener
        self.stt = stt
        self.tts = FakeTts()
        self.player = FakePlayer()
        self.sounds = FeedbackSounds.create(0.1)
        self.detonate = DetonateTool()
        self.events: list[Event] = []
        self.memory = ConversationMemory(max_exchanges=6, ttl_s=600)
        self.policy = LanguagePolicy()
        translator = Translator(TEXTS, choose=lambda variants: variants[0])
        tools: list[Tool[Any]] = [GreetTool(), self.detonate, BrokenTool()]
        brain = None
        if llm is not None:
            budget = BudgetConfig(
                warn_usd=warn_usd,
                stop_usd=4.9,
                input_per_mtok=0.10,
                output_per_mtok=0.50,
                cache_write_per_mtok=0.125,
                cache_read_per_mtok=0.01,
                web_search_usd=0.01,
            )
            brain = Brain(
                provider=llm,
                tools=tools,
                budget=BudgetGuard(UsageStore(Database(":memory:")), budget),
                memory=self.memory,
                translator=translator,
                system="You are JARVIS.",
                max_tool_rounds=3,
            )
        self.pipeline = Pipeline(
            listener=listener,
            stt=stt,
            tts=self.tts,
            player=self.player,
            sounds=self.sounds,
            translator=translator,
            router=Router(tools),
            brain=brain,
            memory=self.memory,
            policy=self.policy,
            verifier=verifier or AcceptEveryone(),
            language=Language.PT,
            silence_ms=600,
            confirmation_timeout_s=CONFIRMATION_TIMEOUT_S,
            clock=lambda: MORNING,
        )
        self.pipeline.subscribe(self.events.append)

    @property
    def states(self) -> list[State]:
        return [event.state for event in self.events if isinstance(event, StateChanged)]

    async def ready(self) -> None:
        await self.pipeline.start()
        self.tts.spoken.clear()
        self.player.played.clear()
        self.events.clear()

    async def turns(self, count: int = 1) -> None:
        await self.ready()
        for _ in range(count):
            turn = self.pipeline.activate()
            assert turn is not None
            await turn

    @property
    def spoken_texts(self) -> list[str]:
        return [text for text, _, _ in self.tts.spoken]


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(scenario())


def heard(*results: Utterance | None) -> FakeListener:
    return FakeListener(*results)


@pytest.mark.parametrize(
    ("hour", "key"),
    [
        (5, "startup.morning"),
        (13, "startup.afternoon"),
        (21, "startup.evening"),
        (2, "startup.night"),
    ],
)
def test_greeting_depends_on_the_time_of_day(hour: int, key: str) -> None:
    assert greeting_key(hour) == key


def test_start_greets_in_the_default_language_with_a_cacheable_phrase() -> None:
    harness = Harness(FakeListener(), FakeStt())

    async def scenario() -> None:
        await harness.pipeline.start()

    run(scenario)

    assert harness.tts.spoken == [("Bom dia, senhor.", Language.PT, True)]
    assert harness.pipeline.state is State.IDLE


def test_routed_command_replies_in_the_spoken_language() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Hello.", Language.EN)))

    run(harness.turns)

    assert harness.tts.spoken == [("Hello, sir.", Language.EN, True)]
    assert harness.player.played[:2] == [harness.sounds.start, harness.sounds.stop]
    assert harness.states == [State.LISTENING, State.THINKING, State.SPEAKING, State.IDLE]
    assert harness.pipeline.language is Language.EN


def test_the_turn_is_published_for_the_hud() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Hello.", Language.EN)))

    run(harness.turns)

    assert [e for e in harness.events if not isinstance(e, StateChanged)] == [
        UserSpoke("Hello.", Language.EN),
        Shown("Greeted once.", (DOCS,)),
        JarvisSpoke("Hello, sir.", Language.EN),
    ]


def test_previous_language_is_passed_to_speech_recognition() -> None:
    harness = Harness(
        heard(utterance(), utterance()),
        FakeStt(said("Hello.", Language.EN), said("Oi.", Language.PT)),
    )

    run(lambda: harness.turns(2))

    assert harness.stt.calls == [Language.PT, Language.EN]


def test_locked_language_overrides_the_spoken_one() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Oi.", Language.PT)))

    async def scenario() -> None:
        await harness.policy.lock(Language.EN)
        await harness.turns()

    run(scenario)

    assert harness.tts.spoken == [("Hello, sir.", Language.EN, True)]


def test_without_an_llm_unknown_requests_get_a_polite_not_configured() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Me conta uma piada.")))

    run(harness.turns)

    assert harness.spoken_texts == ["Sem cérebro, senhor."]


def test_unknown_requests_go_to_the_llm_and_its_words_are_not_cached() -> None:
    llm = FakeProvider(says("Por que o programador usa óculos? Porque não enxerga C#."))
    harness = Harness(heard(utterance()), FakeStt(said("Me conta uma piada.")), llm=llm)

    run(harness.turns)

    assert harness.tts.spoken == [
        ("Por que o programador usa óculos? Porque não enxerga C#.", Language.PT, False)
    ]
    _, messages, tools = llm.requests[0]
    assert "Me conta uma piada." in str(messages[-1])
    assert {tool.name for tool in tools} == {"greet", "detonate", "broken"}


def test_every_exchange_is_remembered_for_follow_ups() -> None:
    llm = FakeProvider(says("Amanhã também, senhor."))
    harness = Harness(
        heard(utterance(), utterance()), FakeStt(said("Oi."), said("E amanhã?")), llm=llm
    )

    run(lambda: harness.turns(2))

    _, messages, _ = llm.requests[0]
    # The rule-handled first exchange is part of the LLM's context for the follow-up.
    assert [type(m).__name__ for m in messages] == [
        "UserMessage",
        "AssistantMessage",
        "UserMessage",
    ]
    assert "Oi." in str(messages[0]) and "Olá, senhor." in str(messages[1])


def test_budget_warning_is_spoken_once_after_the_reply() -> None:
    expensive = TokenUsage(input_tokens=10_000_000, output_tokens=0)  # US$ 1.00
    llm = FakeProvider(says("Feito.", usage=expensive))
    harness = Harness(heard(utterance()), FakeStt(said("Faz algo.")), llm=llm, warn_usd=0.5)

    run(harness.turns)

    assert harness.spoken_texts == ["Feito.", "Orçamento quase no fim, senhor."]


def test_confirmed_action_runs_after_a_spoken_yes() -> None:
    harness = Harness(heard(utterance(), utterance()), FakeStt(said("Explode."), said("Sim.")))

    run(harness.turns)

    assert harness.detonate.executed
    assert harness.spoken_texts == ["Detonar, senhor?", "Bum, senhor."]
    # The answer is awaited without the hotkey, for the confirmation timeout only.
    assert harness.listener.timeouts == [None, CONFIRMATION_TIMEOUT_S]


def test_a_no_cancels_the_action() -> None:
    harness = Harness(heard(utterance(), utterance()), FakeStt(said("Explode."), said("Não.")))

    run(harness.turns)

    assert not harness.detonate.executed
    assert harness.spoken_texts == ["Detonar, senhor?", "Cancelado, senhor."]


def test_silence_cancels_the_action() -> None:
    harness = Harness(heard(utterance(), None), FakeStt(said("Explode.")))

    run(harness.turns)

    assert not harness.detonate.executed
    assert harness.spoken_texts[-1] == "Cancelado, senhor."


def test_an_llm_requested_action_still_needs_a_spoken_yes() -> None:
    llm = FakeProvider(calls(call("detonate")))
    harness = Harness(
        heard(utterance(), utterance()),
        FakeStt(said("Pode explodir tudo, por gentileza?"), said("Não.")),
        llm=llm,
    )

    run(harness.turns)

    assert not harness.detonate.executed
    assert harness.spoken_texts == ["Detonar, senhor?", "Cancelado, senhor."]


def test_announcements_wait_for_the_current_turn() -> None:
    listener = FakeListener()  # listens until cancelled
    harness = Harness(listener, FakeStt())

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await listener.listening.wait()
        harness.pipeline.announce(Reply("test.reminder", {"text": "chá"}), Language.PT)
        assert harness.spoken_texts == []  # still listening: nothing said yet
        harness.pipeline.activate()  # cancels the listening turn
        await asyncio.gather(turn, return_exceptions=True)
        for _ in range(5):  # let the queued announcement run
            await asyncio.sleep(0)

    run(scenario)
    assert harness.spoken_texts == ["Lembrete: chá."]


def test_announcement_when_idle_is_spoken_at_once() -> None:
    harness = Harness(FakeListener(), FakeStt())

    async def scenario() -> None:
        await harness.ready()
        harness.pipeline.announce(Reply("test.reminder", {"text": "tea"}), Language.EN)
        for _ in range(5):
            await asyncio.sleep(0)

    run(scenario)
    assert harness.tts.spoken == [("Reminder: tea.", Language.EN, True)]


def test_no_speech_skips_transcription() -> None:
    harness = Harness(heard(None), FakeStt())

    run(harness.turns)

    assert harness.stt.calls == []
    assert harness.tts.spoken == []
    assert harness.player.played == [harness.sounds.start, harness.sounds.stop]
    assert harness.pipeline.state is State.IDLE


def test_empty_transcript_gets_an_apology_in_the_current_language() -> None:
    harness = Harness(heard(utterance()), FakeStt(Transcript("", Language.EN, 0.6)))

    run(harness.turns)

    assert harness.spoken_texts == ["Como, senhor?"]


def test_failures_are_reported_in_character_and_the_pipeline_recovers() -> None:
    harness = Harness(
        heard(utterance(), utterance(), utterance()),
        FakeStt(RuntimeError("GPU on fire"), said("Quebra."), said("Oi.")),
    )

    run(lambda: harness.turns(3))

    assert harness.spoken_texts == [
        "Algo quebrou, senhor.",
        "Algo quebrou, senhor.",
        "Olá, senhor.",
    ]
    assert harness.pipeline.state is State.IDLE


def test_second_press_while_listening_cancels_the_turn() -> None:
    listener = FakeListener()  # never hears anything: listens until cancelled
    harness = Harness(listener, FakeStt())

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await listener.listening.wait()
        assert harness.pipeline.activate() is None
        await asyncio.gather(turn, return_exceptions=True)
        assert turn.cancelled()

    run(scenario)
    assert harness.stt.calls == []
    assert harness.pipeline.state is State.IDLE


def test_press_while_thinking_is_ignored() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Oi.")))

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        while harness.pipeline.state is not State.THINKING:
            await asyncio.sleep(0)
        assert harness.pipeline.activate() is None
        await turn

    run(scenario)
    assert harness.spoken_texts == ["Olá, senhor."]


def test_activation_is_ignored_until_started() -> None:
    harness = Harness(heard(utterance()), FakeStt())

    async def scenario() -> None:
        assert harness.pipeline.activate() is None

    run(scenario)
    assert harness.listener.calls == 0


def test_rejected_voice_is_not_transcribed() -> None:
    harness = Harness(heard(utterance()), FakeStt(), verifier=RejectEveryone())

    run(harness.turns)

    assert harness.stt.calls == []
