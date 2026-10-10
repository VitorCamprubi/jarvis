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
    return tmp_path


def test_run_starts_and_writes_the_app_log(project_root: Path) -> None:
    assert app.run() == 0

    log_text = (project_root / "logs" / APP_LOG_FILE).read_text(encoding="utf-8")
    assert "Foundation ready" in log_text


def test_run_exits_with_error_on_invalid_config(
    project_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project_root / "config" / LOCAL_FILE).write_text("[logging\n", encoding="utf-8")

    assert app.run() == 2
    assert "cannot start" in capsys.readouterr().out
