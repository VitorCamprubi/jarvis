"""Layered TOML loading: config/default.toml, then config/local.toml on top."""

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jarvis.config.models import AppConfig

DEFAULT_FILE = "default.toml"
LOCAL_FILE = "local.toml"


class ConfigError(Exception):
    """The configuration is missing, malformed or invalid."""


def load_config(config_dir: Path) -> AppConfig:
    """Load and validate the configuration found in ``config_dir``."""
    data = _read_toml(config_dir / DEFAULT_FILE)
    local_file = config_dir / LOCAL_FILE
    if local_file.exists():
        data = deep_merge(data, _read_toml(local_file))

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration in {config_dir}:\n{exc}") from exc


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict where ``override`` wins; nested tables merge, other values replace."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed TOML in {path}: {exc}") from exc
