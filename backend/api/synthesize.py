"""TTS synthesis API routes and history."""

import logging
import os
from typing import List

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.synthesize import GenerationOut, SynthesizeRequest
from backend.services.tts_pipeline import run_inference_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_class=FileResponse)
async def synthesize(
    req: SynthesizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Synthesize speech from text using a given voice profile."""
    profile = (
        db.query(VoiceProfile).filter(VoiceProfile.id == req.voice_profile_id).first()
    )

    if not profile or profile.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Voice profile not found")

    if profile.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to use this voice profile"
        )

    try:
        embedding = np.load(profile.embedding_path)
    except Exception:
        logger.exception("Failed to load embedding for profile_id=%s", profile.id)
        raise HTTPException(
            status_code=500, detail="Failed to load voice profile embedding"
        )

    logger.info(
        "Synthesis started — user_id=%s, profile_id=%s, text_len=%d",
        current_user.id,
        profile.id,
        len(req.text),
    )

    out_path, duration = await run_inference_pipeline(
        req.text, embedding, str(current_user.id)
    )
    logger.info(
        "Synthesis complete — user_id=%s, duration=%.2fs, out=%s",
        current_user.id,
        duration,
        out_path,
    )

    generation = Generation(
        user_id=current_user.id,
        voice_profile_id=profile.id,
        input_text=req.text,
        output_audio_path=out_path,
        duration_seconds=duration,
        status="completed",
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)

    return FileResponse(
        out_path, media_type="audio/wav", filename=f"synthesized_{generation.id}.wav"
    )


@router.get("/history", response_model=List[GenerationOut])
def get_history(
    limit: int = 50,
    offset: int = 0,
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
