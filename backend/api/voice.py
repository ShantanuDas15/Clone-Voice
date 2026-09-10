"""Voice profile management API routes."""

import logging
import uuid
from typing import List

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.voice import VoiceProfileOut
from backend.services.audio_processing import (
    preprocess_audio,
    save_upload,
    validate_audio_file,
)
from backend.services.tts_pipeline import embed_speaker

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/upload", response_model=VoiceProfileOut, status_code=status.HTTP_201_CREATED
)
async def upload_audio(
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate, process, and embed an uploaded audio sample."""
    validate_audio_file(file)
    file_path = save_upload(file, str(current_user.id))
    logger.info("Audio uploaded by user_id=%s — file=%s", current_user.id, file_path)

    y_processed = preprocess_audio(file_path)

    embedding_path = file_path.replace(".wav", "_embed.npy").replace(
        ".mp3", "_embed.npy"
    )

    try:
        logger.debug("Extracting speaker embedding for user_id=%s", current_user.id)
        embedding = embed_speaker(y_processed)
        np.save(embedding_path, embedding)
        logger.info(
            "Speaker embedding saved: %s (shape=%s)", embedding_path, embedding.shape
        )
    except Exception:
        logger.exception(
            "Embedding extraction failed for user_id=%s — persisting failed profile",
            current_user.id,
        )
        profile = VoiceProfile(
            user_id=current_user.id,
            name=name,
            audio_sample_path=file_path,
            embedding_path="",
            status="failed",
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
        raise HTTPException(
            status_code=500, detail="Failed to extract speaker embedding"
        )

    profile = VoiceProfile(
        user_id=current_user.id,
        name=name,
        audio_sample_path=file_path,
        embedding_path=embedding_path,
        status="ready",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    logger.info(
        "Voice profile created: id=%s, name=%s, user_id=%s",
        profile.id,
        profile.name,
        current_user.id,
    )
    return profile


@router.get("/profiles", response_model=List[VoiceProfileOut])
def get_profiles(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """List all active voice profiles for the current user."""
    profiles = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.user_id == current_user.id, VoiceProfile.deleted_at == None
        )
        .all()
    )
    logger.debug(
        "Listed %d voice profiles for user_id=%s", len(profiles), current_user.id
    )
    return profiles


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a voice profile belonging to the current user."""
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")

    profile = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.id == pid,
            VoiceProfile.user_id == current_user.id,
            VoiceProfile.deleted_at == None,
        )
        .first()
    )

    if not profile:
        raise HTTPException(status_code=404, detail="Voice profile not found")

    profile.deleted_at = func.now()
    db.commit()
    logger.info("Voice profile soft-deleted: id=%s by user_id=%s", pid, current_user.id)
    return {"status": "deleted"}
