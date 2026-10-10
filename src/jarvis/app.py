"""Composition root: builds the application's components and wires them together.

Like a hand-written Spring context: this is the only place that knows the
concrete implementations. Every phase plugs its components in here.
"""

import logging
import platform

from jarvis import __version__, paths
from jarvis.config import ConfigError, load_config
from jarvis.log import setup_logging, shutdown_logging

log = logging.getLogger(__name__)


def run() -> int:
    try:
        config = load_config(paths.CONFIG_DIR)
    except ConfigError as exc:
        # Logging is not configured yet, and it depends on this very configuration.
        print(f"JARVIS cannot start: {exc}")
        return 2

    log_dir = paths.PROJECT_ROOT / config.logging.directory
    setup_logging(config.logging, log_dir)
    try:
        weather = config.weather
        log.info("JARVIS %s starting on Python %s", __version__, platform.python_version())
        log.info("Configuration loaded from %s", paths.CONFIG_DIR)
        log.info(
            "Default weather location: %s, %s, %s (%.5f, %.5f)",
            weather.city,
            weather.region,
            weather.country_code,
            weather.latitude,
            weather.longitude,
        )
        log.info("Logs: %s", log_dir.resolve())
        log.info("Foundation ready. The voice pipeline arrives in Phase 1.")
        return 0
    finally:
        shutdown_logging()
