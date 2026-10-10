"""One conversation turn: listen, transcribe, route to a tool, reply.

The rule router picks a tool (ADR-019); tools that change the session ask for a spoken
"yes" first (ADR-025). Requests the rules do not cover get a polite "not yet" until the
LLM arrives in Phase 3.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from jarvis.audio.listener import Listener, Utterance
from jarvis.audio.player import Player
from jarvis.audio.tones import FeedbackSounds
from jarvis.core.state import State
from jarvis.core.verification import SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.log import TRANSCRIPT_LOGGER
from jarvis.router import Router
from jarvis.stt.base import SpeechToText, Transcript
from jarvis.text import Answer, classify_answer
from jarvis.tools.base import Reply, ToolResult
from jarvis.tts.base import TextToSpeech

log = logging.getLogger(__name__)
transcripts = logging.getLogger(TRANSCRIPT_LOGGER)

StateListener = Callable[[State], None]


@dataclass(frozen=True)
class Heard:
    utterance: Utterance
    transcript: Transcript
    stt_s: float


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
        verifier: SpeakerVerifier,
        language: Language,
        silence_ms: int,
        confirmation_timeout_s: float,
    ) -> None:
        self._listener = listener
        self._stt = stt
        self._tts = tts
        self._player = player
        self._sounds = sounds
        self._translator = translator
        self._router = router
        self._verifier = verifier
        self._language = language
        self._silence_s = silence_ms / 1000
        self._confirmation_timeout_s = confirmation_timeout_s
        self._state = State.STARTING
        self._state_listeners: list[StateListener] = []
        self._turn: asyncio.Task[None] | None = None

    @property
    def state(self) -> State:
        return self._state

    @property
    def language(self) -> Language:
        return self._language

    def subscribe(self, listener: StateListener) -> None:
        self._state_listeners.append(listener)

    def start(self) -> asyncio.Task[None]:
        """Models are loaded: become ready and greet."""
        self._set_state(State.IDLE)
        return self._begin(self._speak(Reply("startup.ready")))

    def activate(self) -> asyncio.Task[None] | None:
        """The hotkey was pressed: start a turn (returned), or cancel it while listening."""
        if self._state is State.STARTING:
            log.info("Still starting up; activation ignored")
            return None
        if self._turn is not None and not self._turn.done():
            if self._state is State.LISTENING:
                log.info("Listening cancelled")
                self._turn.cancel()
            else:
                log.info("Busy (%s); activation ignored", self._state)
            return None
        return self._begin(self._conversation_turn())

    def _begin(self, body: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        self._turn = asyncio.create_task(self._guarded(body), name="jarvis-turn")
        return self._turn

    async def _guarded(self, body: Coroutine[Any, Any, None]) -> None:
        """Whatever happens in a turn, JARVIS ends up idle and keeps running."""
        try:
            await body
        except Exception:
            log.exception("Turn failed")
            try:
                await self._speak(Reply("errors.generic"))
            except Exception:
                log.exception("Could not even apologise")
        finally:
            self._set_state(State.IDLE)

    async def _conversation_turn(self) -> None:
        heard = await self._hear()
        if heard is None:
            return
        if not heard.transcript.text:
            await self._speak(Reply("pipeline.not_understood"))
            return
        self._language = heard.transcript.language
        started = time.perf_counter()
        result = await self._handle(heard.transcript.text)
        tool_s = time.perf_counter() - started
        if result.on_confirm is not None:
            await self._speak((await self._confirm(result)).reply)
        else:
            await self._speak(result.reply, heard, tool_s)

    async def _hear(self, no_speech_timeout_s: float | None = None) -> Heard | None:
        """Listen between the start and stop tones and transcribe; None if nothing usable."""
        self._set_state(State.LISTENING)
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

    async def _handle(self, text: str) -> ToolResult:
        route = self._router.route(text)
        if route is None:
            log.info("No rule matched")
            return ToolResult(Reply("router.unknown"))
        log.info("Tool: %s", route.tool.name)
        log.debug("Tool arguments: %r", route.params)
        result = await route.tool.run(route.params)
        if result.details:
            log.info("%s details:\n%s", route.tool.name, result.details)
        return result

    async def _confirm(self, request: ToolResult) -> ToolResult:
        """Ask "Shall I proceed?" and act only on a clear spoken yes (ADR-025)."""
        if request.on_confirm is None:
            return request
        await self._speak(request.reply)
        heard = await self._hear(self._confirmation_timeout_s)
        answer = classify_answer(heard.transcript.text) if heard else Answer.UNCLEAR
        log.info("Confirmation: %s", answer)
        if answer is not Answer.YES:
            return ToolResult(Reply("confirm.cancelled"))
        return await request.on_confirm()

    async def _speak(self, reply: Reply, heard: Heard | None = None, tool_s: float = 0.0) -> None:
        text = self._translator.text(reply.key, self._language, **reply.params)
        started = time.perf_counter()
        clip = await self._tts.synthesize(text, self._language, cacheable=reply.cacheable)
        if heard is not None:
            tts_s = time.perf_counter() - started
            since_end = time.perf_counter() - heard.utterance.ended_at
            log.info(
                "Latency: speech-to-text %.2f s, tool %.2f s, text-to-speech %.2f s; reply "
                "starts %.2f s after the end of speech was detected, %.2f s after you "
                "stopped talking",
                heard.stt_s,
                tool_s,
                tts_s,
                since_end,
                since_end + self._silence_s,
            )
        self._set_state(State.SPEAKING)
        await self._player.play(clip)

    def _set_state(self, state: State) -> None:
        if state is self._state:
            return
        self._state = state
        log.debug("State: %s", state)
        for listener in self._state_listeners:
            listener(state)
