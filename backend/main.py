import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager

from asgi_correlation_id import CorrelationIdFilter, CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from backend.api.auth import router as auth_router
from backend.api.synthesize import router as synthesize_router
from backend.api.voice import router as voice_router
from backend.core.config import settings
from backend.core.rate_limit import limiter
from backend.services.storage_cleanup import periodic_cleanup
from backend.services.tts_pipeline import load_models


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

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(voice_router, prefix="/api/voice", tags=["voice"])
app.include_router(synthesize_router, prefix="/api/synthesize", tags=["synthesize"])


@app.get("/health")
def health():
    """Return application health status."""
    return {"status": "ok", "version": "1.0.0"}
