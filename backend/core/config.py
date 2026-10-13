"""Application configuration and environment settings."""

from pathlib import Path
from typing import List, Literal, get_args
from urllib.parse import urlparse

from limits import parse as parse_rate_limit
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Seconds of silence inserted after a synthesized segment, by how the segment ended
# (SPEECH_QUALITY_PLAN.md S1.3). The keys are the values of
# `services.text_chunking.Boundary` (a test keeps the two in step).
DEFAULT_TTS_PAUSE_SECONDS = {
    "statement": 0.40,
    "question": 0.45,
    "exclamation": 0.45,
    "ellipsis": 0.60,
    "clause": 0.25,
    "comma": 0.12,
    "word": 0.05,
    "paragraph": 0.70,
}
MAX_TTS_PAUSE_SECONDS = 3.0


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str = "secret"
    JWT_ALGORITHM: str = "HS256"
    # HARDENING_PLAN.md finding L6: the session cookie (used by authlib's
    # OAuth flow to hold Google login state/nonce, see api/auth.py) must not
    # sign with the same secret as JWT access/refresh tokens — a leak of one
    # purpose's secret would otherwise compromise the other too. Left blank
    # by default so existing single-secret deployments keep working; main.py
    # falls back to JWT_SECRET_KEY and logs a warning when this is unset.
    SESSION_SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # HARDENING_PLAN.md finding P2-M4: a token replayed this many seconds after
    # it was rotated is refused but does not revoke the user's other sessions,
    # so two tabs refreshing at once don't sign the user out. 0 = always revoke.
    REFRESH_REUSE_GRACE_SECONDS: int = 10
    # Expired refresh-token rows are deleted after this many days (the JWT's
    # own exp already rejects them; the row is dead weight). <= 0 keeps them.
    REFRESH_TOKEN_PRUNE_AFTER_DAYS: int = 1
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    # HARDENING_PLAN.md finding P2-L7: production is the fail-safe default —
    # a deployment that forgets to set this (or copies backend/.env.example
    # unedited) gets INFO logging, not DEBUG lines carrying per-request user
    # ids and file paths. Set to "development" for verbose local debugging.
    APP_ENV: str = "production"
    # Interactive API docs (/docs, /redoc, /openapi.json) describe every route;
    # they are served only in development unless this is set explicitly.
    API_DOCS_ENABLED: bool = False
    DEVICE: str = "cpu"
    # HARDENING_PLAN.md finding P2-L11: torch's CPU thread count. 0 = follow the
    # container CPU limit (cgroup quota) when it is tighter than the host's
    # cores, else leave torch's default; > 0 forces that many threads. An
    # explicit OMP_NUM_THREADS in the environment is respected when this is 0.
    TORCH_NUM_THREADS: int = 0
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
    # SPEECH_QUALITY_PLAN.md S2.1b: most clips one voice profile may be built from. The
    # whole request is still bounded by MAX_AUDIO_SIZE_MB, so this caps the work per
    # upload, not the bytes.
    VOICE_MAX_SAMPLES: int = Field(default=10, ge=1, le=20)
    MAX_AUDIO_DURATION_SECONDS: float = 300.0
    # HARDENING_PLAN.md finding M9: relative values are anchored to BASE_DIR
    # (backend/) by ``anchor_storage_dir``, never the process CWD; absolute
    # values are used as-is.
    UPLOAD_DIR: str = str(BASE_DIR / "uploads")
    OUTPUT_DIR: str = str(BASE_DIR / "outputs")
    WEIGHTS_DIR: str = str(BASE_DIR / "weights")
    # One directory that holds all three of the above as `uploads/`,
    # `outputs/` and `weights/`, so a host with a single persistent volume
    # (Railway allows one per service) sets one variable, not three. Any of
    # the three set explicitly still wins. Blank (default) leaves them as is.
    DATA_DIR: str = ""
    # When True, `python -m backend.serve` (the container entrypoint) downloads
    # any missing or checksum-failing synthesizer/vocoder checkpoint before
    # starting the API. Off by default: provisioning is otherwise an explicit
    # operator step (backend/download_weights.py --fetch). Turn it on where
    # the weights directory is a fresh volume (e.g. Railway).
    FETCH_WEIGHTS_ON_START: bool = False
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
    # Rate limits for the endpoints that send email (resend-verification,
    # forgot-password) and for the ones that consume an emailed token.
    AUTH_EMAIL_RATE_LIMIT: str = "5/hour"
    AUTH_TOKEN_RATE_LIMIT: str = "20/minute"
    # Silent token renewal by every signed-in client; generous, but bounded so
    # the endpoint cannot be used to hammer the database.
    AUTH_REFRESH_RATE_LIMIT: str = "60/minute"
    # SEC-3: failed password checks allowed per account (login, and the
    # password re-check on account erasure) before it answers 429 for the
    # rest of the window. Complements the per-IP AUTH_LOGIN_RATE_LIMIT, which
    # cannot stop many clients guessing one account.
    AUTH_PASSWORD_FAILURE_LIMIT: str = "10/15 minutes"
    # SEC-3: per-IP ceiling for the ordinary signed-in and redirect endpoints
    # (profile, history, logout, Google redirect/callback), which had none.
    API_RATE_LIMIT: str = "120/minute"
    # SPEECH_QUALITY_PLAN.md S7.2c: the per-IP ceiling on POST /synthesize, scaled to what the active
    # engine costs. The default applies to every engine; SYNTHESIZE_RATE_LIMIT_BY_ENGINE overrides it
    # for the engines named (e.g. {"chatterbox": "2/minute"} for a slow GPU engine). The limit follows
    # TTS_ENGINE, read on each request.
    SYNTHESIZE_RATE_LIMIT: str = "5/minute"
    SYNTHESIZE_RATE_LIMIT_BY_ENGINE: dict[str, str] = Field(default_factory=dict)

    # HARDENING_PLAN.md finding P2-H1: local signup does not prove ownership of
    # the address. When True (the fail-safe default), an account whose email is
    # unverified may sign in but cannot upload a voice or synthesize. Google
    # accounts count as verified. Set False only for local development without
    # an email provider.
    REQUIRE_EMAIL_VERIFICATION: bool = True
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    # Base URL of the web app; emailed links point at
    # {FRONTEND_URL}/verify-email#token=... and /reset-password#token=...
    # (the token is in the URL fragment, so it never reaches a server log).
    FRONTEND_URL: str = "http://localhost:3000"
    # How outgoing mail is delivered. "disabled" (the default) sends nothing
    # and logs that fact; "console" logs the message INCLUDING its link, for
    # local development only; "resend" uses the Resend HTTPS API; "smtp" uses
    # an SMTP relay. Hosts that block outbound SMTP should use "resend".
    EMAIL_BACKEND: Literal["disabled", "console", "smtp", "resend"] = "disabled"
    EMAIL_FROM: str = ""
    RESEND_API_KEY: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # STARTTLS on the SMTP connection; set False only for a local test relay.
    SMTP_STARTTLS: bool = True
    # HARDENING_PLAN.md finding H6: bound the single process-wide inference
    # semaphore so callers fail fast instead of queuing unbounded.
    # INFERENCE_MAX_WAITERS: requests already queued for a slot beyond this
    # are rejected immediately with 429, never counting the request(s)
    # currently holding the semaphore.
    INFERENCE_MAX_WAITERS: int = 10
    # HARDENING_PLAN.md finding P2-L10: preprocess_audio's decode/resample/trim
    # ran unbounded outside `_inference_semaphore`, so concurrent uploads (the
    # only existing bound is the per-IP rate limit) could each run a full
    # decode in parallel with the forward pass the semaphore protects.
    # PREPROCESS_MAX_CONCURRENCY caps how many of those can run at once.
    PREPROCESS_MAX_CONCURRENCY: int = 4
    # INFERENCE_ACQUIRE_TIMEOUT_SECONDS: max time a queued request waits for
    # a free slot before giving up with 503.
    INFERENCE_ACQUIRE_TIMEOUT_SECONDS: float = 10.0
    # INFERENCE_CALL_TIMEOUT_SECONDS: max wall-clock time for each stage of a
    # held inference call (the encoder; or, separately, the synthesizer and
    # the vocoder) before it is abandoned with 503. The limit applies per
    # stage, not across the call, so a synthesis can take up to twice this
    # (HARDENING_PLAN.md finding P2-L3).
    INFERENCE_CALL_TIMEOUT_SECONDS: float = 30.0
    # HARDENING_PLAN.md finding P2-M3: text is cleaned (digits expanded), then
    # split into chunks of at most this many characters, each synthesized
    # separately. ~150 chars is about 10 s of speech, inside the checkpoint's
    # 900-frame training length.
    TTS_CHUNK_MAX_CHARS: int = 150
    # Silence inserted after a chunk, in seconds, keyed by how the chunk ended
    # (statement, question, exclamation, ellipsis, clause, comma, word, paragraph).
    # Supply only the keys to change; the rest keep their defaults. As an env var:
    # TTS_PAUSE_SECONDS='{"question": 0.6}'. Replaces TTS_CHUNK_PAUSE_SECONDS
    # (SPEECH_QUALITY_PLAN.md S1.3).
    TTS_PAUSE_SECONDS: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_TTS_PAUSE_SECONDS)
    )
    # SPEECH_QUALITY_PLAN.md S4.1: which speech engine serves requests. "sv2tts" runs in this
    # process; the chatterbox* engines run in the separate inference worker (tts_worker/)
    # named by TTS_WORKER_URL (S4.3) and need a GPU there for the full model (Nano also runs
    # on a CPU).
    TTS_ENGINE: Literal[
        "sv2tts", "chatterbox", "chatterbox_turbo", "chatterbox_nano"
    ] = "sv2tts"
    # The inference worker's base URL and the shared bearer token (a secret: keep it in .env).
    # https is required unless the worker is on this machine. The call timeout must stay
    # under INFERENCE_CALL_TIMEOUT_SECONDS so the request thread ends before its stage times out.
    TTS_WORKER_URL: str = ""
    TTS_WORKER_TOKEN: str = ""
    TTS_WORKER_TIMEOUT_SECONDS: float = Field(default=25.0, gt=0.0, le=300.0)
    # SPEECH_QUALITY_PLAN.md S7.4a: canary. This share of users (0-100, chosen by a stable hash of the
    # user id, so a user always gets the same engine) is served by TTS_CANARY_ENGINE instead of
    # TTS_ENGINE. 0 (default) is off. Rolling back is setting it to 0; the kill switch for the engine
    # itself is TTS_ENGINE=sv2tts. Voice upload is not affected: profiles stay engine-neutral.
    TTS_CANARY_ENGINE: Literal[
        "sv2tts", "chatterbox", "chatterbox_turbo", "chatterbox_nano"
    ] = "chatterbox"
    TTS_CANARY_PERCENT: int = Field(default=0, ge=0, le=100)
    # SPEECH_QUALITY_PLAN.md S5.3a: speak an engine that has a delivery control (the original
    # Chatterbox's exaggeration) sentence by sentence, each with its own style from the text
    # analysis, instead of one call for the whole text. Off by default: it costs one worker call
    # per sentence. Engines without such a control are unaffected.
    EMOTION_CONTROL_ENABLED: bool = False
    # SPEECH_QUALITY_PLAN.md S7.4b: canary for the above. While EMOTION_CONTROL_ENABLED is false,
    # this share of users (0-100, a stable hash of the user id, independent of the engine canary)
    # gets it anyway; raising the percentage only adds users. 0 (default) is off.
    EMOTION_CONTROL_PERCENT: int = Field(default=0, ge=0, le=100)
    # SPEECH_QUALITY_PLAN.md S7.2b: add an inaudible watermark (AudioSeal) to every synthesized
    # WAV, so a clip can be traced to this service after it is re-encoded. Fail closed: if it
    # cannot be applied the request fails rather than serving unmarked audio. The 12-bit tag
    # identifies this deployment in the message the watermark carries. Weights come from
    # `python -m backend.download_weights --fetch` (checksum-pinned); nothing downloads at run time.
    WATERMARK_ENABLED: bool = True
    WATERMARK_TAG: int = Field(default=0xC10, ge=0, le=0xFFF)
    # SPEECH_QUALITY_PLAN.md S4.4: when a worker engine is unavailable (down, timing out,
    # refusing, busy), serve the request with this in-process engine instead of failing it.
    # "none" turns the fallback off. The fallback engine's voice quality is lower: every use
    # is logged and counted (clonevoice_engine_fallback_total).
    TTS_FALLBACK_ENGINE: Literal["none", "sv2tts"] = "sv2tts"
    # After this many unavailable replies in a row the worker is treated as down: requests skip
    # it (and go straight to the fallback) until the cooldown ends, then one request tries it.
    TTS_WORKER_BREAKER_FAILURES: int = Field(default=3, ge=1, le=20)
    TTS_WORKER_BREAKER_COOLDOWN_SECONDS: float = Field(default=30.0, ge=1.0, le=600.0)
    # SPEECH_QUALITY_PLAN.md S3.4: check each synthesis for truncation, silence, clipping
    # and implausible length; on a failure run it again, up to this many attempts in all
    # (each attempt is a full synthesis, so the worst-case latency scales with it), then
    # refuse rather than serve broken audio.
    TTS_QUALITY_GATE_ENABLED: bool = True
    TTS_QUALITY_MAX_ATTEMPTS: int = Field(default=2, ge=1, le=5)
    # SPEECH_QUALITY_PLAN.md S2.5: synthesize this many candidates with the SV2TTS engine and serve
    # the one whose voice is closest to the profile (speaker encoder cosine). 1 = off. Each extra
    # candidate is a full synthesis plus one encoder pass, so latency grows about N-fold: leave it
    # at 1 on a CPU deployment unless the real-time budget allows it.
    TTS_BEST_OF_N: int = Field(default=1, ge=1, le=4)
    # Level every synthesized WAV to OUTPUT_TARGET_LUFS (BS.1770 integrated loudness),
    # never past OUTPUT_PEAK_CEILING_DBFS (true peak), with DC removed and 10 ms edge
    # fades (SPEECH_QUALITY_PLAN.md S3.3). Off = the raw vocoder output, clipped to +-1.
    OUTPUT_NORMALIZE_ENABLED: bool = True
    OUTPUT_TARGET_LUFS: float = Field(default=-18.0, ge=-40.0, le=-6.0)
    OUTPUT_PEAK_CEILING_DBFS: float = Field(default=-1.0, ge=-12.0, le=0.0)
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
    # HARDENING_PLAN.md finding P2-L6: outside APP_ENV=development an empty
    # token no longer means 'open'; /metrics returns 401 until one is set (or
    # METRICS_ENABLED=false).
    METRICS_ENABLED: bool = True
    METRICS_AUTH_TOKEN: str = ""
    STORAGE_MAX_AGE_HOURS: float = 24
    STORAGE_CLEANUP_INTERVAL_SECONDS: float = 3600
    # HARDENING_PLAN.md finding P2-M5: synthesized outputs are protected from
    # pruning only for this many days after creation; after that the WAV is
    # eligible for the normal age-based cleanup (the DB row is kept). 0 or
    # negative keeps every output forever.
    OUTPUT_RETENTION_DAYS: float = 30
    # Responsible use (RU-2): the version of the acceptable-use terms a voice
    # sample upload attests to. Stored on every voice profile beside
    # `consent_confirmed_at`, so a consent can be traced to the exact wording
    # in force. Bump it whenever the terms text changes.
    TERMS_VERSION: str = "2026-09-30"
    # Where the terms text is published (shown by the client next to the
    # consent checkbox). Blank until the page exists.
    TERMS_URL: str = ""
    # HARDENING_PLAN.md finding L5: the engine previously had no
    # pool_pre_ping, pool sizing, or connect timeout, so a stale pooled
    # connection (e.g. after a DB restart or an idle-connection reap by the
    # DB server/proxy) surfaced as a request-time error instead of being
    # transparently recycled. Only meaningful for a real DBAPI (Postgres in
    # production); harmless no-ops are skipped for SQLite in `database.py`,
    # since SQLite has no server-side connection or pool sizing concept.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT_SECONDS: float = 30.0
    # How long a new connection attempt may take before failing, passed as
    # the DBAPI's own `connect_timeout` (psycopg2/Postgres).
    DB_CONNECT_TIMEOUT_SECONDS: float = 10.0
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    @field_validator("TTS_PAUSE_SECONDS")
    @classmethod
    def pauses_are_known_and_bounded(cls, v: dict[str, float]) -> dict[str, float]:
        """Merge overrides onto the defaults; reject unknown keys and out-of-range values."""
        unknown = set(v) - set(DEFAULT_TTS_PAUSE_SECONDS)
        if unknown:
            raise ValueError(
                f"unknown TTS_PAUSE_SECONDS keys {sorted(unknown)}; "
                f"valid: {sorted(DEFAULT_TTS_PAUSE_SECONDS)}"
            )
        merged = {**DEFAULT_TTS_PAUSE_SECONDS, **v}
        for key, seconds in merged.items():
            if not 0.0 <= seconds <= MAX_TTS_PAUSE_SECONDS:
                raise ValueError(
                    f"TTS_PAUSE_SECONDS[{key!r}] must be between 0 and "
                    f"{MAX_TTS_PAUSE_SECONDS:g} seconds"
                )
        return merged

    @field_validator("TORCH_NUM_THREADS")
    @classmethod
    def torch_threads_not_negative(cls, v: int) -> int:
        """Reject negative thread counts; 0 means auto."""
        if v < 0:
            raise ValueError("TORCH_NUM_THREADS must be >= 0 (0 = auto)")
        return v

    @field_validator(
        "AUTH_LOGIN_RATE_LIMIT",
        "AUTH_SIGNUP_RATE_LIMIT",
        "AUTH_EMAIL_RATE_LIMIT",
        "AUTH_TOKEN_RATE_LIMIT",
        "AUTH_REFRESH_RATE_LIMIT",
        "AUTH_PASSWORD_FAILURE_LIMIT",
        "API_RATE_LIMIT",
        "SYNTHESIZE_RATE_LIMIT",
    )
    @classmethod
    def rate_limit_is_parseable(cls, v: str) -> str:
        """Fail at startup on a malformed limit, not on the first request."""
        try:
            parse_rate_limit(v)
        except ValueError:
            raise ValueError(f"not a valid rate limit: {v!r} (e.g. '10/minute')")
        return v

    @field_validator("SYNTHESIZE_RATE_LIMIT_BY_ENGINE")
    @classmethod
    def engine_rate_limits_valid(cls, v: dict[str, str]) -> dict[str, str]:
        """Fail at startup on an unknown engine name or a malformed limit."""
        known = set(get_args(cls.model_fields["TTS_ENGINE"].annotation))
        for engine, limit in v.items():
            if engine not in known:
                raise ValueError(
                    f"SYNTHESIZE_RATE_LIMIT_BY_ENGINE: unknown engine {engine!r}"
                )
            try:
                parse_rate_limit(limit)
            except ValueError:
                raise ValueError(f"not a valid rate limit for {engine!r}: {limit!r}")
        return v

    @field_validator("EMAIL_VERIFICATION_EXPIRE_HOURS", "PASSWORD_RESET_EXPIRE_MINUTES")
    @classmethod
    def token_lifetime_positive(cls, v: int) -> int:
        """Reject a zero or negative lifetime, which would mint dead tokens."""
        if v <= 0:
            raise ValueError("email token lifetimes must be > 0")
        return v

    @model_validator(mode="after")
    def derive_storage_dirs_from_data_dir(self) -> "Settings":
        """Place uploads/outputs/weights under DATA_DIR unless set explicitly."""
        if not self.DATA_DIR.strip():
            return self
        root = Path(self.DATA_DIR).expanduser()
        if not root.is_absolute():
            raise ValueError("DATA_DIR must be an absolute path")
        for field, subdir in (
            ("UPLOAD_DIR", "uploads"),
            ("OUTPUT_DIR", "outputs"),
            ("WEIGHTS_DIR", "weights"),
        ):
            if field not in self.model_fields_set:
                setattr(self, field, str(root / subdir))
        return self

    @model_validator(mode="after")
    def worker_engine_is_configured(self) -> "Settings":
        """Fail at startup on a worker engine with no usable, safe worker settings."""
        canary_on_worker = (
            self.TTS_CANARY_PERCENT > 0 and self.TTS_CANARY_ENGINE != "sv2tts"
        )
        if self.TTS_ENGINE == "sv2tts" and not canary_on_worker:
            return self
        url = urlparse(self.TTS_WORKER_URL)
        if (
            not self.TTS_WORKER_URL
            or not url.hostname
            or url.scheme not in {"http", "https"}
        ):
            raise ValueError(
                f"TTS_ENGINE={self.TTS_ENGINE} (canary {self.TTS_CANARY_ENGINE}, "
                f"{self.TTS_CANARY_PERCENT}%) requires TTS_WORKER_URL (an http(s) URL)"
            )
        if url.scheme != "https" and url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError(
                "TTS_WORKER_URL must be https unless the worker is on this machine: "
                "voice recordings are sent to it"
            )
        if len(self.TTS_WORKER_TOKEN) < 32:
            raise ValueError("TTS_WORKER_TOKEN must be at least 32 characters")
        if self.TTS_WORKER_TIMEOUT_SECONDS >= self.INFERENCE_CALL_TIMEOUT_SECONDS:
            raise ValueError(
                "TTS_WORKER_TIMEOUT_SECONDS must be below INFERENCE_CALL_TIMEOUT_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def email_backend_is_configured(self) -> "Settings":
        """Fail at startup, not at the first signup, on a half-set provider."""
        required = {
            "resend": {"RESEND_API_KEY": self.RESEND_API_KEY},
            "smtp": {"SMTP_HOST": self.SMTP_HOST},
        }.get(self.EMAIL_BACKEND)
        if self.EMAIL_BACKEND != "disabled":
            required = {**(required or {}), "EMAIL_FROM": self.EMAIL_FROM}
        missing = [name for name, value in (required or {}).items() if not value]
        if missing:
            raise ValueError(
                f"EMAIL_BACKEND={self.EMAIL_BACKEND} requires: {', '.join(missing)}"
            )
        return self

    @field_validator("UPLOAD_DIR", "OUTPUT_DIR")
    @classmethod
    def anchor_storage_dir(cls, v: str) -> str:
        """Resolve a relative storage path against BASE_DIR, not the CWD."""
        if not v.strip():
            raise ValueError("storage directory must not be empty")
        path = Path(v).expanduser()
        return str(path if path.is_absolute() else BASE_DIR / path)

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def validate_allowed_origins(cls, origins: List[str]) -> List[str]:
        """Require exact origins: the API allows credentials, so `*` is unsafe."""
        for origin in origins:
            parsed = urlparse(origin)
            exact = f"{parsed.scheme}://{parsed.netloc}"
            if (
                "*" in origin
                or parsed.scheme not in ("http", "https")
                or not parsed.netloc
                or origin != exact
            ):
                raise ValueError(
                    "ALLOWED_ORIGINS entries must be exact origins such as "
                    "https://app.example.com (scheme and host, no wildcard, "
                    f"path or trailing slash); got {origin!r}"
                )
        return origins

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        if v == "secret" or len(v) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters and cannot be 'secret'"
            )
        return v

    @field_validator("SESSION_SECRET_KEY")
    @classmethod
    def validate_session_secret_key(cls, v: str) -> str:
        """Blank (fall back to JWT_SECRET_KEY, see below) or >=32 chars — never
        the literal 'secret', matching JWT_SECRET_KEY's own bar."""
        if v and (v == "secret" or len(v) < 32):
            raise ValueError(
                "SESSION_SECRET_KEY must be at least 32 characters and cannot be "
                "'secret' (or leave it blank to fall back to JWT_SECRET_KEY)"
            )
        return v

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
