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
    # HARDENING_PLAN.md finding M5: extra bytes allowed on top of
    # MAX_AUDIO_SIZE_MB for multipart boundaries and form fields. The ASGI
    # body-size limit is MAX_AUDIO_SIZE_MB + this, enforced before parsing.
    REQUEST_BODY_OVERHEAD_KB: int = 256
    # HARDENING_PLAN.md finding M4: duration bounds for voice samples.
    # MIN_VOICED_DURATION_SECONDS applies AFTER silence trimming, so a long
    # file that is mostly silence is rejected; MAX_AUDIO_DURATION_SECONDS
    # applies to the raw upload, checked before the expensive decode.
    MIN_VOICED_DURATION_SECONDS: float = 2.0
    MAX_AUDIO_DURATION_SECONDS: float = 300.0
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
    # HARDENING_PLAN.md finding M3: slowapi/limits storage backend. The
    # default is per-process memory (fine for one worker in dev/tests); set a
    # shared store such as ``redis://redis:6379/0`` so limits hold across
    # workers/replicas and survive restarts.
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    # Number of trusted reverse proxies in front of the app. 0 (default) means
    # the socket peer is the client and X-Forwarded-For is ignored, since it
    # is attacker-controlled when no proxy overwrites it.
    TRUSTED_PROXY_COUNT: int = 0
    AUTH_LOGIN_RATE_LIMIT: str = "10/minute"
    AUTH_SIGNUP_RATE_LIMIT: str = "5/minute"
    # HARDENING_PLAN.md finding H6: bound the single process-wide inference
    # semaphore so callers fail fast instead of queuing unbounded.
    # INFERENCE_MAX_WAITERS: requests already queued for a slot beyond this
    # are rejected immediately with 429, never counting the request(s)
    # currently holding the semaphore.
    INFERENCE_MAX_WAITERS: int = 10
    # INFERENCE_ACQUIRE_TIMEOUT_SECONDS: max time a queued request waits for
    # a free slot before giving up with 503.
    INFERENCE_ACQUIRE_TIMEOUT_SECONDS: float = 10.0
    # INFERENCE_CALL_TIMEOUT_SECONDS: max wall-clock time for one held
    # inference call (embedding extraction, or the synthesizer+vocoder
    # forward passes together) before it is abandoned with 503.
    INFERENCE_CALL_TIMEOUT_SECONDS: float = 30.0
    # HARDENING_PLAN.md finding M6: on shutdown, wait up to this long for
    # in-flight forward passes (worker threads) to finish before exiting.
    INFERENCE_SHUTDOWN_DRAIN_TIMEOUT_SECONDS: float = 30.0
    # HARDENING_PLAN.md finding M7 (readiness probe).
    # READINESS_DB_TIMEOUT_SECONDS: max time the `SELECT 1` DB check may take
    # before /health/ready reports the database as down.
    READINESS_DB_TIMEOUT_SECONDS: float = 2.0
    # READINESS_WARMUP_ENABLED: run one tiny synthesizer+vocoder forward pass
    # at startup and require it to succeed before reporting ready. Off by
    # default (adds startup time; the result is cached, never re-run per probe).
    READINESS_WARMUP_ENABLED: bool = False
    # HARDENING_PLAN.md finding M8: Prometheus metrics at GET /metrics.
    # METRICS_ENABLED=False makes the endpoint return 404. When
    # METRICS_AUTH_TOKEN is non-empty, scrapers must send it as a bearer token.
    METRICS_ENABLED: bool = True
    METRICS_AUTH_TOKEN: str = ""
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
