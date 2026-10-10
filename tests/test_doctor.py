import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from jarvis.doctor import (
    Status,
    check_config,
    check_cuda,
    check_gpu,
    check_hotkey,
    check_python,
    check_secrets,
)

FakeRun = Callable[..., subprocess.CompletedProcess[str]]


def nvidia_smi_returning(stdout: str) -> FakeRun:
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    return run


def nvidia_smi_raising(error: Exception) -> FakeRun:
    def run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise error

    return run


def test_python_version_check() -> None:
    assert check_python((3, 14)).status is Status.OK
    assert check_python((3, 13)).status is Status.FAIL


def test_gpu_reports_name_driver_and_free_vram() -> None:
    result = check_gpu(nvidia_smi_returning("NVIDIA GeForce RTX 4060 Ti, 617.14, 8188, 1226\n"))

    assert result.status is Status.OK
    assert "RTX 4060 Ti" in result.detail
    assert "driver 617.14" in result.detail
    assert "6.8 GB free of 8.0 GB" in result.detail


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("nvidia-smi"),
        subprocess.CalledProcessError(9, "nvidia-smi"),
        subprocess.TimeoutExpired("nvidia-smi", 10),
    ],
)
def test_gpu_check_fails_when_driver_is_unavailable(error: Exception) -> None:
    assert check_gpu(nvidia_smi_raising(error)).status is Status.FAIL


def test_gpu_check_warns_on_unexpected_output() -> None:
    assert check_gpu(nvidia_smi_returning("something else")).status is Status.WARN


def test_cuda_check_fails_without_the_nvidia_wheels() -> None:
    result = check_cuda(lambda: [])

    assert result.status is Status.FAIL
    assert "uv sync" in result.detail


def test_cuda_check_names_missing_libraries(tmp_path: Path) -> None:
    (tmp_path / "cublas64_12.dll").write_bytes(b"")

    result = check_cuda(lambda: [tmp_path])

    assert result.status is Status.FAIL
    assert "cudnn64_9.dll" in result.detail


def test_hotkey_check() -> None:
    assert check_hotkey("ctrl+alt+j").status is Status.OK
    assert check_hotkey("ctrl+alt+").status is Status.FAIL


def test_config_check_fails_without_config(tmp_path: Path) -> None:
    assert check_config(tmp_path).status is Status.FAIL


def test_secrets_check_warns_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert check_secrets(tmp_path / ".env").status is Status.WARN
