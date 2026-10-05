"""Voice profile management API routes."""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.db_errors import db_unavailable, is_transient_db_error
from backend.core.rate_limit import limiter
from backend.core.security import get_current_user, get_verified_user
from backend.core.validators import require_nonblank_name
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.voice import VoiceProfileOut
from backend.services.audio_processing import (preprocess_audio,
                                               preprocess_semaphore,
                                               save_upload,
                                               validate_audio_file)
from backend.services.erasure import erase_voice_profile, remove_files
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
    db: Session,
    file_path: str,
    user_id: uuid.UUID,
    name: str,
    consent_confirmed_at: datetime,
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
        consent_confirmed_at=consent_confirmed_at,
        terms_version=settings.TERMS_VERSION,
    )
    try:
        await asyncio.to_thread(_persist_profile, db, profile)
    except SQLAlchemyError:
        # HARDENING_PLAN.md P2-L2: the caller re-raises its own status code;
        # a DB error while recording the failure must not replace it.
        logger.exception("Failed to persist failed profile for user_id=%s", user_id)
        await asyncio.to_thread(db.rollback)


@router.post(
    "/upload", response_model=VoiceProfileOut, status_code=status.HTTP_201_CREATED
)
@limiter.limit("10/minute")
async def upload_audio(
    request: Request,
    name: str = Form(..., min_length=1, max_length=255),
    consent_confirmed: bool = Form(...),
    terms_version: Optional[str] = Form(None, max_length=50),
    file: UploadFile = File(...),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Validate, process, and embed an uploaded audio sample."""
    # HARDENING_PLAN.md finding P2-L1: `Form(min_length=1)` alone still
    # accepts a whitespace-only name; reject it before any file work.
    try:
        name = require_nonblank_name(name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    # Responsible-use safeguard: require an explicit attestation that the
    # uploader has the right to use this voice sample, before any file work.
    # Captured once so every profile row from this request (success or
    # failure) records the same consent timestamp.
    if not consent_confirmed:
        raise HTTPException(
            status_code=422,
            detail="You must confirm you have the right to use this voice sample.",
        )
    # The attestation is only meaningful against the wording the user saw. A
    # client that says which version it showed must match the current one;
    # otherwise the terms changed under it and it has to ask again. Omitting
    # the field is still accepted (the current version is recorded).
    if terms_version is not None and terms_version != settings.TERMS_VERSION:
        raise HTTPException(
            status_code=409,
            detail="The terms have changed (current version "
            f"{settings.TERMS_VERSION}). Review them and confirm again.",
        )
    consent_confirmed_at = datetime.now(timezone.utc)

    # HARDENING_PLAN.md finding P2-M1: release the connection the auth lookup
    # left open in a transaction before the slow decode/embedding work. The
    # session reconnects lazily when the profile row is persisted.
    user_id = current_user.id
    await asyncio.to_thread(db.close)

    ext = await asyncio.to_thread(validate_audio_file, file)
    file_path = await asyncio.to_thread(save_upload, file, str(user_id), ext)
    logger.info("Audio uploaded by user_id=%s — file=%s", user_id, file_path)

    try:
        # HARDENING_PLAN.md finding P2-L10: bound how many uploads decode
        # audio at once, so this doesn't compete unbounded with the model
        # forward pass the inference semaphore protects.
        async with preprocess_semaphore:
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
        await _cleanup_failed_upload(db, file_path, user_id, name, consent_confirmed_at)
        raise HTTPException(
            status_code=429,
            detail="Voice profile service is busy. Please try again shortly.",
        )
    except InferenceTimeoutError:
        logger.exception("Embedding extraction timed out for user_id=%s", user_id)
        await _cleanup_failed_upload(db, file_path, user_id, name, consent_confirmed_at)
        raise HTTPException(
            status_code=503,
            detail="Voice profile service is temporarily overloaded. Please try again shortly.",
        )
    except Exception:
        logger.exception(
            "Embedding extraction failed for user_id=%s — persisting failed profile",
            user_id,
        )
        await _cleanup_failed_upload(db, file_path, user_id, name, consent_confirmed_at)
        raise HTTPException(
            status_code=500, detail="Failed to extract speaker embedding"
        )

    profile = VoiceProfile(
        user_id=user_id,
        name=name,
        audio_sample_path=file_path,
        embedding_path=embedding_path,
        status="ready",
        consent_confirmed_at=consent_confirmed_at,
        terms_version=settings.TERMS_VERSION,
    )
    try:
        await asyncio.to_thread(_persist_profile, db, profile)
    except SQLAlchemyError as error:
        # HARDENING_PLAN.md P2-L2: no row will reference these files.
        logger.exception("Failed to persist voice profile for user_id=%s", user_id)
        await asyncio.to_thread(db.rollback)
        await asyncio.to_thread(_remove_quietly, file_path)
        await asyncio.to_thread(_remove_quietly, embedding_path)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(status_code=500, detail="Failed to save voice profile")

    logger.info(
        "Voice profile created: id=%s, name=%s, user_id=%s",
        profile.id,
        profile.name,
        user_id,
    )
    return profile


@router.get("/profiles", response_model=List[VoiceProfileOut])
@limiter.limit(settings.API_RATE_LIMIT)
def get_profiles(
    request: Request,
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """List all active voice profiles for the current user, newest first."""
    profiles = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.user_id == current_user.id, VoiceProfile.deleted_at == None
        )
        .order_by(VoiceProfile.created_at.desc())
        .all()
    )
    logger.debug(
        "Listed %d voice profiles for user_id=%s", len(profiles), current_user.id
    )
    return profiles


@router.delete("/profiles/{profile_id}")
@limiter.limit(settings.API_RATE_LIMIT)
def delete_profile(
    request: Request,
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

    # SEC-2: the cloned outputs and the voice's own files go with the profile.
    files = erase_voice_profile(db, profile)
    db.commit()
    remove_files(files)
    logger.info("Voice profile soft-deleted: id=%s by user_id=%s", pid, current_user.id)
    return {"status": "deleted"}
