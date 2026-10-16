import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import pytest

from jarvis.doctor import (
    Status,
    check_config,
    check_cuda,
    check_gpu,
    check_hotkey,
    check_llm,
    check_python,
    check_spending,
    check_wake_word,
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


def test_llm_check_warns_without_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert check_llm(tmp_path / ".env").status is Status.WARN


def test_llm_check_treats_an_empty_key_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")

    def factory(key: str) -> FakeClient:
        raise AssertionError("no client without a key")

    assert check_llm(env_file, client_factory=factory).status is Status.WARN


REQUEST = httpx2.Request("GET", "https://api.anthropic.com/v1/models/claude-haiku-5-5")


def status_error(cls: type[anthropic.APIStatusError], status: int, text: str = "") -> Exception:
    return cls(text, response=httpx2.Response(status, request=REQUEST), body=None)


class FakeModels:
    def __init__(self, error: Exception | None) -> None:
        self.error = error

    def retrieve(self, model: str) -> object:
        if self.error is not None:
            raise self.error
        return object()


class FakeClient:
    def __init__(self, error: Exception | None) -> None:
        self.models = FakeModels(error)


def env_with_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    return env_file


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (None, Status.OK),
        (status_error(anthropic.AuthenticationError, 401), Status.FAIL),
        (status_error(anthropic.NotFoundError, 404), Status.FAIL),
        (
            status_error(anthropic.BadRequestError, 400, "anthropic-workspace-id is required"),
            Status.FAIL,
        ),
        (anthropic.APIConnectionError(request=REQUEST), Status.WARN),
    ],
)
def test_llm_check_validates_the_key_for_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception | None, status: Status
) -> None:
    keys: list[str] = []

    def factory(key: str) -> FakeClient:
        keys.append(key)
        return FakeClient(error)

    result = check_llm(env_with_key(tmp_path, monkeypatch), client_factory=factory)

    assert result.status is status
    assert keys == ["sk-ant-test"]
    assert "sk-ant-test" not in result.detail


def test_spending_check_without_a_database(tmp_path: Path) -> None:
    result = check_spending(tmp_path / "jarvis.db", stop_usd=4.9)

    assert result.status is Status.OK
    assert result.detail == "no LLM usage yet"


@pytest.mark.parametrize(("spent", "status"), [(0.0123, Status.OK), (4.95, Status.WARN)])
def test_spending_check_sums_the_recorded_cost(
    tmp_path: Path, spent: float, status: Status
) -> None:
    db_file = tmp_path / "jarvis.db"
    with closing(sqlite3.connect(db_file)) as connection, connection:
        connection.execute("CREATE TABLE llm_usage (cost_usd REAL)")
        connection.executemany("INSERT INTO llm_usage VALUES (?)", [(spent / 2,), (spent / 2,)])

    result = check_spending(db_file, stop_usd=4.9)

    assert result.status is status
    assert f"US$ {spent:.4f}" in result.detail


def test_spending_check_counts_todays_web_searches(tmp_path: Path) -> None:
    db_file = tmp_path / "jarvis.db"
    with closing(sqlite3.connect(db_file)) as connection, connection:
        connection.execute("CREATE TABLE llm_usage (at TEXT, cost_usd REAL, web_searches INTEGER)")
        connection.executemany(
            "INSERT INTO llm_usage VALUES (?, ?, ?)",
            [
                ("2026-10-12T20:00:00+00:00", 0.02, 2),  # yesterday, local time
                ("2026-10-13T12:00:00+00:00", 0.03, 3),
            ],
        )
    now = datetime(2026, 10, 13, 10, 0, tzinfo=timezone(timedelta(hours=-3)))

    result = check_spending(db_file, stop_usd=4.9, daily_searches=20, now=now)

    assert result.detail.endswith("; 3 of 20 web searches today")


def test_wake_word_check_reports_the_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import openwakeword

    fake_package = tmp_path / "openwakeword"
    (fake_package / "resources" / "models").mkdir(parents=True)
    monkeypatch.setattr(openwakeword, "__file__", str(fake_package / "__init__.py"))
    assert check_wake_word("hey_jarvis").status is Status.WARN  # downloaded on the first start

    (fake_package / "resources" / "models" / "hey_jarvis_v0.1.onnx").write_bytes(b"")
    assert check_wake_word("hey_jarvis").status is Status.OK
