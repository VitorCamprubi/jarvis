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
    web_search_usd: float = Field(ge=0)  # per search

    @model_validator(mode="after")
    def _warn_before_stop(self) -> Self:
        if self.warn_usd > self.stop_usd:
            raise ValueError("budget.warn_usd cannot exceed budget.stop_usd")
        return self


class SearchConfig(_Section):
    enabled: bool
    max_per_question: int = Field(ge=1, le=5)
    daily_limit: int = Field(ge=0, le=500)


class NewsFeed(_Section):
    name: str = Field(min_length=1)
    url: HttpUrlText
    language: Language


class NewsTopic(_Section):
    query: str = Field(min_length=1)
    language: Language


class NewsConfig(_Section):
    max_age_hours: float = Field(gt=0, le=72)
    per_source_limit: int = Field(ge=1, le=50)
    cache_minutes: float = Field(ge=0, le=240)
    request_timeout_s: float = Field(gt=0, le=30)
    duplicate_threshold: int = Field(ge=50, le=100)
    spoken_stories: int = Field(ge=1, le=8)
    briefing_stories: int = Field(ge=1, le=5)
    feeds: list[NewsFeed]
    topics: list[NewsTopic]

    @model_validator(mode="after")
    def _has_sources(self) -> Self:
        if not self.feeds and not self.topics:
            raise ValueError("news needs at least one feed or topic")
        return self


class FilesConfig(_Section):
    folders: list[str] = Field(min_length=1)
    skip_dirs: list[str]
    refresh_minutes: float = Field(gt=0, le=1440)
    max_results: int = Field(ge=1, le=10)
    match_threshold: int = Field(ge=50, le=100)


class RemindersConfig(_Section):
    default_hour: int = Field(ge=0, le=23)  # "amanhã" without a time


class WakeConfig(_Section):
    enabled: bool
    model: str = Field(min_length=1)  # an openWakeWord pre-trained model
    threshold: float = Field(gt=0, le=1)  # wakes at once
    confirm_threshold: float = Field(gt=0, le=1)  # from here up, Whisper confirms
    confirm_s: float = Field(gt=0.5, le=5)  # audio transcribed to confirm
    backlog_s: float = Field(ge=0, le=6)  # audio before the wake kept in the request
    cooldown_s: float = Field(ge=0, le=10)

    @model_validator(mode="after")
    def _confirm_below_threshold(self) -> Self:
        if self.confirm_threshold > self.threshold:
            raise ValueError("wake.confirm_threshold cannot exceed wake.threshold")
        return self


class HudConfig(_Section):
    enabled: bool  # false: console only, as in Phases 1 to 4
    opacity: float = Field(ge=0.3, le=1.0)  # of the panel's background
    details_seconds: float = Field(ge=5, le=600)  # lists and details fold away after this
    load_seconds: float = Field(ge=0.5, le=30)  # CPU/GPU/RAM refresh


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
    search: SearchConfig
    files: FilesConfig
    reminders: RemindersConfig
    weather: WeatherConfig
    news: NewsConfig
    hud: HudConfig
    wake: WakeConfig

    @model_validator(mode="after")
    def _check_vad_timings(self) -> Self:
        if self.vad.no_speech_timeout_s > self.vad.max_utterance_s:
            raise ValueError("vad.no_speech_timeout_s cannot exceed vad.max_utterance_s")
        return self
