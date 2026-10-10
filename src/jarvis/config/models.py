"""Typed, validated configuration models.

Defaults live only in config/default.toml, so every field here is required:
there is a single source of truth and a missing key is reported, not hidden.
"""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis.i18n.language import Language

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
HttpUrlText = Annotated[str, Field(pattern=r"^https?://\S+$")]


class _Section(BaseModel):
    # extra="forbid" turns a typo in a TOML key into an error instead of a silently ignored value.
    model_config = ConfigDict(extra="forbid", frozen=True)


class LoggingConfig(_Section):
    level: LogLevel
    directory: Path
    max_file_size_mb: int = Field(gt=0, le=100)
    backup_count: int = Field(ge=0, le=50)
    log_transcripts: bool


class LanguageConfig(_Section):
    default: Language


class ActivationConfig(_Section):
    hotkey: str = Field(min_length=1)


class AudioConfig(_Section):
    input_device: str
    output_device: str
    feedback_volume: float = Field(ge=0, le=1)


class VadConfig(_Section):
    threshold: float = Field(gt=0, lt=1)
    min_speech_level_dbfs: float = Field(ge=-100, le=0)
    silence_ms: int = Field(ge=100, le=5000)
    no_speech_timeout_s: float = Field(gt=0, le=60)
    max_utterance_s: float = Field(gt=0, le=120)
    pre_roll_ms: int = Field(ge=0, le=2000)


class SttConfig(_Section):
    model: str = Field(min_length=1)
    device: Literal["cuda", "cpu"]
    compute_type: str = Field(min_length=1)
    beam_size: int = Field(ge=1, le=10)
    short_audio_s: float = Field(ge=0)
    min_confidence: float = Field(ge=0.5, le=1)
    min_confidence_short: float = Field(ge=0.5, le=1)


class TtsConfig(_Section):
    first_audio_timeout_s: float = Field(gt=0, le=30)
    retry_online_after_s: float = Field(ge=0)
    cache: bool
    cache_max_mb: int = Field(gt=0)
    edge_voice_en: str = Field(min_length=1)
    edge_voice_pt: str = Field(min_length=1)
    piper_voice_en: str = Field(pattern=r"^[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-[a-z]+$")
    piper_voice_pt: str = Field(pattern=r"^[a-z]{2}_[A-Z]{2}-[a-z0-9_]+-[a-z]+$")


class ConfirmationConfig(_Section):
    timeout_s: float = Field(ge=1, le=30)


class AppsConfig(_Section):
    match_threshold: int = Field(ge=50, le=100)
    refresh_minutes: int = Field(ge=1, le=1440)
    aliases: dict[str, str]  # spoken name -> Start menu app name, or a URL


class SitesConfig(_Section):
    favorites: dict[str, HttpUrlText]


class VolumeConfig(_Section):
    step: int = Field(ge=1, le=50)


class WeatherConfig(_Section):
    city: str = Field(min_length=1)
    region: str
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1)


class AppConfig(_Section):
    logging: LoggingConfig
    language: LanguageConfig
    activation: ActivationConfig
    audio: AudioConfig
    vad: VadConfig
    stt: SttConfig
    tts: TtsConfig
    confirmation: ConfirmationConfig
    apps: AppsConfig
    sites: SitesConfig
    volume: VolumeConfig
    weather: WeatherConfig

    @model_validator(mode="after")
    def _check_vad_timings(self) -> Self:
        if self.vad.no_speech_timeout_s > self.vad.max_utterance_s:
            raise ValueError("vad.no_speech_timeout_s cannot exceed vad.max_utterance_s")
        return self
