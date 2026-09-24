import asyncio
import hmac
import logging
import logging.config
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdFilter, CorrelationIdMiddleware
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from backend.api.auth import router as auth_router
from backend.api.synthesize import router as synthesize_router
from backend.api.voice import router as voice_router
from backend.core import metrics
from backend.core.body_limit import BodySizeLimitMiddleware
from backend.core.config import settings
from backend.core.database import SessionLocal, get_db
from backend.core.migrations import check_schema_current
from backend.core.rate_limit import limiter
from backend.core.sentry import init_sentry
from backend.services.storage_cleanup import periodic_cleanup
from backend.services.tts_pipeline import (drain_inflight_inference,
                                           get_model_health, get_warmup_status,
                                           load_models, warmup_inference)


def configure_logging() -> None:
    """Configure structured JSON logging, tagging every record with the request ID."""
    level = "DEBUG" if settings.APP_ENV == "development" else "INFO"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "correlation_id": {
                    "()": CorrelationIdFilter,
                    "uuid_length": 32,
                    "default_value": "-",
                },
            },
            "formatters": {
                "json": {
                    "()": "pythonjsonlogger.json.JsonFormatter",
                    "format": (
                        "%(asctime)s %(levelname)s %(name)s "
                        "%(correlation_id)s %(message)s"
                    ),
                    "rename_fields": {
                        "asctime": "timestamp",
                        "levelname": "level",
                        "name": "logger",
                        "correlation_id": "request_id",
                    },
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "filters": ["correlation_id"],
                },
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
        }
    )


configure_logging()
init_sentry()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events."""
    logger.info("Starting CloneVoice API — loading SV2TTS models...")
    load_models(device=settings.DEVICE)
    if settings.READINESS_WARMUP_ENABLED:
        await warmup_inference()

    cleanup_task = asyncio.create_task(
        periodic_cleanup(
            directories=[settings.UPLOAD_DIR, settings.OUTPUT_DIR],
            interval_seconds=settings.STORAGE_CLEANUP_INTERVAL_SECONDS,
            max_age_hours=settings.STORAGE_MAX_AGE_HOURS,
            session_factory=SessionLocal,
        )
    )
    logger.info(
        "Storage cleanup background task started (every %.0fs, max age %.0fh).",
        settings.STORAGE_CLEANUP_INTERVAL_SECONDS,
        settings.STORAGE_MAX_AGE_HOURS,
    )

    logger.info("Application startup complete.")
    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    # Let running forward passes finish instead of abandoning worker threads
    # mid-inference (HARDENING_PLAN.md finding M6).
    await drain_inflight_inference(settings.INFERENCE_SHUTDOWN_DRAIN_TIMEOUT_SECONDS)
    logger.info("Application shutting down.")


app = FastAPI(title="CloneVoice API", lifespan=lifespan)

# --- Rate limiting -----------------------------------------------------------
# Attach the limiter so SlowAPI can access it from any route.
# The RateLimitExceeded handler returns a JSON 429 with a clear detail message.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# -----------------------------------------------------------------------------


def resolve_session_secret_key(session_secret_key: str, jwt_secret_key: str) -> str:
    """Pick the secret that signs the session cookie (HARDENING_PLAN.md L6).

    The session cookie (authlib's OAuth flow uses it to hold Google login
    state/nonce — see api/auth.py) must not sign with the same secret as JWT
    access/refresh tokens, so a leak of one purpose's secret doesn't
    compromise the other. Falls back to `jwt_secret_key` with a logged
    warning when `session_secret_key` is unset, so existing single-secret
    deployments keep working.

    Args:
        session_secret_key: `settings.SESSION_SECRET_KEY`, blank if unset.
        jwt_secret_key: `settings.JWT_SECRET_KEY`, used as the fallback.

    Returns:
        The secret to pass to `SessionMiddleware`.
    """
    if session_secret_key:
        return session_secret_key
    logger.warning(
        "SESSION_SECRET_KEY is not set — falling back to JWT_SECRET_KEY for the "
        "session cookie. Set a separate SESSION_SECRET_KEY in production "
        "(HARDENING_PLAN.md finding L6)."
    )
    return jwt_secret_key


app.add_middleware(
    SessionMiddleware,
    secret_key=resolve_session_secret_key(
        settings.SESSION_SECRET_KEY, settings.JWT_SECRET_KEY
    ),
)

# Reject oversized bodies before multipart parsing spools them to disk (M5).
# Added before CORS so the 413 still passes through CORS and gets its headers.
app.add_middleware(
    BodySizeLimitMiddleware,
    max_body_bytes=settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
    + settings.REQUEST_BODY_OVERHEAD_KB * 1024,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Correlation/request ID middleware — added last so it wraps every other
# middleware (outermost), guaranteeing a request ID exists for the full
# lifetime of the request, including logs emitted by CORS/session layers.
# The generated ID is echoed back to the client via the X-Request-ID header.
app.add_middleware(CorrelationIdMiddleware, header_name="X-Request-ID")

API_V1_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=f"{API_V1_PREFIX}/auth", tags=["auth"])
app.include_router(voice_router, prefix=f"{API_V1_PREFIX}/voice", tags=["voice"])
app.include_router(
    synthesize_router, prefix=f"{API_V1_PREFIX}/synthesize", tags=["synthesize"]
)


def _check_database(db: Session) -> None:
    """Prove the DB is usable (``SELECT 1``) and migrated to the Alembic head."""
    db.execute(text("SELECT 1"))
    check_schema_current(db)


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics(authorization: str = Header(default="")) -> Response:
    """Expose inference metrics in Prometheus text format (finding M8).

    404 when ``METRICS_ENABLED`` is false; when ``METRICS_AUTH_TOKEN`` is set
    the caller must send it as ``Authorization: Bearer <token>``.
    """
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    token = settings.METRICS_AUTH_TOKEN
    if token and not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)


@app.get("/health/live")
def liveness() -> dict:
    """Liveness probe: the process is up and serving. Checks no dependencies.

    Deliberately never touches the DB or models, so an orchestrator only
    restarts the container when the process itself is wedged — not during a
    DB outage or model problem (HARDENING_PLAN.md finding M7).
    """
    return {"status": "alive"}


@app.get("/health/ready")
@app.get("/health")
async def readiness(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness probe: 200 only when the app can actually serve requests.

    Requires (1) a working DB connection whose ``alembic_version`` is the
    Alembic head revision (``SELECT 1`` plus that check, bounded by
    ``READINESS_DB_TIMEOUT_SECONDS``; HARDENING_PLAN.md finding P2-M2), (2) every SV2TTS model loaded on the
    configured device, and (3) when ``READINESS_WARMUP_ENABLED`` is set, a
    successful startup warm-up forward pass. ``/health`` is kept as an alias
    for backward compatibility. Errors are logged, never returned.
    """
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_check_database, db),
            timeout=settings.READINESS_DB_TIMEOUT_SECONDS,
        )
        database_ok = True
    except Exception:
        logger.exception("Readiness DB check failed.")
        database_ok = False

    model_status = get_model_health(settings.DEVICE)
    models_ready = model_status.pop("ready")
    warmup = get_warmup_status()
    warmup_ok = warmup in ("disabled", "ok")

    ready = database_ok and models_ready and warmup_ok
    payload = {
        "status": "ok" if ready else "degraded",
        "version": "1.0.0",
        "database": {"ok": database_ok},
        "models": model_status,
        "warmup": warmup,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
