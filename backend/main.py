import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdFilter, CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from backend.api.auth import router as auth_router
from backend.api.synthesize import router as synthesize_router
from backend.api.voice import router as voice_router
from backend.core.body_limit import BodySizeLimitMiddleware
from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.core.rate_limit import limiter
from backend.core.sentry import init_sentry
from backend.services.storage_cleanup import periodic_cleanup
from backend.services.tts_pipeline import get_model_health, load_models


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
    logger.info("Application shutting down.")


app = FastAPI(title="CloneVoice API", lifespan=lifespan)

# --- Rate limiting -----------------------------------------------------------
# Attach the limiter so SlowAPI can access it from any route.
# The RateLimitExceeded handler returns a JSON 429 with a clear detail message.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# -----------------------------------------------------------------------------

app.add_middleware(SessionMiddleware, secret_key=settings.JWT_SECRET_KEY)

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


@app.get("/health")
def health():
    """Report application health, verifying the SV2TTS models are actually
    loaded and placed on the configured device rather than trusting a
    static "ok" — so a load balancer never routes traffic to an instance
    whose models failed to load or crashed after startup."""
    model_status = get_model_health(settings.DEVICE)
    ready = model_status.pop("ready")
    payload = {
        "status": "ok" if ready else "degraded",
        "version": "1.0.0",
        "models": model_status,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
