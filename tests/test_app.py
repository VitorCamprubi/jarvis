import shutil
from pathlib import Path

import pytest

from jarvis import app, paths
from jarvis.config.loader import DEFAULT_FILE, LOCAL_FILE
from jarvis.log import APP_LOG_FILE


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the app at a temporary project root holding only the shipped defaults."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(paths.CONFIG_DIR / DEFAULT_FILE, config_dir)
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    return tmp_path


def write_local(project_root: Path, toml: str) -> None:
    (project_root / "config" / LOCAL_FILE).write_text(toml, encoding="utf-8")


def app_log(project_root: Path) -> str:
    return (project_root / "logs" / APP_LOG_FILE).read_text(encoding="utf-8")


def test_run_exits_with_error_on_invalid_config(
    project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_local(project_root, "[logging\n")

    assert app.run() == 2
    assert "cannot start" in capsys.readouterr().out


def test_run_explains_an_invalid_hotkey(project_root: Path) -> None:
    write_local(project_root, '[activation]\nhotkey = "ctrl+alt+nope"\n')

    assert app.run() == 2
    assert "Unknown key 'nope'" in app_log(project_root)


def test_run_explains_a_missing_microphone(project_root: Path) -> None:
    write_local(project_root, '[audio]\ninput_device = "no such microphone 42"\n')

    assert app.run() == 2
    assert "no such microphone 42" in app_log(project_root)
