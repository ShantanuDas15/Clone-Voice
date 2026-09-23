"""Voice profile management API routes."""

import asyncio
import logging
import os
import uuid
from typing import List

import numpy as np
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import get_current_user
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.voice import VoiceProfileOut
from backend.services.audio_processing import (preprocess_audio, save_upload,
                                               validate_audio_file)
from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError,
                                           embed_speaker_async)

logger = logging.getLogger(__name__)

router = APIRouter()


def _persist_profile(db: Session, profile: VoiceProfile) -> None:
    """Add, commit, and refresh a voice profile row (run off the event loop)."""
    db.add(profile)
    db.commit()
    db.refresh(profile)


def _remove_quietly(path: str) -> None:
    """Delete a file, logging (not raising) on failure."""
    try:
        os.remove(path)
    except OSError:
        logger.exception("Failed to remove rejected upload: %s", path)


def _is_usable_embedding(embedding: np.ndarray) -> bool:
    """Return True only for a finite, non-zero embedding (never persist a blank one)."""
    return (
        embedding is not None
        and embedding.size > 0
        and bool(np.all(np.isfinite(embedding)))
        and bool(np.any(embedding != 0))
    )


async def _cleanup_failed_upload(
    db: Session, file_path: str, user_id: uuid.UUID, name: str
) -> None:
    """Remove the orphaned upload and persist a `status="failed"` profile row.

    Shared by every embedding-extraction failure path (generic error, queue
    rejection, timeout) so each one leaves the same consistent audit trail.
    """
    try:
        await asyncio.to_thread(os.remove, file_path)
        logger.info("Removed orphaned upload after embedding failure: %s", file_path)
    except OSError:
        logger.exception("Failed to remove orphaned upload: %s", file_path)
    profile = VoiceProfile(
        user_id=user_id,
        name=name,
        audio_sample_path=file_path,
        embedding_path="",
        status="failed",
    )
    await asyncio.to_thread(_persist_profile, db, profile)


@router.post(
    "/upload", response_model=VoiceProfileOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/minute")
async def upload_audio(
    request: Request,
    name: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate, process, and embed an uploaded audio sample."""
    # HARDENING_PLAN.md finding P2-M1: release the connection the auth lookup
    # left open in a transaction before the slow decode/embedding work. The
    # session reconnects lazily when the profile row is persisted.
    user_id = current_user.id
    await asyncio.to_thread(db.close)

    ext = await asyncio.to_thread(validate_audio_file, file)
    file_path = await asyncio.to_thread(save_upload, file, str(user_id), ext)
    logger.info("Audio uploaded by user_id=%s — file=%s", user_id, file_path)

    try:
        y_processed = await asyncio.to_thread(preprocess_audio, file_path)
    except HTTPException:
        # Unusable input (too short/silent/long/undecodable): don't keep the
        # user's audio on disk for a profile that will never exist.
        await asyncio.to_thread(_remove_quietly, file_path)
        raise

    embedding_path = os.path.splitext(file_path)[0] + "_embed.npy"

    try:
        logger.debug("Extracting speaker embedding for user_id=%s", user_id)
        embedding = await embed_speaker_async(y_processed)
        if not _is_usable_embedding(embedding):
            logger.warning(
                "Blank/invalid speaker embedding for user_id=%s — rejecting",
                user_id,
            )
            await asyncio.to_thread(_remove_quietly, file_path)
            raise HTTPException(
                status_code=422,
                detail="Could not extract a voice from this audio. "
                "Please upload a clearer sample.",
            )
        await asyncio.to_thread(np.save, embedding_path, embedding)
        logger.info(
            "Speaker embedding saved: %s (shape=%s)", embedding_path, embedding.shape
        )
    except HTTPException:
        raise
    except InferenceQueueFullError:
        logger.warning(
            "Inference queue full — rejecting upload for user_id=%s", user_id
        )
        await _cleanup_failed_upload(db, file_path, user_id, name)
        raise HTTPException(
            status_code=429,
            detail="Voice profile service is busy. Please try again shortly.",
        )
    except InferenceTimeoutError:
        logger.exception("Embedding extraction timed out for user_id=%s", user_id)
        await _cleanup_failed_upload(db, file_path, user_id, name)
        raise HTTPException(
            status_code=503,
            detail="Voice profile service is temporarily overloaded. Please try again shortly.",
        )
    except Exception:
        logger.exception(
            "Embedding extraction failed for user_id=%s — persisting failed profile",
            user_id,
        )
        await _cleanup_failed_upload(db, file_path, user_id, name)
        raise HTTPException(
            status_code=500, detail="Failed to extract speaker embedding"
        )

    profile = VoiceProfile(
        user_id=user_id,
        name=name,
        audio_sample_path=file_path,
        embedding_path=embedding_path,
        status="ready",
    )
    await asyncio.to_thread(_persist_profile, db, profile)

    logger.info(
        "Voice profile created: id=%s, name=%s, user_id=%s",
        profile.id,
        profile.name,
        user_id,
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
