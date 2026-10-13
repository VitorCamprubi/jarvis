"""Environment checks, run with `uv run jarvis --check`.

Each phase adds the checks it needs. A FAIL makes the command exit with a non-zero code.
"""

import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import sounddevice as sd

from jarvis import paths
from jarvis.activation import HotkeyError, parse_hotkey
from jarvis.audio.devices import DeviceNotFoundError, Kind, device_name, find_device, list_devices
from jarvis.config import ConfigError, load_config, load_secrets
from jarvis.stt.cuda import missing_dlls, register_nvidia_dlls

MIN_PYTHON = (3, 14)
NVIDIA_SMI_TIMEOUT_S = 10


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str


def check_python(version: tuple[int, ...] = sys.version_info[:2]) -> CheckResult:
    found = ".".join(map(str, version))
    if version >= MIN_PYTHON:
        return CheckResult("Python", Status.OK, f"Python {found}")
    required = ".".join(map(str, MIN_PYTHON))
    return CheckResult("Python", Status.FAIL, f"Python {found} found, {required}+ required")


def check_gpu(run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> CheckResult:
    """Query the NVIDIA driver; speech recognition runs on the GPU."""
    query = "--query-gpu=name,driver_version,memory.total,memory.used"
    try:
        result = run(
            ["nvidia-smi", query, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT_S,
            check=True,
        )
    except FileNotFoundError:
        return CheckResult("GPU", Status.FAIL, "nvidia-smi not found: install the NVIDIA driver")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return CheckResult("GPU", Status.FAIL, f"nvidia-smi failed: {exc}")

    try:
        first_gpu = result.stdout.strip().splitlines()[0]
        name, driver, total_mib, used_mib = (part.strip() for part in first_gpu.split(","))
        free_gb = (int(total_mib) - int(used_mib)) / 1024
        total_gb = int(total_mib) / 1024
    except IndexError, ValueError:
        return CheckResult("GPU", Status.WARN, f"unexpected nvidia-smi output: {result.stdout!r}")
    return CheckResult(
        "GPU",
        Status.OK,
        f"{name}, driver {driver}, VRAM {free_gb:.1f} GB free of {total_gb:.1f} GB",
    )


def check_cuda(register: Callable[[], list[Path]] = register_nvidia_dlls) -> CheckResult:
    """cuBLAS and cuDNN from NVIDIA's pip wheels, as CTranslate2 needs them (ADR-014)."""
    dirs = register()
    if not dirs:
        return CheckResult("CUDA", Status.FAIL, "NVIDIA libraries not installed: run `uv sync`")
    missing = missing_dlls(dirs)
    if missing:
        return CheckResult("CUDA", Status.FAIL, f"missing {', '.join(missing)}: run `uv sync`")
    try:
        import ctranslate2

        gpus = ctranslate2.get_cuda_device_count()
    except Exception as exc:
        return CheckResult("CUDA", Status.FAIL, f"CTranslate2 cannot use CUDA: {exc}")
    if gpus == 0:
        return CheckResult("CUDA", Status.FAIL, "CTranslate2 sees no CUDA GPU")
    return CheckResult("CUDA", Status.OK, f"cuBLAS and cuDNN found; {gpus} GPU(s) usable")


def check_config(config_dir: Path = paths.CONFIG_DIR) -> CheckResult:
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        return CheckResult("Config", Status.FAIL, str(exc))
    weather = config.weather
    return CheckResult(
        "Config", Status.OK, f"valid; weather default: {weather.city}, {weather.region}"
    )


def check_hotkey(text: str) -> CheckResult:
    try:
        parse_hotkey(text)
    except HotkeyError as exc:
        return CheckResult("Hotkey", Status.FAIL, str(exc))
    return CheckResult("Hotkey", Status.OK, f"{text.upper()} (conflicts show up when JARVIS runs)")


def check_audio_device(query: str, kind: Kind) -> CheckResult:
    label = "Microphone" if kind == "input" else "Audio out"
    try:
        name = device_name(find_device(query, kind), kind)
    except (DeviceNotFoundError, sd.PortAudioError, ValueError) as exc:
        return CheckResult(label, Status.FAIL, str(exc))
    return CheckResult(label, Status.OK, name + ("" if query else " (Windows default)"))


def check_llm(
    env_file: Path = paths.ENV_FILE,
    model: str = "claude-haiku-5-5",
    client_factory: Callable[[str], Any] | None = None,
) -> CheckResult:
    """Validate the API key with a free model lookup (no tokens are spent)."""
    key = load_secrets(env_file).anthropic_api_key
    if key is None:
        return CheckResult(
            "LLM", Status.WARN, "ANTHROPIC_API_KEY not set in .env: only local rules will answer"
        )
    import anthropic

    factory = client_factory or (
        lambda api_key: anthropic.Anthropic(api_key=api_key, timeout=10, max_retries=0)
    )
    try:
        factory(key.get_secret_value()).models.retrieve(model)
    except anthropic.AuthenticationError:
        return CheckResult("LLM", Status.FAIL, "the API key was rejected: create a new one")
    except anthropic.NotFoundError:
        return CheckResult("LLM", Status.FAIL, f"model {model} is not available to this key")
    except anthropic.BadRequestError as exc:
        if "anthropic-workspace-id" in str(exc):
            return CheckResult(
                "LLM", Status.FAIL, "the key is not tied to a workspace: create it in 'jarvis'"
            )
        return CheckResult("LLM", Status.FAIL, f"the API refused the request: {exc}")
    except anthropic.APIConnectionError:
        return CheckResult("LLM", Status.WARN, "could not reach the Anthropic API (offline?)")
    except anthropic.APIStatusError as exc:
        return CheckResult("LLM", Status.FAIL, f"the API answered {exc.status_code}")
    return CheckResult("LLM", Status.OK, f"API key valid; {model} available")


def check_spending(
    db_file: Path = paths.DATA_DIR / "jarvis.db",
    stop_usd: float = 0.0,
    daily_searches: int = 0,
    now: datetime | None = None,
) -> CheckResult:
    """What the LLM has cost so far, by JARVIS's own estimate (ADR-010), and today's web
    searches against the daily limit (ADR-034)."""
    if not db_file.exists():
        return CheckResult("Spending", Status.OK, "no LLM usage yet")
    try:
        with closing(sqlite3.connect(db_file)) as connection:
            spent = connection.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_usage"
            ).fetchone()[0]
            searches = _searches_today(connection, now or datetime.now().astimezone())
    except sqlite3.Error:
        return CheckResult("Spending", Status.OK, "no LLM usage yet")
    status = Status.WARN if stop_usd and spent >= stop_usd else Status.OK
    detail = f"US$ {spent:.4f} so far (estimate; stops at {stop_usd:.2f})"
    if daily_searches:
        detail += f"; {searches} of {daily_searches} web searches today"
    return CheckResult("Spending", status, detail)


def _searches_today(connection: sqlite3.Connection, now: datetime) -> int:
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    try:
        row = connection.execute(
            "SELECT COALESCE(SUM(web_searches), 0) FROM llm_usage WHERE at >= ?",
            (midnight.isoformat(),),
        ).fetchone()
    except sqlite3.OperationalError:  # a database from before web search (migration 2)
        return 0
    return int(row[0])


def run_checks() -> int:
    results = [check_python(), check_gpu(), check_cuda(), check_config()]
    try:
        config = load_config(paths.CONFIG_DIR)
    except ConfigError:
        config = None  # already reported by check_config
    if config is not None:
        results += [
            check_hotkey(config.activation.hotkey),
            check_audio_device(config.audio.input_device, "input"),
            check_audio_device(config.audio.output_device, "output"),
        ]
        results += [
            check_llm(model=config.brain.model),
            check_spending(
                stop_usd=config.budget.stop_usd,
                daily_searches=config.search.daily_limit if config.search.enabled else 0,
            ),
        ]
    else:
        results.append(check_llm())

    width = max(len(result.name) for result in results)
    for result in results:
        print(f"[{result.status:<4}] {result.name:<{width}}  {result.detail}")
    failed = any(result.status is Status.FAIL for result in results)
    print("\nSome checks failed." if failed else "\nAll required checks passed.")
    return 1 if failed else 0


def mic_test(phase_s: float = 3.0) -> int:
    """Compare background noise with the user's voice and suggest vad.min_speech_level_dbfs."""
    from jarvis.audio.calibration import calibrate, measure
    from jarvis.audio.vad import SileroVad

    try:
        config = load_config(paths.CONFIG_DIR)
        device = find_device(config.audio.input_device, "input")
    except (ConfigError, DeviceNotFoundError) as exc:
        print(f"Cannot test the microphone: {exc}")
        return 1
    vad = SileroVad()
    print(f"Microphone: {device_name(device, 'input')}")
    input(f"Press Enter, then stay QUIET for {phase_s:.0f} seconds...")
    quiet = measure(phase_s, device, vad)
    input(f"Press Enter, then SPEAK normally for {phase_s:.0f} seconds (e.g. count to ten)...")
    speaking = measure(phase_s, device, vad)

    result = calibrate(quiet, speaking, config.vad.threshold)
    current = config.vad.min_speech_level_dbfs
    print(f"\nBackground level:        {result.background_dbfs:6.1f} dBFS")
    if result.background_speech:
        print("  (speech-like sound while you were quiet: a TV, a video or people nearby)")
    if result.speech_dbfs is None:
        print("No speech detected while you spoke: check the microphone and its volume.")
        return 1
    print(f"Your voice:              {result.speech_dbfs:6.1f} dBFS")
    print(f"Current minimum level:   {current:6.1f} dBFS (vad.min_speech_level_dbfs)")
    print(f"Suggested minimum level: {result.suggested_min_level_dbfs:6.1f} dBFS")
    if result.speech_dbfs - result.background_dbfs < 10:
        print("Your voice is barely louder than the background: raise the microphone volume.")
    elif current >= result.speech_dbfs - 3:
        print("The current minimum would cut off your voice: use the suggested value.")
    print("\nTo change it, add to config/local.toml:\n  [vad]")
    print(f"  min_speech_level_dbfs = {result.suggested_min_level_dbfs:.1f}")
    return 0


def print_devices() -> int:
    sections: tuple[tuple[Kind, str], ...] = (("input", "Microphones"), ("output", "Audio outputs"))
    for kind, title in sections:
        print(f"{title}:")
        for name in list_devices(kind):
            print(f"  {name}")
    print('\nUse part of a name in config/local.toml, e.g. [audio] input_device = "fifine".')
    return 0
