"""One conversation turn: listen, transcribe, reply.

In Phase 1 the reply repeats what was heard, in the language it was said in; later
phases put the router and the tools between transcription and reply.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from jarvis.audio.listener import Listener
from jarvis.audio.player import Player
from jarvis.audio.tones import FeedbackSounds
from jarvis.core.state import State
from jarvis.core.verification import SpeakerVerifier
from jarvis.i18n import Language, Translator
from jarvis.log import TRANSCRIPT_LOGGER
from jarvis.stt.base import SpeechToText
from jarvis.tts.base import TextToSpeech

log = logging.getLogger(__name__)
transcripts = logging.getLogger(TRANSCRIPT_LOGGER)

StateListener = Callable[[State], None]


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
        verifier: SpeakerVerifier,
        language: Language,
        silence_ms: int,
    ) -> None:
        self._listener = listener
        self._stt = stt
        self._tts = tts
        self._player = player
        self._sounds = sounds
        self._translator = translator
        self._verifier = verifier
        self._language = language
        self._silence_s = silence_ms / 1000
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
        return self._begin(self._greet())

    def activate(self) -> asyncio.Task[None] | None:
        """The hotkey was pressed: start a turn (returned), or cancel it while still listening."""
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
                await self._say(self._translator.text("errors.generic", self._language))
            except Exception:
                log.exception("Could not even apologise")
        finally:
            self._set_state(State.IDLE)

    async def _greet(self) -> None:
        await self._say(self._translator.text("startup.ready", self._language))

    async def _conversation_turn(self) -> None:
        self._set_state(State.LISTENING)
        await self._player.play(self._sounds.start)
        utterance = await self._listener.listen()
        # The "got it" tone plays while Whisper works, so it costs no time.
        stop_tone = asyncio.create_task(self._player.play(self._sounds.stop))
        try:
            if utterance is None:
                log.info("No speech detected")
                return
            if not await self._verifier.is_owner(utterance.audio):
                log.info("Voice not recognised as the owner's; ignored")
                return
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
        if not transcript.text:
            await self._say(self._translator.text("pipeline.not_understood", self._language))
            return

        self._language = transcript.language
        reply = self._translator.text("pipeline.heard", self._language, text=transcript.text)
        started = time.perf_counter()
        # The reply contains what the user said, so it must not be cached on disk.
        clip = await self._tts.synthesize(reply, self._language, cacheable=False)
        tts_s = time.perf_counter() - started
        since_end = time.perf_counter() - utterance.ended_at
        log.info(
            "Latency: speech-to-text %.2f s, text-to-speech %.2f s; reply starts %.2f s after "
            "the end of speech was detected, %.2f s after you stopped talking",
            stt_s,
            tts_s,
            since_end,
            since_end + self._silence_s,
        )
        self._set_state(State.SPEAKING)
        await self._player.play(clip)

    async def _say(self, text: str) -> None:
        """Speak a fixed phrase from the locale files (safe to cache)."""
        clip = await self._tts.synthesize(text, self._language, cacheable=True)
        self._set_state(State.SPEAKING)
        await self._player.play(clip)

    def _set_state(self, state: State) -> None:
        if state is self._state:
            return
        self._state = state
        log.debug("State: %s", state)
        for listener in self._state_listeners:
            listener(state)
