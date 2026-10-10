"""Environment checks, run with `uv run jarvis --check`.

Each phase adds the checks it needs (microphone and CUDA libraries in Phase 1,
LLM provider in Phase 3). A FAIL makes the command exit with a non-zero code.
"""

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jarvis import paths
from jarvis.config import ConfigError, load_config, load_secrets

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
    """Query the NVIDIA driver; speech recognition runs on the GPU from Phase 1."""
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


def check_config(config_dir: Path = paths.CONFIG_DIR) -> CheckResult:
    try:
        config = load_config(config_dir)
    except ConfigError as exc:
        return CheckResult("Config", Status.FAIL, str(exc))
    weather = config.weather
    return CheckResult(
        "Config", Status.OK, f"valid; weather default: {weather.city}, {weather.region}"
    )


def check_secrets(env_file: Path = paths.ENV_FILE) -> CheckResult:
    if load_secrets(env_file).anthropic_api_key is None:
        return CheckResult(
            "Secrets", Status.WARN, "ANTHROPIC_API_KEY not set (needed from Phase 3)"
        )
    return CheckResult("Secrets", Status.OK, "ANTHROPIC_API_KEY is set")


def run_checks() -> int:
    results = [check_python(), check_gpu(), check_config(), check_secrets()]
    width = max(len(result.name) for result in results)
    for result in results:
        print(f"[{result.status:<4}] {result.name:<{width}}  {result.detail}")
    failed = any(result.status is Status.FAIL for result in results)
    print("\nSome checks failed." if failed else "\nAll required checks passed.")
    return 1 if failed else 0
