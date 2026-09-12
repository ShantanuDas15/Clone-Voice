import logging
import logging.config
from contextlib import asynccontextmanager

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
from backend.services.tts_pipeline import load_models


def configure_logging() -> None:
    """Configure structured logging for the application."""
    level = "DEBUG" if settings.APP_ENV == "development" else "INFO"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
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
    logger.info("Application startup complete.")
    yield
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

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(voice_router, prefix="/api/voice", tags=["voice"])
app.include_router(synthesize_router, prefix="/api/synthesize", tags=["synthesize"])


@app.get("/health")
def health():
    """Return application health status."""
    return {"status": "ok", "version": "1.0.0"}
