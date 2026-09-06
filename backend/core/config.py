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
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]
    VOCODER_SAMPLE_RATE: int = 22050

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
