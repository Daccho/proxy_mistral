from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
import os

_env_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class MeetingBaaSSettings(BaseSettings):
    model_config = _env_config
    api_key: str = Field(..., alias="MEETING_BAAS_API_KEY")
    base_url: str = Field("https://api.meetingbaas.com", alias="MEETING_BAAS_BASE_URL")
    audio_format: str = "s16le"
    sample_rate: int = 16000
    ws_port: int = 8765


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
    model: str = "eleven_turbo_v2_5"
    stability: float = 0.5
    similarity_boost: float = 0.75


class AppSettings(BaseSettings):
    log_level: str = "INFO"
    data_dir: str = "data"
    max_context_tokens: int = 256000
    context_compression_threshold: float = 0.7


class Settings(BaseSettings):
    meeting_baas: MeetingBaaSSettings = MeetingBaaSSettings()
    mistral: MistralSettings = MistralSettings()
    elevenlabs: ElevenLabsSettings = ElevenLabsSettings()
    app: AppSettings = AppSettings()

    model_config = _env_config


# Initialize settings
settings = Settings()