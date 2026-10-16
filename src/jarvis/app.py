"""Composition root: builds the application's components and wires them together.

Like a hand-written Spring context: this is the only place that knows the
concrete implementations. Every phase plugs its components in here.
"""

import asyncio
import logging
import platform
import time
from collections.abc import Callable, Coroutine
from typing import Any

import anthropic

from jarvis import __version__, paths
from jarvis.activation import HotkeyError, HotkeyListener, parse_hotkey
from jarvis.audio.clip import Samples
from jarvis.audio.devices import DeviceNotFoundError, device_name, find_device
from jarvis.audio.listener import MicrophoneListener
from jarvis.audio.microphone import Microphone
from jarvis.audio.player import SoundDevicePlayer
from jarvis.audio.tones import FeedbackSounds
from jarvis.audio.vad import SileroVad
from jarvis.audio.wake import OpenWakeWord, WakeWatcher
from jarvis.brain import Brain, BudgetGuard, ConversationMemory
from jarvis.brain.claude import ClaudeProvider
from jarvis.brain.digest import NewsDigest
from jarvis.brain.persona import system_prompt
from jarvis.brain.provider import WebSearch
from jarvis.config import AppConfig, ConfigError, TtsConfig, load_config, load_secrets
from jarvis.core.events import SpendingChanged
from jarvis.core.language import LanguagePolicy
from jarvis.core.pipeline import Pipeline
from jarvis.core.runtime import CoreRuntime
from jarvis.core.state import State
from jarvis.core.verification import AcceptEveryone
from jarvis.hud import Hud, watch_load
from jarvis.i18n import Language, Translator
from jarvis.log import setup_logging, shutdown_logging
from jarvis.router import Router
from jarvis.storage import Database, Reminder, ReminderStore, SettingsStore, UsageStore
from jarvis.stt.whisper import WhisperStt
from jarvis.text import mentions_wake_word
from jarvis.tools import (
    AppIndex,
    FileIndex,
    NewsService,
    Reply,
    ResultList,
    Services,
    Tool,
    WeatherClient,
    build_tools,
)
from jarvis.tools.files import expand_folders
from jarvis.tools.reminders import ReminderService
from jarvis.tts.base import TextToSpeech
from jarvis.tts.cache import CachedTts
from jarvis.tts.edge import EdgeTts
from jarvis.tts.fallback import FallbackTts
from jarvis.tts.piper import PiperTts
from jarvis.windows.process import claim_single_instance, is_windowless, show_error

log = logging.getLogger(__name__)

WAIT_INTERVAL_S = 0.25


class StartupError(Exception):
    """A problem the user must fix (configuration, devices, hotkey) before JARVIS can run."""


def run() -> int:
    try:
        config = load_config(paths.CONFIG_DIR)
    except ConfigError as exc:
        # Logging is not configured yet, and it depends on this very configuration.
        _cannot_start(str(exc))
        return 2

    setup_logging(config.logging, paths.PROJECT_ROOT / config.logging.directory)
    try:
        if not claim_single_instance():
            raise StartupError("JARVIS is already running: look for the reactor in the tray")
        return _run(config)
    except StartupError as exc:
        log.error("JARVIS cannot start: %s", exc)
        _cannot_start(str(exc))
        return 2
    finally:
        shutdown_logging()


def _cannot_start(reason: str) -> None:
    print(f"JARVIS cannot start: {reason}")
    if is_windowless():  # started with Windows (ADR-044): nobody sees a console
        show_error(f"JARVIS cannot start:\n{reason}")


def _run(config: AppConfig) -> int:
    log.info("JARVIS %s starting on Python %s", __version__, platform.python_version())
    try:
        hotkey = parse_hotkey(config.activation.hotkey)
        input_device = find_device(config.audio.input_device, "input")
        output_device = find_device(config.audio.output_device, "output")
    except (HotkeyError, DeviceNotFoundError) as exc:
        raise StartupError(str(exc)) from exc
    log.info("Microphone: %s", device_name(input_device, "input"))
    log.info("Audio output: %s", device_name(output_device, "output"))

    stt = WhisperStt(config.stt)
    piper = PiperTts(
        {Language.EN: config.tts.piper_voice_en, Language.PT: config.tts.piper_voice_pt},
        paths.DATA_DIR / "voices",
    )
    translator = Translator.load()
    microphone = Microphone(
        lambda: find_device(config.audio.input_device, "input"),  # again after a replug
        history_s=max(config.wake.backlog_s, config.wake.confirm_s) + 1,
    )
    # Qt must start on the main thread, before anything posts to the HUD (ADR-004).
    hud = (
        Hud(
            config.hud,
            translator,
            config.language.default,
            config.budget.stop_usd,
            paths.DATA_DIR / "hud.ini",
        )
        if config.hud.enabled
        else None
    )
    db = Database(paths.DATA_DIR / "jarvis.db")
    policy = LanguagePolicy(SettingsStore(db))
    on_spending = (lambda spent: hud.post(SpendingChanged(spent))) if hud else None
    llm = _build_llm(config, UsageStore(db), on_spending)
    services = Services(
        app_index=AppIndex(config.apps.match_threshold, config.apps.refresh_minutes * 60),
        file_index=FileIndex(
            expand_folders(config.files.folders),
            config.files.skip_dirs,
            config.files.refresh_minutes * 60,
        ),
        results=ResultList(),
        weather=WeatherClient(),
        reminders=ReminderService(ReminderStore(db)),
        news=NewsService(config.news, NewsDigest(*llm, config.user) if llm else None),
        language=policy,
        reply_language=lambda: pipeline.reply_language,
    )
    tools = build_tools(config, services)
    log.info("Tools: %s", ", ".join(tool.name for tool in tools))
    memory = ConversationMemory(config.brain.memory_turns, config.brain.memory_minutes * 60)
    pipeline = Pipeline(
        listener=MicrophoneListener(config.vad, SileroVad(), microphone),
        stt=stt,
        tts=_build_tts(config.tts, piper),
        player=SoundDevicePlayer(output_device),
        sounds=FeedbackSounds.create(config.audio.feedback_volume),
        translator=translator,
        router=Router(tools),
        brain=_build_brain(config, llm, tools, memory, translator) if llm else None,
        memory=memory,
        policy=policy,
        verifier=AcceptEveryone(),
        language=config.language.default,
        silence_ms=config.vad.silence_ms,
        confirmation_timeout_s=config.confirmation.timeout_s,
        wake_backlog_s=config.wake.backlog_s,
    )
    if hud is not None:
        pipeline.subscribe(hud.post)

    runtime = CoreRuntime()
    runtime.start()
    background = [microphone.keep_alive(), services.news.keep_fresh()]
    if config.wake.enabled:
        background.append(_wake_watcher(config, microphone, stt, pipeline).run())
    if hud is not None:
        background.append(watch_load(hud.post, config.hud.load_seconds))
    # The hotkey thread never touches the pipeline: it asks the core loop to do it.
    hotkey_listener = HotkeyListener(hotkey, on_press=lambda: runtime.call_soon(pipeline.activate))
    try:
        startup = runtime.submit(
            _start_up(pipeline, stt, piper, services, db, llm[1] if llm else None)
        )
        hotkey_listener.start()
        for task in background:
            runtime.submit(_logged(task))
        log.info("Press %s to talk. Ctrl+C quits.", config.activation.hotkey.upper())
        if hud is not None:
            code = hud.run(startup)
            log.info("Shutting down. Goodbye, sir.")
            return code
        while True:
            if startup.done() and startup.exception() is not None:
                log.error("Start-up failed: %s", startup.exception())
                return 1
            time.sleep(WAIT_INTERVAL_S)
    except HotkeyError as exc:
        raise StartupError(str(exc)) from exc
    except KeyboardInterrupt:
        log.info("Shutting down. Goodbye, sir.")
        return 0
    finally:
        hotkey_listener.stop()
        runtime.stop()
        db.close()


def _wake_watcher(
    config: AppConfig, microphone: Microphone, stt: WhisperStt, pipeline: Pipeline
) -> WakeWatcher:
    async def says_jarvis(audio: Samples) -> bool:
        transcript = await stt.transcribe(audio, pipeline.language)
        log.debug("Wake word check heard: %r", transcript.text)
        return mentions_wake_word(transcript.text)

    return WakeWatcher(
        microphone,
        lambda: OpenWakeWord(config.wake.model),
        config.wake,
        confirm=says_jarvis,
        on_wake=pipeline.wake,
        armed=lambda: pipeline.state in (State.IDLE, State.SPEAKING),
    )


async def _logged(job: Coroutine[Any, Any, None]) -> None:
    """Background jobs log their failure instead of vanishing with it."""
    try:
        await job
    except Exception:
        log.exception("A background job stopped")


def _build_llm(
    config: AppConfig, usage: UsageStore, on_spending: Callable[[float], None] | None = None
) -> tuple[ClaudeProvider, BudgetGuard] | None:
    """Claude and its spending guard, or None without an API key (rules only)."""
    secrets = load_secrets(paths.ENV_FILE)
    if secrets.anthropic_api_key is None:
        log.warning("ANTHROPIC_API_KEY is not set: only the local rules will answer")
        return None
    client = anthropic.AsyncAnthropic(
        api_key=secrets.anthropic_api_key.get_secret_value(),
        timeout=config.brain.request_timeout_s,
        max_retries=1,
    )
    log.info("LLM: %s (effort %s)", config.brain.model, config.brain.effort)
    budget = BudgetGuard(usage, config.budget, on_change=on_spending)
    return ClaudeProvider(client, config.brain), budget


def _build_brain(
    config: AppConfig,
    llm: tuple[ClaudeProvider, BudgetGuard],
    tools: list[Tool[Any]],
    memory: ConversationMemory,
    translator: Translator,
) -> Brain:
    provider, budget = llm
    web_search = None
    if config.search.enabled and config.search.daily_limit > 0:
        place = config.weather
        web_search = WebSearch(
            config.search.max_per_question,
            place.city,
            place.region,
            place.country_code,
            place.timezone,
        )
        log.info("Web search: up to %d searches a day", config.search.daily_limit)
    return Brain(
        provider=provider,
        tools=tools,
        budget=budget,
        memory=memory,
        translator=translator,
        system=system_prompt(config.user, config.weather, web_search is not None),
        max_tool_rounds=config.brain.max_tool_rounds,
        web_search=web_search,
        daily_searches=config.search.daily_limit,
    )


async def _start_up(
    pipeline: Pipeline,
    stt: WhisperStt,
    piper: PiperTts,
    services: Services,
    db: Database,
    budget: BudgetGuard | None,
) -> None:
    await db.open()
    await services.language.load()
    if budget is not None:
        await budget.status()  # shows the spending on the HUD
    log.info("Loading the speech model (the first run downloads it)...")
    # The indexes load meanwhile; a search would also reload them on demand.
    indexes = [
        asyncio.create_task(services.app_index.refresh()),
        asyncio.create_task(services.file_index.refresh()),
    ]
    await asyncio.to_thread(stt.load)
    try:
        await asyncio.to_thread(piper.prepare)
    except Exception as exc:  # JARVIS still works online without the offline voice
        log.warning("Offline voice unavailable: %s", exc)
    for outcome in await asyncio.gather(*indexes, return_exceptions=True):
        if isinstance(outcome, Exception):
            log.warning("An index could not be built yet: %s", outcome)
    await pipeline.start()

    def announce(reminder: Reminder, overdue: bool) -> None:
        key = "reminders.overdue" if overdue else "reminders.due"
        pipeline.announce(Reply(key, {"text": reminder.text}, cacheable=False), reminder.language)

    await services.reminders.start(announce)


def _build_tts(config: TtsConfig, offline: TextToSpeech) -> TextToSpeech:
    edge = EdgeTts(
        {Language.EN: config.edge_voice_en, Language.PT: config.edge_voice_pt},
        config.first_audio_timeout_s,
    )
    online: TextToSpeech = (
        CachedTts(edge, paths.DATA_DIR / "tts-cache", config.cache_max_mb * 1024 * 1024)
        if config.cache
        else edge
    )
    return FallbackTts(online, offline, config.retry_online_after_s)
