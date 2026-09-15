"""Application configuration and environment settings."""

from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str = "secret"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    APP_ENV: str = "development"
    DEVICE: str = "cpu"
    MAX_AUDIO_SIZE_MB: int = 25
    UPLOAD_DIR: str = "uploads"
    OUTPUT_DIR: str = "outputs"
    WEIGHTS_DIR: str = str(BASE_DIR / "weights")
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    # Must match backend/services/sv2tts/vocoder/hparams.py's `sample_rate`
    # (itself derived from the synthesizer's hparams) for the real SV2TTS
    # checkpoint (HARDENING_PLAN.md finding H1/C2 verification) — confirmed
    # 16000, not the previously-guessed 22050.
    VOCODER_SAMPLE_RATE: int = 16000
    RATE_LIMIT_ENABLED: bool = True
    STORAGE_MAX_AGE_HOURS: float = 24
    STORAGE_CLEANUP_INTERVAL_SECONDS: float = 3600
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        if v == "secret" or len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters and cannot be 'secret'"
            )
        return v

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
