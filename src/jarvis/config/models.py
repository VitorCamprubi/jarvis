"""Typed, validated configuration models.

Defaults live only in config/default.toml, so every field here is required:
there is a single source of truth and a missing key is reported, not hidden.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class _Section(BaseModel):
    # extra="forbid" turns a typo in a TOML key into an error instead of a silently ignored value.
    model_config = ConfigDict(extra="forbid", frozen=True)


class LoggingConfig(_Section):
    level: LogLevel
    directory: Path
    max_file_size_mb: int = Field(gt=0, le=100)
    backup_count: int = Field(ge=0, le=50)
    log_transcripts: bool


class WeatherConfig(_Section):
    city: str = Field(min_length=1)
    region: str
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1)


class AppConfig(_Section):
    logging: LoggingConfig
    weather: WeatherConfig
