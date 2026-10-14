"""Voice profile management API routes."""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional

import numpy as np
from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request,
                     UploadFile, status)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.db_errors import db_unavailable, is_transient_db_error
from backend.core.rate_limit import limiter
from backend.core.security import get_current_user, get_verified_user
from backend.core.validators import require_nonblank_name
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.models.voice_profile_sample import VoiceProfileSample
from backend.schemas.voice import (QualityOut, SampleOut, VoiceProfileOut,
                                   VoiceProfileUploadOut)
from backend.services.audio_processing import (preprocess_audio,
                                               preprocess_semaphore,
                                               save_upload,
                                               validate_audio_file)
from backend.services.audio_quality import assess_file
from backend.services.erasure import erase_voice_profile, remove_files
from backend.services.tts_engine import get_engine
from backend.services.tts_pipeline import (InferenceQueueFullError,
                                           InferenceTimeoutError)
from backend.services.voice_embedding import (CLIP_AGREEMENT_WARN,
                                              EMBEDDING_VERSION,
                                              aggregate_embeddings,
                                              clip_agreement, find_outliers,
                                              is_usable_embedding)

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


async def _assess_quality_quietly(file_path: str) -> Optional[QualityOut]:
    """Assess the saved upload's recording quality; return ``None`` rather than ever failing.

    The report is advice (SPEECH_QUALITY_PLAN.md S2.2). A problem measuring it must not
    cost the user a profile that was otherwise created, so any error is logged and swallowed.
    """
    try:
        async with preprocess_semaphore:
            report = await asyncio.to_thread(assess_file, file_path)
        return QualityOut.from_report(report)
    except Exception:
        logger.warning("Recording-quality assessment failed", exc_info=True)
        return None


def _is_usable_embedding(embedding: np.ndarray) -> bool:
    """Return True only for a finite, non-zero embedding (never persist a blank one)."""
    return is_usable_embedding(embedding)


async def _cleanup_failed_upload(
    db: Session,
    file_paths: List[str],
    user_id: uuid.UUID,
    name: str,
    consent_confirmed_at: datetime,
) -> None:
    """Remove every orphaned file and persist a `status="failed"` profile row.

    Shared by every embedding-extraction failure path (generic error, queue
    rejection, timeout) so each one leaves the same consistent audit trail.
    The row records the first clip's path, as it did when a profile had one.
    """
    for file_path in file_paths:
        try:
            await asyncio.to_thread(os.remove, file_path)
            logger.info(
                "Removed orphaned upload after embedding failure: %s", file_path
            )
        except OSError:
            logger.exception("Failed to remove orphaned upload: %s", file_path)
    profile = VoiceProfile(
        user_id=user_id,
        name=name,
        audio_sample_path=file_paths[0] if file_paths else "",
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


@dataclass
class _Clip:
    """One processed enrolment clip."""

    audio_path: str
    embedding_path: str
    embedding: np.ndarray
    quality: Optional[QualityOut]


_RATING_ORDER = {"good": 0, "fair": 1, "poor": 2}


def _collect_uploads(
    file: Optional[UploadFile], files: Optional[List[UploadFile]]
) -> List[UploadFile]:
    """Return the clips of this request (``file`` first), or raise 422 if none or too many."""
    uploads = ([file] if file is not None else []) + list(files or [])
    if not uploads:
        raise HTTPException(status_code=422, detail="Upload at least one audio sample.")
    if len(uploads) > settings.VOICE_MAX_SAMPLES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many samples: at most {settings.VOICE_MAX_SAMPLES} per voice.",
        )
    return uploads


async def _process_clip(
    upload: UploadFile, user_id: uuid.UUID, created: List[str]
) -> _Clip:
    """Validate, save, preprocess and embed one clip.

    Every file written is appended to ``created`` as soon as it exists, so the caller
    can remove them all if any clip (this or a later one) fails.
    """
    ext = await asyncio.to_thread(validate_audio_file, upload)
    file_path = await asyncio.to_thread(save_upload, upload, str(user_id), ext)
    created.append(file_path)
    logger.info("Audio uploaded by user_id=%s — file=%s", user_id, file_path)

    # HARDENING_PLAN.md finding P2-L10: bound how many uploads decode
    # audio at once, so this doesn't compete unbounded with the model
    # forward pass the inference semaphore protects.
    async with preprocess_semaphore:
        y_processed = await asyncio.to_thread(preprocess_audio, file_path)

    logger.debug("Extracting speaker embedding for user_id=%s", user_id)
    embedding = (await get_engine().prepare_voice(y_processed)).embedding
    if not _is_usable_embedding(embedding):
        logger.warning(
            "Blank/invalid speaker embedding for user_id=%s — rejecting", user_id
        )
        raise HTTPException(
            status_code=422,
            detail="Could not extract a voice from this audio. "
            "Please upload a clearer sample.",
        )
    embedding_path = os.path.splitext(file_path)[0] + "_embed.npy"
    await asyncio.to_thread(np.save, embedding_path, embedding)
    created.append(embedding_path)
    logger.info(
        "Speaker embedding saved: %s (shape=%s)", embedding_path, embedding.shape
    )
    quality = await _assess_quality_quietly(file_path)
    return _Clip(file_path, embedding_path, embedding, quality)


async def _process_clips(
    uploads: List[UploadFile],
    user_id: uuid.UUID,
    created: List[str],
    on_failure: Optional[Callable[[], Awaitable[None]]] = None,
) -> List[_Clip]:
    """Process every clip, or clean up and raise the HTTP error for the first failure.

    Unusable input removes every file written so far. An infrastructure failure (queue full,
    timeout, any other error) awaits ``on_failure`` instead when given (the upload records a
    ``failed`` profile row there); otherwise it removes the files, as for unusable input.
    """

    async def discard() -> None:
        if on_failure is not None:
            await on_failure()
            return
        for path in created:
            await asyncio.to_thread(_remove_quietly, path)

    clips: List[_Clip] = []
    try:
        for upload in uploads:
            clips.append(await _process_clip(upload, user_id, created))
    except HTTPException:
        # Unusable input (too short/silent/long/undecodable, blank embedding): don't keep
        # any of the user's audio on disk for a profile that will never exist.
        for path in created:
            await asyncio.to_thread(_remove_quietly, path)
        raise
    except InferenceQueueFullError:
        logger.warning(
            "Inference queue full — rejecting upload for user_id=%s", user_id
        )
        await discard()
        raise HTTPException(
            status_code=429,
            detail="Voice profile service is busy. Please try again shortly.",
        )
    except InferenceTimeoutError:
        logger.exception("Embedding extraction timed out for user_id=%s", user_id)
        await discard()
        raise HTTPException(
            status_code=503,
            detail="Voice profile service is temporarily overloaded. Please try again shortly.",
        )
    except Exception:
        logger.exception("Embedding extraction failed for user_id=%s", user_id)
        await discard()
        raise HTTPException(
            status_code=500, detail="Failed to extract speaker embedding"
        )
    return clips


async def _save_profile_embedding(
    embeddings: List[np.ndarray], directory: str, created: List[str]
) -> str:
    """Save the aggregate of several clip embeddings in ``directory``; return its path."""
    path = os.path.join(directory, f"{uuid.uuid4()}_profile_embed.npy")
    await asyncio.to_thread(np.save, path, aggregate_embeddings(embeddings))
    created.append(path)
    return path


def _check_terms(consent_confirmed: bool, terms_version: Optional[str]) -> None:
    """Raise 422/409 unless the uploader attested to the current terms."""
    # Responsible-use safeguard: require an explicit attestation that the
    # uploader has the right to use this voice sample, before any file work.
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


def _quality_json(quality: Optional[QualityOut]) -> Optional[dict]:
    """The quality report as the JSON stored on a sample row, or None when there is none."""
    return quality.model_dump() if quality is not None else None


def _samples_out(rows: List[VoiceProfileSample]) -> List[SampleOut]:
    """Per-clip response entries from stored rows (flagging uses the upload's rule: 3+ clips)."""
    many = len(rows) >= 3
    return [
        SampleOut(
            position=row.position,
            agreement=round(row.agreement, 4),
            mismatch=many and row.agreement < CLIP_AGREEMENT_WARN,
            quality=QualityOut.model_validate(row.quality) if row.quality else None,
        )
        for row in rows
    ]


def _profile_out(profile: VoiceProfile) -> VoiceProfileOut:
    """A profile with its clips, built from the stored rows."""
    return VoiceProfileOut(
        id=profile.id,
        name=profile.name,
        status=profile.status,
        consent_confirmed_at=profile.consent_confirmed_at,
        terms_version=profile.terms_version,
        created_at=profile.created_at,
        embedding_version=profile.embedding_version,
        samples=_samples_out(list(profile.samples)),
    )


def _build_profile(
    user_id: uuid.UUID,
    name: str,
    consent_confirmed_at: datetime,
    clips: List[_Clip],
    profile_embedding_path: str,
    agreement: List[float],
) -> VoiceProfile:
    """Build the ready profile row with one sample row per clip."""
    return VoiceProfile(
        user_id=user_id,
        name=name,
        audio_sample_path=clips[0].audio_path,
        embedding_path=profile_embedding_path,
        embedding_version=EMBEDDING_VERSION,
        status="ready",
        consent_confirmed_at=consent_confirmed_at,
        terms_version=settings.TERMS_VERSION,
        samples=[
            VoiceProfileSample(
                position=i,
                audio_path=clip.audio_path,
                embedding_path=clip.embedding_path,
                agreement=agreement[i],
                quality=_quality_json(clip.quality),
            )
            for i, clip in enumerate(clips)
        ],
    )


@router.post(
    "/upload",
    response_model=VoiceProfileUploadOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def upload_audio(
    request: Request,
    name: str = Form(..., min_length=1, max_length=255),
    consent_confirmed: bool = Form(...),
    terms_version: Optional[str] = Form(None, max_length=50),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Validate, process and embed one audio sample, or several clips of one speaker.

    Send a single clip as ``file`` (as before) and/or several as ``files``. Several clips
    are averaged into one steadier voice embedding (SPEECH_QUALITY_PLAN.md S2.1). If any
    clip fails, none is kept and no profile is created.
    """
    # HARDENING_PLAN.md finding P2-L1: `Form(min_length=1)` alone still
    # accepts a whitespace-only name; reject it before any file work.
    try:
        name = require_nonblank_name(name)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))

    _check_terms(consent_confirmed, terms_version)
    uploads = _collect_uploads(file, files)
    consent_confirmed_at = datetime.now(timezone.utc)

    # HARDENING_PLAN.md finding P2-M1: release the connection the auth lookup
    # left open in a transaction before the slow decode/embedding work. The
    # session reconnects lazily when the profile row is persisted.
    user_id = current_user.id
    await asyncio.to_thread(db.close)

    created: List[str] = []
    clips = await _process_clips(
        uploads,
        user_id,
        created,
        lambda: _cleanup_failed_upload(
            db, created, user_id, name, consent_confirmed_at
        ),
    )

    embeddings = [clip.embedding for clip in clips]
    agreement = clip_agreement(embeddings)
    mismatched = set(find_outliers(embeddings, CLIP_AGREEMENT_WARN))
    if mismatched:
        logger.warning(
            "Clips %s of user_id=%s disagree with the rest of the profile",
            sorted(mismatched),
            user_id,
        )
    if len(clips) == 1:
        # One clip: the profile embedding *is* the clip's, exactly as before S2.1b.
        profile_embedding_path = clips[0].embedding_path
    else:
        profile_embedding_path = await _save_profile_embedding(
            embeddings, os.path.dirname(clips[0].audio_path), created
        )

    profile = _build_profile(
        user_id, name, consent_confirmed_at, clips, profile_embedding_path, agreement
    )
    try:
        await asyncio.to_thread(_persist_profile, db, profile)
    except SQLAlchemyError as error:
        # HARDENING_PLAN.md P2-L2: no row will reference these files.
        logger.exception("Failed to persist voice profile for user_id=%s", user_id)
        await asyncio.to_thread(db.rollback)
        for path in created:
            await asyncio.to_thread(_remove_quietly, path)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(status_code=500, detail="Failed to save voice profile")

    logger.info(
        "Voice profile created: id=%s, name=%s, user_id=%s, clips=%d",
        profile.id,
        profile.name,
        user_id,
        len(clips),
    )
    reports = [clip.quality for clip in clips]
    rated = [q for q in reports if q is not None]
    worst = max(rated, key=lambda q: _RATING_ORDER[q.rating]) if rated else None
    return VoiceProfileUploadOut(
        id=profile.id,
        name=profile.name,
        status=profile.status,
        consent_confirmed_at=profile.consent_confirmed_at,
        terms_version=profile.terms_version,
        created_at=profile.created_at,
        quality=worst,
        samples=_samples_out(list(profile.samples)),
    )


@dataclass
class _Existing:
    """A profile's stored state, read before the slow work so the session can be released."""

    old_embedding_path: str
    clip_count: int
    clip_embedding_paths: List[str]
    embeddings: List[np.ndarray]
    legacy_audio_path: Optional[str]
    legacy_embedding_path: Optional[str]
    directory: str


def _load_existing(db: Session, user_id: uuid.UUID, profile_id: uuid.UUID) -> _Existing:
    """Read the profile's clips and embeddings, or raise 404/409 if it cannot take a clip."""
    profile = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_id == user_id,
            VoiceProfile.deleted_at == None,
        )
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    if profile.status != "ready":
        raise HTTPException(status_code=409, detail="This voice profile is not ready.")
    if profile.embedding_version not in (None, EMBEDDING_VERSION):
        raise HTTPException(
            status_code=409,
            detail="This voice profile was made by an older engine and cannot take "
            "another clip. Upload a new profile.",
        )
    # A profile from before S2.1b has no sample rows: its one clip is the profile's own.
    legacy = not profile.samples
    clips = (
        [(profile.audio_sample_path, profile.embedding_path)]
        if legacy
        else [(s.audio_path, s.embedding_path) for s in profile.samples]
    )
    try:
        embeddings = [np.load(embedding_path) for _, embedding_path in clips]
    except (OSError, ValueError):
        logger.exception("Stored clip embedding unreadable for profile %s", profile_id)
        raise HTTPException(
            status_code=409,
            detail="This voice profile's stored clips are unavailable. Upload a new profile.",
        )
    return _Existing(
        old_embedding_path=profile.embedding_path,
        clip_count=len(clips),
        clip_embedding_paths=[embedding_path for _, embedding_path in clips],
        embeddings=embeddings,
        legacy_audio_path=clips[0][0] if legacy else None,
        legacy_embedding_path=clips[0][1] if legacy else None,
        directory=os.path.dirname(clips[0][0]),
    )


def _attach_clips(
    db: Session,
    user_id: uuid.UUID,
    profile_id: uuid.UUID,
    existing: _Existing,
    clips: List[_Clip],
    profile_embedding_path: str,
    agreement: List[float],
) -> None:
    """Add the new sample rows and swap in the new aggregate embedding, in one commit."""
    profile = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_id == user_id,
            VoiceProfile.deleted_at == None,
        )
        .first()
    )
    # Another request changed or deleted the profile while the clips were processed.
    if profile is None or len(profile.samples) != (
        0 if existing.legacy_audio_path else existing.clip_count
    ):
        raise HTTPException(
            status_code=409, detail="The voice profile changed. Please try again."
        )
    if existing.legacy_audio_path:
        profile.samples.append(
            VoiceProfileSample(
                position=0,
                audio_path=existing.legacy_audio_path,
                embedding_path=existing.legacy_embedding_path,
                agreement=0.0,
            )
        )
    for i, clip in enumerate(clips, start=existing.clip_count):
        profile.samples.append(
            VoiceProfileSample(
                position=i,
                audio_path=clip.audio_path,
                embedding_path=clip.embedding_path,
                agreement=0.0,
                quality=_quality_json(clip.quality),
            )
        )
    for sample, score in zip(profile.samples, agreement):
        sample.agreement = score
    profile.embedding_path = profile_embedding_path
    profile.embedding_version = EMBEDDING_VERSION
    db.commit()


@router.post(
    "/profiles/{profile_id}/samples",
    response_model=VoiceProfileUploadOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def add_samples(
    request: Request,
    profile_id: str,
    consent_confirmed: bool = Form(...),
    terms_version: Optional[str] = Form(None, max_length=50),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Add clips of the same speaker to an existing profile and re-derive its embedding.

    The profile embedding becomes the mean over every clip, old and new (SPEECH_QUALITY_PLAN.md
    S2.1c). If any new clip fails, none is kept and the profile is unchanged. The response lists
    every clip with its stored recording-quality report.
    """
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")
    _check_terms(consent_confirmed, terms_version)
    uploads = _collect_uploads(file, files)

    user_id = current_user.id
    existing = await asyncio.to_thread(_load_existing, db, user_id, pid)
    if existing.clip_count + len(uploads) > settings.VOICE_MAX_SAMPLES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many samples: a voice holds at most {settings.VOICE_MAX_SAMPLES} "
            f"and this one has {existing.clip_count}.",
        )
    # Release the connection before the slow decode/embedding work (HARDENING_PLAN.md P2-M1).
    await asyncio.to_thread(db.close)

    created: List[str] = []
    clips = await _process_clips(uploads, user_id, created)
    embeddings = existing.embeddings + [clip.embedding for clip in clips]
    agreement = clip_agreement(embeddings)
    mismatched = set(find_outliers(embeddings, CLIP_AGREEMENT_WARN))
    if mismatched:
        logger.warning(
            "Clips %s of profile %s disagree with the rest", sorted(mismatched), pid
        )
    profile_embedding_path = await _save_profile_embedding(
        embeddings, existing.directory, created
    )
    try:
        await asyncio.to_thread(
            _attach_clips,
            db,
            user_id,
            pid,
            existing,
            clips,
            profile_embedding_path,
            agreement,
        )
    except (HTTPException, SQLAlchemyError) as error:
        # No row will reference the new files; the profile keeps its old embedding.
        await asyncio.to_thread(db.rollback)
        for path in created:
            await asyncio.to_thread(_remove_quietly, path)
        if isinstance(error, HTTPException):
            raise
        logger.exception("Failed to add clips to profile %s", pid)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(status_code=500, detail="Failed to save voice profile")

    # The old aggregate is now unreferenced, unless it was a lone clip's own embedding.
    if existing.old_embedding_path not in existing.clip_embedding_paths:
        await asyncio.to_thread(_remove_quietly, existing.old_embedding_path)

    logger.info(
        "Clips added to profile %s by user_id=%s: +%d (now %d)",
        pid,
        user_id,
        len(clips),
        len(embeddings),
    )
    rated = [c.quality for c in clips if c.quality is not None]
    worst = max(rated, key=lambda q: _RATING_ORDER[q.rating]) if rated else None
    profile = await asyncio.to_thread(_reload_profile, db, pid)
    return VoiceProfileUploadOut(
        id=profile.id,
        name=profile.name,
        status=profile.status,
        consent_confirmed_at=profile.consent_confirmed_at,
        terms_version=profile.terms_version,
        created_at=profile.created_at,
        embedding_version=profile.embedding_version,
        quality=worst,
        samples=_samples_out(list(profile.samples)),
    )


def _reload_profile(db: Session, profile_id: uuid.UUID) -> VoiceProfile:
    """Return the committed profile row (the session was closed during the slow work)."""
    return db.query(VoiceProfile).filter(VoiceProfile.id == profile_id).one()


def _remove_sample(
    db: Session, user_id: uuid.UUID, profile_id: uuid.UUID, position: int
) -> tuple:
    """Drop one clip, re-derive the embedding over the rest; return (profile, files to remove).

    Raises 404/409 when the clip cannot be removed. Files are returned, not deleted: the caller
    removes them only after the commit.
    """
    profile = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.id == profile_id,
            VoiceProfile.user_id == user_id,
            VoiceProfile.deleted_at == None,
        )
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    if profile.status != "ready":
        raise HTTPException(status_code=409, detail="This voice profile is not ready.")
    if profile.embedding_version not in (None, EMBEDDING_VERSION):
        raise HTTPException(
            status_code=409,
            detail="This voice profile was made by an older engine and cannot be changed. "
            "Upload a new profile.",
        )
    samples = list(profile.samples)
    if len(samples) <= 1:  # includes a profile from before sample rows: one clip
        raise HTTPException(
            status_code=409,
            detail="A voice needs at least one clip. Delete the profile instead.",
        )
    removed = next((s for s in samples if s.position == position), None)
    if removed is None:
        raise HTTPException(status_code=404, detail="Voice sample not found")
    removed_files = [removed.audio_path, removed.embedding_path]
    kept = [s for s in samples if s is not removed]
    try:
        embeddings = [np.load(s.embedding_path) for s in kept]
    except (OSError, ValueError):
        logger.exception("Stored clip embedding unreadable for profile %s", profile_id)
        raise HTTPException(
            status_code=409,
            detail="This voice profile's stored clips are unavailable. Upload a new profile.",
        )
    old_embedding_path = profile.embedding_path
    new_path = None
    if len(kept) == 1:
        # One clip left: the profile embedding is that clip's own, as for a first upload.
        profile.embedding_path = kept[0].embedding_path
    else:
        new_path = os.path.join(
            os.path.dirname(kept[0].audio_path), f"{uuid.uuid4()}_profile_embed.npy"
        )
        np.save(new_path, aggregate_embeddings(embeddings))
        profile.embedding_path = new_path
    scores = clip_agreement(embeddings)
    try:
        db.delete(removed)
        profile.samples.remove(removed)
        # Renumber from 0 in two steps so the (profile, position) unique key never collides.
        for i, sample in enumerate(kept):
            sample.position = -(i + 1)
        db.flush()
        for i, (sample, score) in enumerate(zip(kept, scores)):
            sample.position = i
            sample.agreement = score
        profile.audio_sample_path = kept[0].audio_path
        profile.embedding_version = EMBEDDING_VERSION
        db.commit()
    except Exception:
        db.rollback()
        if new_path:
            _remove_quietly(new_path)
        raise
    files = list(removed_files)
    if old_embedding_path not in [removed_files[1], *(s.embedding_path for s in kept)]:
        files.append(old_embedding_path)
    return profile, files


@router.delete(
    "/profiles/{profile_id}/samples/{position}", response_model=VoiceProfileUploadOut
)
@limiter.limit(settings.API_RATE_LIMIT)
async def remove_sample(
    request: Request,
    profile_id: str,
    position: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove one clip from a multi-clip profile and re-derive its embedding from the rest.

    The clip's audio and embedding are erased from disk (SPEECH_QUALITY_PLAN.md S2.1d). The
    remaining clips are renumbered from 0. The last clip cannot be removed: delete the profile.
    """
    try:
        pid = uuid.UUID(profile_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile ID format")
    try:
        profile, files = await asyncio.to_thread(
            _remove_sample, db, current_user.id, pid, position
        )
    except SQLAlchemyError as error:
        logger.exception("Failed to remove clip from profile %s", pid)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(status_code=500, detail="Failed to save voice profile")
    await asyncio.to_thread(remove_files, files)
    logger.info(
        "Clip %d removed from profile %s by user_id=%s", position, pid, current_user.id
    )
    return VoiceProfileUploadOut(
        id=profile.id,
        name=profile.name,
        status=profile.status,
        consent_confirmed_at=profile.consent_confirmed_at,
        terms_version=profile.terms_version,
        created_at=profile.created_at,
        embedding_version=profile.embedding_version,
        samples=_samples_out(list(profile.samples)),
    )


@router.get("/profiles", response_model=List[VoiceProfileOut])
@limiter.limit(settings.API_RATE_LIMIT)
def get_profiles(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all active voice profiles for the current user, newest first."""
    profiles = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.user_id == current_user.id, VoiceProfile.deleted_at == None
        )
        .options(selectinload(VoiceProfile.samples))
        .order_by(VoiceProfile.created_at.desc())
        .all()
    )
    logger.debug(
        "Listed %d voice profiles for user_id=%s", len(profiles), current_user.id
    )
    return [_profile_out(profile) for profile in profiles]


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
