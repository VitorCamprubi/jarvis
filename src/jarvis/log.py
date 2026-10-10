"""Logging setup: rotating log files in the logs directory plus console output.

Two separate logs:
- jarvis.log: application events, at the level set in the configuration.
- transcripts.log: what the user said, written only when logging.log_transcripts is true.
  Transcripts never propagate to jarvis.log or the console.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.config import LoggingConfig

APP_LOGGER = "jarvis"
TRANSCRIPT_LOGGER = "jarvis.transcripts"
APP_LOG_FILE = "jarvis.log"
TRANSCRIPT_LOG_FILE = "transcripts.log"

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

# Handlers installed by setup_logging, so shutdown_logging removes only ours
# (and leaves alone handlers added by others, such as pytest's log capture).
_installed: list[tuple[logging.Logger, logging.Handler]] = []


def setup_logging(config: LoggingConfig, log_dir: Path) -> None:
    """Configure logging. Safe to call again: previous handlers are replaced."""
    shutdown_logging()
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT)
    max_bytes = config.max_file_size_mb * 1024 * 1024

    # Handlers go on the root logger so third-party warnings are captured too;
    # the root stays at WARNING while our own "jarvis" loggers use the configured level.
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    app_file = _rotating_file(log_dir / APP_LOG_FILE, max_bytes, config.backup_count)
    console = logging.StreamHandler(sys.stderr)
    for handler in (app_file, console):
        handler.setFormatter(formatter)
        _install(root, handler)
    logging.getLogger(APP_LOGGER).setLevel(config.level)

    transcripts = logging.getLogger(TRANSCRIPT_LOGGER)
    transcripts.setLevel(logging.INFO)
    transcripts.propagate = False
    transcript_handler: logging.Handler
    if config.log_transcripts:
        transcript_handler = _rotating_file(
            log_dir / TRANSCRIPT_LOG_FILE, max_bytes, config.backup_count
        )
        transcript_handler.setFormatter(formatter)
    else:
        transcript_handler = logging.NullHandler()
    _install(transcripts, transcript_handler)


def shutdown_logging() -> None:
    """Detach and close our handlers, releasing the log files (Windows locks open files)."""
    while _installed:
        logger, handler = _installed.pop()
        logger.removeHandler(handler)
        handler.close()


def _rotating_file(path: Path, max_bytes: int, backup_count: int) -> RotatingFileHandler:
    # delay=True opens the file on the first record, so unused logs leave no empty files.
    return RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8", delay=True
    )


def _install(logger: logging.Logger, handler: logging.Handler) -> None:
    logger.addHandler(handler)
    _installed.append((logger, handler))
