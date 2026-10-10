import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from fakes import (
    FakeListener,
    FakePlayer,
    FakeStt,
    FakeTts,
    RejectEveryone,
    utterance,
)
from pydantic import BaseModel

from jarvis.audio.listener import Utterance
from jarvis.audio.tones import FeedbackSounds
from jarvis.core.pipeline import Pipeline
from jarvis.core.state import State
from jarvis.core.verification import AcceptEveryone, SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.router import Router
from jarvis.stt.base import Transcript
from jarvis.tools.base import Intent, Reply, Tool, ToolResult, phrasings

TEXTS = {
    Language.EN: {
        "startup.ready": ["Online, sir."],
        "pipeline.not_understood": ["Pardon, sir?"],
        "router.unknown": ["Beyond me, sir."],
        "confirm.cancelled": ["Cancelled, sir."],
        "errors.generic": ["Something broke, sir."],
        "test.greeted": ["Hello, sir."],
        "test.confirm": ["Detonate, sir?"],
        "test.done": ["Boom, sir."],
    },
    Language.PT: {
        "startup.ready": ["Online, senhor."],
        "pipeline.not_understood": ["Como, senhor?"],
        "router.unknown": ["Não sei, senhor."],
        "confirm.cancelled": ["Cancelado, senhor."],
        "errors.generic": ["Algo quebrou, senhor."],
        "test.greeted": ["Olá, senhor."],
        "test.confirm": ["Detonar, senhor?"],
        "test.done": ["Bum, senhor."],
    },
}
CONFIRMATION_TIMEOUT_S = 6.0


class NoParams(BaseModel):
    pass


class GreetTool(Tool[NoParams]):
    name = "greet"
    description = "Say hello."
    params_model = NoParams
    intents = phrasings(pt=(Intent("oi"),), en=(Intent("hello"),))

    async def run(self, params: NoParams) -> ToolResult:
        return ToolResult(Reply("test.greeted"))


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
    ) -> None:
        self.listener = listener
        self.stt = stt
        self.tts = FakeTts()
        self.player = FakePlayer()
        self.sounds = FeedbackSounds.create(0.1)
        self.detonate = DetonateTool()
        self.states: list[State] = []
        self.pipeline = Pipeline(
            listener=listener,
            stt=stt,
            tts=self.tts,
            player=self.player,
            sounds=self.sounds,
            translator=Translator(TEXTS, choose=lambda variants: variants[0]),
            router=Router([GreetTool(), self.detonate, BrokenTool()]),
            verifier=verifier or AcceptEveryone(),
            language=Language.PT,
            silence_ms=600,
            confirmation_timeout_s=CONFIRMATION_TIMEOUT_S,
        )
        self.pipeline.subscribe(self.states.append)

    async def ready(self) -> None:
        await self.pipeline.start()
        self.tts.spoken.clear()
        self.player.played.clear()
        self.states.clear()

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


def test_start_greets_in_the_default_language_with_a_cacheable_phrase() -> None:
    harness = Harness(FakeListener(), FakeStt())

    async def scenario() -> None:
        await harness.pipeline.start()

    run(scenario)

    assert harness.tts.spoken == [("Online, senhor.", Language.PT, True)]
    assert harness.pipeline.state is State.IDLE


def test_routed_command_replies_in_the_spoken_language() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Hello.", Language.EN)))

    run(harness.turns)

    assert harness.tts.spoken == [("Hello, sir.", Language.EN, True)]
    assert harness.player.played[:2] == [harness.sounds.start, harness.sounds.stop]
    assert harness.states == [State.LISTENING, State.THINKING, State.SPEAKING, State.IDLE]
    assert harness.pipeline.language is Language.EN


def test_previous_language_is_passed_to_speech_recognition() -> None:
    harness = Harness(
        heard(utterance(), utterance()),
        FakeStt(said("Hello.", Language.EN), said("Oi.", Language.PT)),
    )

    run(lambda: harness.turns(2))

    assert harness.stt.calls == [Language.PT, Language.EN]


def test_unknown_request_gets_a_polite_not_yet() -> None:
    harness = Harness(heard(utterance()), FakeStt(said("Me conta uma piada.")))

    run(harness.turns)

    assert harness.spoken_texts == ["Não sei, senhor."]


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
