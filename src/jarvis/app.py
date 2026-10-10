"""Composition root: builds the application's components and wires them together.

Like a hand-written Spring context: this is the only place that knows the
concrete implementations. Every phase plugs its components in here.
"""

import asyncio
import logging
import platform
import time

from jarvis import __version__, paths
from jarvis.activation import HotkeyError, HotkeyListener, parse_hotkey
from jarvis.audio.devices import DeviceNotFoundError, device_name, find_device
from jarvis.audio.listener import MicrophoneListener
from jarvis.audio.player import SoundDevicePlayer
from jarvis.audio.tones import FeedbackSounds
from jarvis.audio.vad import SileroVad
from jarvis.config import AppConfig, ConfigError, TtsConfig, load_config
from jarvis.core.pipeline import Pipeline
from jarvis.core.runtime import CoreRuntime
from jarvis.core.verification import AcceptEveryone
from jarvis.i18n import Language, Translator
from jarvis.log import setup_logging, shutdown_logging
from jarvis.router import Router
from jarvis.stt.whisper import WhisperStt
from jarvis.tools import AppIndex, build_tools
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
    app_index = AppIndex(config.apps.match_threshold, config.apps.refresh_minutes * 60)
    tools = build_tools(config, app_index)
    log.info("Tools: %s", ", ".join(tool.name for tool in tools))
    pipeline = Pipeline(
        listener=MicrophoneListener(config.vad, SileroVad(), input_device),
        stt=stt,
        tts=_build_tts(config.tts, piper),
        player=SoundDevicePlayer(output_device),
        sounds=FeedbackSounds.create(config.audio.feedback_volume),
        translator=Translator.load(),
        router=Router(tools),
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
        startup = runtime.submit(_start_up(pipeline, stt, piper, app_index))
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


async def _start_up(
    pipeline: Pipeline, stt: WhisperStt, piper: PiperTts, app_index: AppIndex
) -> None:
    log.info("Loading the speech model (the first run downloads it)...")
    # The Start menu index loads meanwhile; "open X" would reload it on demand anyway.
    index_task = asyncio.create_task(app_index.refresh())
    await asyncio.to_thread(stt.load)
    try:
        await asyncio.to_thread(piper.prepare)
    except Exception as exc:  # JARVIS still works online without the offline voice
        log.warning("Offline voice unavailable: %s", exc)
    try:
        await index_task
    except Exception as exc:
        log.warning("Could not read the Start menu yet: %s", exc)
    await pipeline.start()


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
