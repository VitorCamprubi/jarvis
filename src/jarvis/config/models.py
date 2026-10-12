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


class UserConfig(_Section):
    name: str = Field(min_length=1)
    surname: str = Field(min_length=1)


class BrainConfig(_Section):
    model: str = Field(min_length=1)
    effort: Literal["low", "medium", "high"]
    thinking: Literal["adaptive", "disabled"]
    max_tokens: int = Field(ge=256, le=16000)
    max_tool_rounds: int = Field(ge=1, le=8)
    request_timeout_s: float = Field(gt=0, le=120)
    memory_turns: int = Field(ge=0, le=20)
    memory_minutes: float = Field(gt=0, le=240)


class BudgetConfig(_Section):
    warn_usd: float = Field(ge=0)
    stop_usd: float = Field(gt=0)
    # US$ per million tokens.
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    cache_write_per_mtok: float = Field(ge=0)
    cache_read_per_mtok: float = Field(ge=0)

    @model_validator(mode="after")
    def _warn_before_stop(self) -> Self:
        if self.warn_usd > self.stop_usd:
            raise ValueError("budget.warn_usd cannot exceed budget.stop_usd")
        return self


class FilesConfig(_Section):
    folders: list[str] = Field(min_length=1)
    skip_dirs: list[str]
    refresh_minutes: float = Field(gt=0, le=1440)
    max_results: int = Field(ge=1, le=10)
    match_threshold: int = Field(ge=50, le=100)


class RemindersConfig(_Section):
    default_hour: int = Field(ge=0, le=23)  # "amanhã" without a time


class WeatherConfig(_Section):
    city: str = Field(min_length=1)
    region: str
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1)


class AppConfig(_Section):
    user: UserConfig
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
    brain: BrainConfig
    budget: BudgetConfig
    files: FilesConfig
    reminders: RemindersConfig
    weather: WeatherConfig

    @model_validator(mode="after")
    def _check_vad_timings(self) -> Self:
        if self.vad.no_speech_timeout_s > self.vad.max_utterance_s:
            raise ValueError("vad.no_speech_timeout_s cannot exceed vad.max_utterance_s")
        return self
