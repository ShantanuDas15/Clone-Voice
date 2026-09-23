"""TTS synthesis API routes and history."""

import asyncio
import logging
import os
from typing import List

import numpy as np
import torch
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import get_current_user
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.synthesize import GenerationOut, SynthesizeRequest
from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError,
                                           free_gpu_memory,
                                           run_inference_pipeline)

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_failed_generation(
    db: Session, user_id, voice_profile_id, text: str
) -> None:
    """Persist a `status="failed"` audit row for an inference error.

    Runs on the error path only — a successful synthesis records its own
    `status="completed"` row after the pipeline returns.
    """
    failed_generation = Generation(
        user_id=user_id,
        voice_profile_id=voice_profile_id,
        input_text=text,
        output_audio_path=None,
        duration_seconds=None,
        status="failed",
    )
    db.add(failed_generation)
    db.commit()


def _persist_generation(db: Session, generation: Generation) -> None:
    """Add, commit, and refresh a completed generation row (run off the event loop)."""
    db.add(generation)
    db.commit()
    db.refresh(generation)


@router.post("", response_class=FileResponse)
@limiter.limit("5/minute")
async def synthesize(
    request: Request,
    req: SynthesizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synthesize speech from text using a given voice profile."""
    profile = await asyncio.to_thread(
        lambda: db.query(VoiceProfile)
        .filter(VoiceProfile.id == req.voice_profile_id)
        .first()
    )

    if not profile or profile.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Voice profile not found")

    if profile.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to use this voice profile"
        )

    if profile.status != "ready":
        # e.g. a "failed" profile has no embedding; a 4xx beats np.load("") -> 500.
        raise HTTPException(
            status_code=409,
            detail="Voice profile is not ready for synthesis",
        )

    # HARDENING_PLAN.md finding P2-M1: the auth lookup and profile query left a
    # transaction (and its pooled connection) open on this session. Copy what
    # inference needs into plain locals and release the connection now, so a
    # request queued for or running inference doesn't hold one "idle in
    # transaction". The session reconnects lazily for the persist below.
    user_id = current_user.id
    profile_id = profile.id
    embedding_path = profile.embedding_path
    await asyncio.to_thread(db.close)

    try:
        embedding = await asyncio.to_thread(np.load, embedding_path)
    except Exception:
        logger.exception("Failed to load embedding for profile_id=%s", profile_id)
        raise HTTPException(
            status_code=500, detail="Failed to load voice profile embedding"
        )

    logger.info(
        "Synthesis started — user_id=%s, profile_id=%s, text_len=%d",
        user_id,
        profile_id,
        len(req.text),
    )

    try:
        out_path, duration = await run_inference_pipeline(
            req.text, embedding, str(user_id)
        )
    except InferenceQueueFullError:
        logger.warning(
            "Inference queue full — rejecting synthesis request — "
            "user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        raise HTTPException(
            status_code=429,
            detail="Synthesis service is busy. Please try again shortly.",
        )
    except InferenceTimeoutError:
        logger.exception(
            "Inference timed out — user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        await asyncio.to_thread(
            _record_failed_generation, db, user_id, profile_id, req.text
        )
        free_gpu_memory()
        raise HTTPException(
            status_code=503,
            detail="Synthesis service is temporarily overloaded. Please try again shortly.",
        )
    except torch.cuda.OutOfMemoryError:
        logger.exception(
            "GPU OOM during synthesis — user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        await asyncio.to_thread(
            _record_failed_generation, db, user_id, profile_id, req.text
        )
        free_gpu_memory()
        raise HTTPException(
            status_code=503,
            detail="Synthesis service is temporarily overloaded. Please try again shortly.",
        )
    except Exception:
        logger.exception(
            "Synthesis pipeline failed — user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        await asyncio.to_thread(
            _record_failed_generation, db, user_id, profile_id, req.text
        )
        free_gpu_memory()
        raise HTTPException(
            status_code=500,
            detail="Speech synthesis failed. Please try again later.",
        )

    logger.info(
        "Synthesis complete — user_id=%s, duration=%.2fs, out=%s",
        user_id,
        duration,
        out_path,
    )

    generation = Generation(
        user_id=user_id,
        voice_profile_id=profile_id,
        input_text=req.text,
        output_audio_path=out_path,
        duration_seconds=duration,
        status="completed",
    )
    await asyncio.to_thread(_persist_generation, db, generation)

    return FileResponse(
        out_path, media_type="audio/wav", filename=f"synthesized_{generation.id}.wav"
    )


@router.get("/history", response_model=List[GenerationOut])
def get_history(
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return paginated synthesis history for the current user."""
    if limit > 50:
        limit = 50

    generations = (
        db.query(Generation)
        .join(VoiceProfile, Generation.voice_profile_id == VoiceProfile.id)
        .filter(Generation.user_id == current_user.id, VoiceProfile.deleted_at == None)
        .order_by(Generation.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.debug(
        "History fetched — user_id=%s, count=%d", current_user.id, len(generations)
    )

    results = []
    for gen in generations:
        filename = (
            os.path.basename(gen.output_audio_path) if gen.output_audio_path else ""
        )
        results.append(
            GenerationOut(
                id=gen.id,
                voice_profile_id=gen.voice_profile_id,
                input_text=gen.input_text,
                output_filename=filename,
                duration_seconds=gen.duration_seconds,
                created_at=gen.created_at,
            )
        )

    return results
