"""One conversation turn: listen, transcribe, route to a tool or to the brain, reply.

The rule router answers fixed commands locally (ADR-019); anything else goes to the LLM with
the tools (ADR-026). Tools that change the session ask for a spoken "yes" first (ADR-025).
Every exchange goes into the short-term memory (ADR-028), and unprompted announcements (due
reminders) wait until no turn is running. A turn starts with the hotkey or the wake word
(ADR-040); either one, while JARVIS speaks, cuts him short and listens (ADR-041). Replies are
spoken sentence by sentence, the next one synthesised while the current one plays (ADR-042).
"""

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.audio.clip import AudioClip
from jarvis.audio.listener import Listener, MicrophoneError, Utterance
from jarvis.audio.player import Player
from jarvis.audio.tones import FeedbackSounds
from jarvis.brain import Brain, ConversationMemory
from jarvis.core.events import (
    Event,
    EventSink,
    JarvisSpoke,
    Shown,
    StateChanged,
    UserSpoke,
)
from jarvis.core.language import LanguagePolicy
from jarvis.core.state import State
from jarvis.core.verification import SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.log import TRANSCRIPT_LOGGER
from jarvis.router import Router
from jarvis.stt.base import SpeechToText, Transcript
from jarvis.text import Answer, after_wake_word, classify_answer
from jarvis.text.sentences import speech_chunks
from jarvis.text.when import part_of_day
from jarvis.tools.base import Reply, ToolResult, render
from jarvis.tts.base import TextToSpeech

log = logging.getLogger(__name__)
transcripts = logging.getLogger(TRANSCRIPT_LOGGER)


def greeting_key(hour: int) -> str:
    return f"startup.{part_of_day(hour)}"


@dataclass(frozen=True)
class Heard:
    utterance: Utterance
    transcript: Transcript
    stt_s: float


@dataclass(frozen=True)
class Outcome:
    results: tuple[ToolResult, ...]  # spoken in order
    budget_warning: bool = False


class Pipeline:
    """Lives on the core event loop; other threads reach it through CoreRuntime.call_soon."""

    def __init__(
        self,
        *,
        listener: Listener,
        stt: SpeechToText,
        tts: TextToSpeech,
        player: Player,
        sounds: FeedbackSounds,
        translator: Translator,
        router: Router,
        brain: Brain | None,
        memory: ConversationMemory,
        policy: LanguagePolicy,
        verifier: SpeakerVerifier,
        language: Language,
        silence_ms: int,
        confirmation_timeout_s: float,
        wake_backlog_s: float = 0.0,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._listener = listener
        self._stt = stt
        self._tts = tts
        self._player = player
        self._sounds = sounds
        self._translator = translator
        self._router = router
        self._brain = brain
        self._memory = memory
        self._policy = policy
        self._verifier = verifier
        self._language = language  # the language last spoken by the user
        self._silence_s = silence_ms / 1000
        self._confirmation_timeout_s = confirmation_timeout_s
        self._wake_backlog_s = wake_backlog_s
        self._clock = clock
        self._state = State.STARTING
        self._listeners: list[EventSink] = []
        self._turn: asyncio.Task[None] | None = None
        self._announcements: deque[tuple[Reply, Language]] = deque()

    @property
    def state(self) -> State:
        return self._state

    @property
    def language(self) -> Language:
        return self._language

    @property
    def reply_language(self) -> Language:
        return self._policy.reply_language(self._language)

    def subscribe(self, listener: EventSink) -> None:
        """Receive every event (state, what was heard and said...) on the core thread."""
        self._listeners.append(listener)

    def start(self) -> asyncio.Task[None]:
        """Models are loaded: become ready and greet according to the time of day."""
        self._set_state(State.IDLE)
        return self._begin(self._speak(Reply(greeting_key(self._clock().hour))))

    def activate(self) -> asyncio.Task[None] | None:
        """The hotkey was pressed: start a turn (returned), cancel it while listening, or
        interrupt the speech and listen."""
        if self._state is State.STARTING:
            log.info("Still starting up; activation ignored")
            return None
        turn = self._turn
        if turn is not None and not turn.done():
            if self._state is State.SPEAKING:
                return self._interrupt(turn)
            if self._state is State.LISTENING:
                log.info("Listening cancelled")
                turn.cancel()
            else:
                log.info("Busy (%s); activation ignored", self._state)
            return None
        return self._begin(self._conversation_turn())

    def wake(self) -> asyncio.Task[None] | None:
        """The wake word was heard: listen, keeping the audio from just before, since the
        request may follow in the same breath; or interrupt the speech."""
        turn = self._turn
        if self._state is State.SPEAKING and turn is not None and not turn.done():
            return self._interrupt(turn, self._wake_backlog_s)
        if self._state is not State.IDLE or self._busy():
            return None
        return self._begin(self._conversation_turn(self._wake_backlog_s))

    def _interrupt(self, turn: asyncio.Task[None], backlog_s: float = 0.0) -> asyncio.Task[None]:
        log.info("Interrupted while speaking")
        turn.cancel()

        async def listen_next() -> None:
            with contextlib.suppress(asyncio.CancelledError):
                await turn
            await self._conversation_turn(backlog_s)

        return self._begin(listen_next())

    def announce(self, reply: Reply, language: Language) -> None:
        """Say something unprompted (a due reminder) as soon as no turn is running."""
        self._announcements.append((reply, language))
        self._announce_when_free()

    def _busy(self) -> bool:
        return self._turn is not None and not self._turn.done()

    def _announce_when_free(self) -> None:
        if self._announcements and self._state is not State.STARTING and not self._busy():
            self._begin(self._announce_pending())

    async def _announce_pending(self) -> None:
        while self._announcements:
            reply, language = self._announcements.popleft()
            await self._speak(reply, language=language)

    def _begin(self, body: Coroutine[Any, Any, Any]) -> asyncio.Task[None]:
        self._turn = asyncio.create_task(self._guarded(body), name="jarvis-turn")
        return self._turn

    async def _guarded(self, body: Coroutine[Any, Any, Any]) -> None:
        """Whatever happens in a turn, JARVIS ends up idle and keeps running."""
        try:
            await body
        except Exception as exc:
            key = "errors.microphone" if isinstance(exc, MicrophoneError) else "errors.generic"
            log.exception("Turn failed")
            try:
                await self._speak(Reply(key))
            except Exception:
                log.exception("Could not even apologise")
        finally:
            self._set_state(State.IDLE)
            if self._announcements:
                # Runs once this task has finished, so the next one can start.
                asyncio.get_running_loop().call_soon(self._announce_when_free)

    async def _conversation_turn(self, backlog_s: float = 0.0) -> None:
        """``backlog_s`` > 0: woken by voice, and the audio may start with "Ei Jarvis"."""
        heard = await self._hear(backlog_s=backlog_s)
        if heard is None:
            return
        said = heard.transcript.text
        if backlog_s:
            said = after_wake_word(said)
            if not said:  # only "Ei Jarvis": now the request itself
                heard = await self._hear()
                if heard is None:
                    return
                said = heard.transcript.text
        if not said:
            await self._speak(Reply("pipeline.not_understood"))
            return
        self._language = heard.transcript.language
        self._emit(UserSpoke(said, self.reply_language))
        started = time.perf_counter()
        outcome = await self._handle(said)
        tool_s = time.perf_counter() - started
        self._show(outcome.results)
        spoken: list[str] = []
        try:
            for index, result in enumerate(outcome.results):
                if result.on_confirm is not None:
                    spoken.append(await self._speak(result.reply))
                    spoken.append(await self._speak((await self._confirm(result)).reply))
                else:
                    timed = heard if index == 0 else None
                    spoken.append(await self._speak(result.reply, timed, tool_s))
            if outcome.budget_warning:
                spoken.append(await self._speak(Reply("brain.budget_warning")))
        finally:  # an interrupted reply is remembered too, as far as it went
            self._memory.add(said, " ".join(spoken))

    async def _hear(
        self, no_speech_timeout_s: float | None = None, backlog_s: float = 0.0
    ) -> Heard | None:
        """Listen between the start and stop tones and transcribe; None if nothing usable."""
        self._set_state(State.LISTENING)
        if backlog_s:
            # Woken by voice, the request may already be under way: every frame counts, so
            # the start tone plays while listening instead of before.
            start_tone = asyncio.create_task(self._player.play(self._sounds.start))
            try:
                utterance = await self._listener.listen(no_speech_timeout_s, backlog_s)
            finally:
                start_tone.cancel()
        else:
            await self._player.play(self._sounds.start)
            utterance = await self._listener.listen(no_speech_timeout_s)
        # The "got it" tone plays while Whisper works, so it costs no time.
        stop_tone = asyncio.create_task(self._player.play(self._sounds.stop))
        try:
            if utterance is None:
                log.info("No speech detected")
                return None
            if not await self._verifier.is_owner(utterance.audio):
                log.info("Voice not recognised as the owner's; ignored")
                return None
            self._set_state(State.THINKING)
            started = time.perf_counter()
            transcript = await self._stt.transcribe(utterance.audio, self._language)
            stt_s = time.perf_counter() - started
        finally:
            await stop_tone
        # The text goes only to the transcript log, which can be switched off.
        transcripts.info("[%s] %s", transcript.language, transcript.text)
        log.info(
            "Heard %.1f s of speech in %s (language confidence %.2f)",
            utterance.duration_s,
            transcript.language,
            transcript.language_confidence,
        )
        return Heard(utterance, transcript, stt_s)

    async def _handle(self, said: str) -> Outcome:
        route = self._router.route(said)
        if route is not None:
            log.info("Tool: %s", route.tool.name)
            log.debug("Tool arguments: %r", route.params)
            result = await route.tool.run(route.params)
            if result.details:
                log.info("%s details:\n%s", route.tool.name, result.details)
            return Outcome((result,))
        if self._brain is None:
            log.info("No rule matched and no LLM is configured")
            return Outcome((ToolResult(Reply("brain.not_configured")),))
        log.info("No rule matched: asking the LLM")
        answer = await self._brain.answer(said, self.reply_language)
        return Outcome(answer.results, answer.budget_warning)

    async def _confirm(self, request: ToolResult) -> ToolResult:
        """After "Shall I proceed?", act only on a clear spoken yes (ADR-025)."""
        if request.on_confirm is None:
            return request
        heard = await self._hear(self._confirmation_timeout_s)
        if heard is not None and heard.transcript.text:
            self._emit(UserSpoke(heard.transcript.text, self.reply_language))
        answer = classify_answer(heard.transcript.text) if heard else Answer.UNCLEAR
        log.info("Confirmation: %s", answer)
        if answer is not Answer.YES:
            return ToolResult(Reply("confirm.cancelled"))
        return await request.on_confirm()

    async def _speak(
        self,
        reply: Reply,
        heard: Heard | None = None,
        tool_s: float = 0.0,
        language: Language | None = None,
    ) -> str:
        """Say a reply, sentence by sentence; returns the text spoken."""
        language = language or self.reply_language
        text = render(reply, self._translator, language)
        chunks = speech_chunks(text) or [text]
        started = time.perf_counter()
        next_clip = self._synthesize(chunks[0], language, reply.cacheable)
        try:
            for index in range(len(chunks)):
                clip = await next_clip
                if index + 1 < len(chunks):  # synthesised while this one plays
                    next_clip = self._synthesize(chunks[index + 1], language, reply.cacheable)
                if index == 0:
                    if heard is not None:
                        self._log_latency(heard, tool_s, time.perf_counter() - started)
                    self._set_state(State.SPEAKING)
                    self._emit(JarvisSpoke(text, language))
                await self._player.play(clip)
        finally:
            next_clip.cancel()  # nothing left synthesising after an interruption
        return text

    def _synthesize(
        self, text: str, language: Language, cacheable: bool
    ) -> asyncio.Task[AudioClip]:
        return asyncio.create_task(self._tts.synthesize(text, language, cacheable=cacheable))

    def _log_latency(self, heard: Heard, tool_s: float, tts_s: float) -> None:
        since_end = time.perf_counter() - heard.utterance.ended_at
        log.info(
            "Latency: speech-to-text %.2f s, rules/LLM %.2f s, text-to-speech %.2f s; reply "
            "starts %.2f s after the end of speech was detected, %.2f s after you "
            "stopped talking",
            heard.stt_s,
            tool_s,
            tts_s,
            since_end,
            since_end + self._silence_s,
        )

    def _show(self, results: tuple[ToolResult, ...]) -> None:
        details = "\n\n".join(result.details for result in results if result.details)
        links = tuple(link for result in results for link in result.links)
        if details or links:
            self._emit(Shown(details or None, links))

    def _set_state(self, state: State) -> None:
        if state is self._state:
            return
        self._state = state
        log.debug("State: %s", state)
        self._emit(StateChanged(state))

    def _emit(self, event: Event) -> None:
        for listener in self._listeners:
            listener(event)
