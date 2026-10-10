import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.config import LoggingConfig
from jarvis.log import (
    APP_LOG_FILE,
    TRANSCRIPT_LOG_FILE,
    TRANSCRIPT_LOGGER,
    setup_logging,
    shutdown_logging,
)


def make_config(**overrides: object) -> LoggingConfig:
    values: dict[str, object] = {
        "level": "INFO",
        "directory": "logs",
        "max_file_size_mb": 1,
        "backup_count": 1,
        "log_transcripts": True,
    }
    values.update(overrides)
    return LoggingConfig.model_validate(values)


@pytest.fixture(autouse=True)
def release_log_files() -> Iterator[None]:
    yield
    shutdown_logging()


def test_app_events_go_to_the_app_log(tmp_path: Path) -> None:
    setup_logging(make_config(), tmp_path)

    logging.getLogger("jarvis.test").info("systems online")
    shutdown_logging()

    assert "systems online" in (tmp_path / APP_LOG_FILE).read_text(encoding="utf-8")


def test_configured_level_filters_lower_levels(tmp_path: Path) -> None:
    setup_logging(make_config(level="WARNING"), tmp_path)

    logger = logging.getLogger("jarvis.test")
    logger.info("routine detail")
    logger.warning("worth noting")
    shutdown_logging()

    text = (tmp_path / APP_LOG_FILE).read_text(encoding="utf-8")
    assert "worth noting" in text
    assert "routine detail" not in text


def test_transcripts_are_kept_out_of_the_app_log(tmp_path: Path) -> None:
    setup_logging(make_config(), tmp_path)

    logging.getLogger(TRANSCRIPT_LOGGER).info("abre o navegador")
    shutdown_logging()

    assert "abre o navegador" in (tmp_path / TRANSCRIPT_LOG_FILE).read_text(encoding="utf-8")
    assert not (tmp_path / APP_LOG_FILE).exists()


def test_transcripts_are_not_recorded_when_disabled(tmp_path: Path) -> None:
    setup_logging(make_config(log_transcripts=False), tmp_path)

    logging.getLogger(TRANSCRIPT_LOGGER).info("private words")
    shutdown_logging()

    assert not (tmp_path / TRANSCRIPT_LOG_FILE).exists()
    assert not (tmp_path / APP_LOG_FILE).exists()


def test_setup_twice_does_not_duplicate_lines(tmp_path: Path) -> None:
    setup_logging(make_config(), tmp_path)
    setup_logging(make_config(), tmp_path)

    logging.getLogger("jarvis.test").info("once only")
    shutdown_logging()

    assert (tmp_path / APP_LOG_FILE).read_text(encoding="utf-8").count("once only") == 1
