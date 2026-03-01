from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
import os

_env_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class MeetingBaaSSettings(BaseSettings):
    model_config = _env_config
    api_key: str = Field(..., alias="MEETING_BAAS_API_KEY")
    base_url: str = Field("https://api.meetingbaas.com", alias="MEETING_BAAS_BASE_URL")
    bot_image: str = Field("", alias="BOT_IMAGE")
    audio_format: str = "s16le"
    sample_rate: int = 16000
    ws_port: int = 8765
    public_ws_url: str = Field("", alias="PUBLIC_WS_URL")


class MistralSettings(BaseSettings):
    model_config = _env_config
    api_key: str = Field(..., alias="MISTRAL_API_KEY")
    model: str = "mistral-medium-2505"
    temperature: float = 0.3
    max_tokens: int = 4096


class ElevenLabsSettings(BaseSettings):
    model_config = _env_config
    api_key: str = Field(..., alias="ELEVENLABS_API_KEY")
    voice_id: str = Field(..., alias="ELEVENLABS_VOICE_ID")
    model: str = "eleven_flash_v2_5"
    stability: float = 0.5
    similarity_boost: float = 0.75


class AppSettings(BaseSettings):
    log_level: str = "INFO"
    data_dir: str = "data"
    max_context_tokens: int = 256000
    context_compression_threshold: float = 0.7
    environment: str = Field("development", alias="ENVIRONMENT")


class SecuritySettings(BaseSettings):
    model_config = _env_config
    api_key: str = Field("", alias="PROXY_MISTRAL_API_KEY")
    ws_token: str = Field("", alias="PROXY_MISTRAL_WS_TOKEN")
    allowed_origins: str = Field("", alias="ALLOWED_ORIGINS")


class GoogleCalendarSettings(BaseSettings):
    model_config = _env_config
    credentials_json: str = Field("", alias="GOOGLE_CALENDAR_CREDENTIALS")
    token_path: str = "data/google_calendar_token.json"
    poll_interval_minutes: int = Field(5, alias="CALENDAR_POLL_INTERVAL")
    lookahead_minutes: int = Field(15, alias="CALENDAR_LOOKAHEAD_MINUTES")


class SchedulerSettings(BaseSettings):
    model_config = _env_config
    enabled: bool = Field(True, alias="SCHEDULER_ENABLED")
    max_concurrent_meetings: int = Field(1, alias="MAX_CONCURRENT_MEETINGS")
    join_before_start_minutes: int = Field(2, alias="JOIN_BEFORE_START_MINUTES")
    auto_leave_after_end_minutes: int = Field(5, alias="AUTO_LEAVE_AFTER_END_MINUTES")
    default_persona: str = Field("default", alias="DEFAULT_PERSONA")


class Settings(BaseSettings):
    meeting_baas: MeetingBaaSSettings = MeetingBaaSSettings()
    mistral: MistralSettings = MistralSettings()
    elevenlabs: ElevenLabsSettings = ElevenLabsSettings()
    app: AppSettings = AppSettings()
    security: SecuritySettings = SecuritySettings()
    google_calendar: GoogleCalendarSettings = GoogleCalendarSettings()
    scheduler: SchedulerSettings = SchedulerSettings()

    model_config = _env_config


# Initialize settings
settings = Settings()