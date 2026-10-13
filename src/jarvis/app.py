"""Composition root: builds the application's components and wires them together.

Like a hand-written Spring context: this is the only place that knows the
concrete implementations. Every phase plugs its components in here.
"""

import asyncio
import logging
import platform
import time
from typing import Any

import anthropic

from jarvis import __version__, paths
from jarvis.activation import HotkeyError, HotkeyListener, parse_hotkey
from jarvis.audio.devices import DeviceNotFoundError, device_name, find_device
from jarvis.audio.listener import MicrophoneListener
from jarvis.audio.player import SoundDevicePlayer
from jarvis.audio.tones import FeedbackSounds
from jarvis.audio.vad import SileroVad
from jarvis.brain import Brain, BudgetGuard, ConversationMemory
from jarvis.brain.claude import ClaudeProvider
from jarvis.brain.digest import NewsDigest
from jarvis.brain.persona import system_prompt
from jarvis.brain.provider import WebSearch
from jarvis.config import AppConfig, ConfigError, TtsConfig, load_config, load_secrets
from jarvis.core.language import LanguagePolicy
from jarvis.core.pipeline import Pipeline
from jarvis.core.runtime import CoreRuntime
from jarvis.core.verification import AcceptEveryone
from jarvis.i18n import Language, Translator
from jarvis.log import setup_logging, shutdown_logging
from jarvis.router import Router
from jarvis.storage import Database, Reminder, ReminderStore, SettingsStore, UsageStore
from jarvis.stt.whisper import WhisperStt
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

log = logging.getLogger(__name__)

WAIT_INTERVAL_S = 0.25


class StartupError(Exception):
    """A problem the user must fix (configuration, devices, hotkey) before JARVIS can run."""


def run() -> int:
    try:
        config = load_config(paths.CONFIG_DIR)
    except ConfigError as exc:
        # Logging is not configured yet, and it depends on this very configuration.
        print(f"JARVIS cannot start: {exc}")
        return 2

    setup_logging(config.logging, paths.PROJECT_ROOT / config.logging.directory)
    try:
        return _run(config)
    except StartupError as exc:
        log.error("JARVIS cannot start: %s", exc)
        return 2
    finally:
        shutdown_logging()


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
    db = Database(paths.DATA_DIR / "jarvis.db")
    policy = LanguagePolicy(SettingsStore(db))
    llm = _build_llm(config, UsageStore(db))
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
        listener=MicrophoneListener(config.vad, SileroVad(), input_device),
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
    )

    runtime = CoreRuntime()
    runtime.start()
    # The hotkey thread never touches the pipeline: it asks the core loop to do it.
    hotkey_listener = HotkeyListener(hotkey, on_press=lambda: runtime.call_soon(pipeline.activate))
    try:
        startup = runtime.submit(_start_up(pipeline, stt, piper, services, db))
        hotkey_listener.start()
        log.info("Press %s to talk. Ctrl+C quits.", config.activation.hotkey.upper())
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


def _build_llm(config: AppConfig, usage: UsageStore) -> tuple[ClaudeProvider, BudgetGuard] | None:
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
    return ClaudeProvider(client, config.brain), BudgetGuard(usage, config.budget)


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
    pipeline: Pipeline, stt: WhisperStt, piper: PiperTts, services: Services, db: Database
) -> None:
    await db.open()
    await services.language.load()
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
