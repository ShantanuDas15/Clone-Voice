from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.api.auth import router as auth_router
from backend.api.synthesize import router as synthesize_router
from backend.api.voice import router as voice_router
from backend.core.config import settings
from backend.services.tts_pipeline import load_models


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_models(device=settings.DEVICE)
    yield


app = FastAPI(title="CloneVoice API", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=settings.JWT_SECRET_KEY)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(voice_router, prefix="/api/voice", tags=["voice"])
app.include_router(synthesize_router, prefix="/api/synthesize", tags=["synthesize"])


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
