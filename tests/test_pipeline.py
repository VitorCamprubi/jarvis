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

from jarvis.audio.tones import FeedbackSounds
from jarvis.core.pipeline import Pipeline
from jarvis.core.state import State
from jarvis.core.verification import AcceptEveryone, SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.stt.base import Transcript

TEXTS = {
    Language.EN: {
        "startup.ready": ["Online, sir."],
        "pipeline.heard": ["You said: {text}"],
        "pipeline.not_understood": ["Pardon, sir?"],
        "errors.generic": ["Something broke, sir."],
    },
    Language.PT: {
        "startup.ready": ["Online, senhor."],
        "pipeline.heard": ["O senhor disse: {text}"],
        "pipeline.not_understood": ["Como, senhor?"],
        "errors.generic": ["Algo quebrou, senhor."],
    },
}


class Harness:
    def __init__(
        self,
        listener: FakeListener,
        stt: FakeStt,
        tts: FakeTts | None = None,
        verifier: SpeakerVerifier | None = None,
    ) -> None:
        self.listener = listener
        self.stt = stt
        self.tts = tts or FakeTts()
        self.player = FakePlayer()
        self.sounds = FeedbackSounds.create(0.1)
        self.states: list[State] = []
        self.pipeline = Pipeline(
            listener=listener,
            stt=stt,
            tts=self.tts,
            player=self.player,
            sounds=self.sounds,
            translator=Translator(TEXTS, choose=lambda variants: variants[0]),
            verifier=verifier or AcceptEveryone(),
            language=Language.PT,
            silence_ms=600,
        )
        self.pipeline.subscribe(self.states.append)

    async def ready(self) -> None:
        await self.pipeline.start()
        self.tts.spoken.clear()
        self.player.played.clear()
        self.states.clear()

    @property
    def spoken_texts(self) -> list[str]:
        return [text for text, _, _ in self.tts.spoken]


def run(scenario: Callable[[], Coroutine[Any, Any, None]]) -> None:
    asyncio.run(scenario())


def test_start_greets_in_the_default_language_with_a_cacheable_phrase() -> None:
    harness = Harness(FakeListener(), FakeStt())

    async def scenario() -> None:
        await harness.pipeline.start()

    run(scenario)
    assert harness.tts.spoken == [("Online, senhor.", Language.PT, True)]
    assert harness.pipeline.state is State.IDLE


def test_turn_repeats_what_was_heard_in_the_detected_language() -> None:
    harness = Harness(
        FakeListener(utterance()), FakeStt(Transcript("Open Spotify.", Language.EN, 0.99))
    )

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await turn

    run(scenario)
    # The reply contains what the user said, so it must not be cached.
    assert harness.tts.spoken == [("You said: Open Spotify.", Language.EN, False)]
    assert harness.player.played[:2] == [harness.sounds.start, harness.sounds.stop]
    assert len(harness.player.played) == 3
    assert harness.states == [State.LISTENING, State.THINKING, State.SPEAKING, State.IDLE]
    assert harness.pipeline.language is Language.EN


def test_previous_language_is_passed_to_speech_recognition() -> None:
    harness = Harness(
        FakeListener(utterance(), utterance()),
        FakeStt(
            Transcript("Open Spotify.", Language.EN, 0.99),
            Transcript("Abre o Spotify.", Language.PT, 0.95),
        ),
    )

    async def scenario() -> None:
        await harness.ready()
        for _ in range(2):
            turn = harness.pipeline.activate()
            assert turn is not None
            await turn

    run(scenario)
    assert harness.stt.calls == [Language.PT, Language.EN]


def test_no_speech_skips_transcription() -> None:
    harness = Harness(FakeListener(None), FakeStt())

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await turn

    run(scenario)
    assert harness.stt.calls == []
    assert harness.tts.spoken == []
    assert harness.player.played == [harness.sounds.start, harness.sounds.stop]
    assert harness.pipeline.state is State.IDLE


def test_empty_transcript_gets_an_apology_in_the_current_language() -> None:
    harness = Harness(FakeListener(utterance()), FakeStt(Transcript("", Language.EN, 0.6)))

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await turn

    run(scenario)
    assert harness.spoken_texts == ["Como, senhor?"]


def test_failure_is_reported_in_character_and_pipeline_recovers() -> None:
    harness = Harness(
        FakeListener(utterance(), utterance()),
        FakeStt(RuntimeError("GPU on fire"), Transcript("Oi.", Language.PT, 0.9)),
    )

    async def scenario() -> None:
        await harness.ready()
        for _ in range(2):
            turn = harness.pipeline.activate()
            assert turn is not None
            await turn

    run(scenario)
    assert harness.spoken_texts == ["Algo quebrou, senhor.", "O senhor disse: Oi."]
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
    harness = Harness(FakeListener(utterance()), FakeStt(Transcript("Oi.", Language.PT, 0.9)))

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        while harness.pipeline.state is not State.THINKING:
            await asyncio.sleep(0)
        assert harness.pipeline.activate() is None
        await turn

    run(scenario)
    assert harness.spoken_texts == ["O senhor disse: Oi."]


def test_activation_is_ignored_until_started() -> None:
    harness = Harness(FakeListener(utterance()), FakeStt())

    async def scenario() -> None:
        assert harness.pipeline.activate() is None

    run(scenario)
    assert harness.listener.calls == 0


def test_rejected_voice_is_not_transcribed() -> None:
    harness = Harness(FakeListener(utterance()), FakeStt(), verifier=RejectEveryone())

    async def scenario() -> None:
        await harness.ready()
        turn = harness.pipeline.activate()
        assert turn is not None
        await turn

    run(scenario)
    assert harness.stt.calls == []
