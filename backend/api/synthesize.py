"""TTS synthesis API routes and history."""

import asyncio
import logging
import os
from typing import List, Optional
from uuid import UUID

import numpy as np
import torch
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.db_errors import db_unavailable, is_transient_db_error
from backend.core.rate_limit import limiter, synthesize_key, synthesize_limit
from backend.core.security import get_current_user, get_verified_user
from backend.models.generation import Generation
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.synthesize import (
    GenerationOut,
    SynthesisCapabilitiesOut,
    SynthesizeRequest,
)
from backend.services import style_markup, styled_synthesis
from backend.services.erasure import erase_generation, remove_files
from backend.services.text_analysis import StyleOverride
from backend.services.tts_engine import EngineUnavailableError, get_engine_for_user
from backend.services.tts_pipeline import (
    InferenceQueueFullError,
    InferenceTimeoutError,
    OutputQualityError,
    free_gpu_memory,
    run_inference_pipeline,
)
from backend.services.voice_embedding import EMBEDDING_VERSION

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_failed_generation(
    db: Session,
    user_id,
    voice_profile_id,
    text: str,
    engine: Optional[str] = None,
    requested: Optional[dict] = None,
) -> None:
    """Persist a `status="failed"` audit row for an inference error.

    ``requested`` holds what the user asked for (emotion, intensity, seed); the
    ``*_applied`` columns stay NULL because no engine finished the request.

    Runs on the error path only — a successful synthesis records its own
    `status="completed"` row after the pipeline returns. A DB failure here is
    logged and swallowed (HARDENING_PLAN.md P2-L2) so it can never replace the
    caller's intended 429/503/500 with an unhandled error.
    """
    failed_generation = Generation(
        user_id=user_id,
        voice_profile_id=voice_profile_id,
        input_text=text,
        output_audio_path=None,
        duration_seconds=None,
        status="failed",
        engine=engine,
        **(requested or {}),
    )
    try:
        db.add(failed_generation)
        db.commit()
    except SQLAlchemyError:
        logger.exception(
            "Failed to record failed generation — user_id=%s, profile_id=%s",
            user_id,
            voice_profile_id,
        )
        db.rollback()


def _remove_quietly(path: str) -> None:
    """Delete a file, logging (not raising) on failure."""
    try:
        os.remove(path)
    except OSError:
        logger.exception("Failed to remove orphaned output: %s", path)


def _style_override(req: SynthesizeRequest) -> Optional[StyleOverride]:
    """The user's requested delivery, or None for ``auto``."""
    if req.emotion == "auto":
        return None
    return StyleOverride(req.emotion, req.intensity)


def _engine_headers(generation: Generation) -> dict:
    """Response headers saying which engine spoke, and whether it was the backup."""
    headers = {}
    if generation.engine:
        headers["X-Voice-Engine"] = generation.engine
    if generation.engine_fallback_from:
        headers["X-Voice-Engine-Fallback"] = generation.engine_fallback_from
    return headers


def _style_headers(requested: bool, result: object) -> dict:
    """Style headers: whether a requested emotion was applied, and the emotion of each sentence.

    ``X-Voice-Style`` is sent only when an emotion was requested. ``X-Voice-Emotions`` is sent
    whenever the engine spoke sentence by sentence (also for ``auto``, where it shows what the
    text analysis detected): one label per sentence, in order, from the six fixed emotion names,
    never any text.
    """
    headers = {}
    if requested:
        applied = getattr(result, "style_applied", False)
        headers["X-Voice-Style"] = "applied" if applied else "ignored"
    emotions = getattr(result, "emotions_used", ())
    if emotions:
        headers["X-Voice-Emotions"] = ",".join(emotions)
    return headers


def _seed_headers(seed: Optional[int], result: object) -> dict:
    """``X-Voice-Seed`` says whether a requested seed reached the engine that spoke."""
    if seed is None:
        return {}
    applied = getattr(result, "seed_applied", False)
    return {"X-Voice-Seed": "applied" if applied else "ignored"}


def _requested_fields(override: Optional[StyleOverride], seed: Optional[int]) -> dict:
    """The emotion, intensity and seed the user asked for, as `Generation` columns."""
    return {
        "emotion": override.emotion if override else None,
        "intensity": override.intensity if override else None,
        "seed": seed,
    }


def _tag_headers(result: object) -> dict:
    """``X-Voice-Tags-Dropped`` lists sound tags the engine that spoke could not make."""
    dropped = getattr(result, "sound_tags_dropped", ())
    return {"X-Voice-Tags-Dropped": ",".join(dropped)} if dropped else {}


def _persist_generation(db: Session, generation: Generation) -> None:
    """Add, commit, and refresh a completed generation row (run off the event loop)."""
    db.add(generation)
    db.commit()
    db.refresh(generation)


def _load_profile_and_release(db: Session, profile_id) -> Optional[VoiceProfile]:
    """Look up a voice profile and close the session in one thread dispatch.

    HARDENING_PLAN.md finding P2-M1: doing the query and the close as two
    separate `asyncio.to_thread` calls leaves an event-loop hop between them
    where the transaction is still open; running both synchronously here
    means there is no scheduling point in between for it to be observed.
    """
    profile = db.query(VoiceProfile).filter(VoiceProfile.id == profile_id).first()
    db.close()
    return profile


def _output_file(output_path: Optional[str]) -> Optional[str]:
    """Return the real path of a stored output WAV, or None if it is unusable.

    Unusable means no path recorded (a failed generation), a path that resolves
    outside ``OUTPUT_DIR``, or a file that is gone (pruned after the retention
    window, see ``OUTPUT_RETENTION_DAYS``).
    """
    if not output_path:
        return None
    real = os.path.realpath(output_path)
    base = os.path.realpath(settings.OUTPUT_DIR)
    if not real.startswith(base + os.sep) or not os.path.isfile(real):
        return None
    return real


@router.post("", response_class=FileResponse)
@limiter.limit(synthesize_limit, key_func=synthesize_key)
async def synthesize(
    request: Request,
    req: SynthesizeRequest,
    current_user: User = Depends(get_verified_user),
    db: Session = Depends(get_db),
):
    """Synthesize speech from text using a given voice profile."""
    # HARDENING_PLAN.md finding P2-M1: the auth lookup left a transaction (and
    # its pooled connection) open on this session. The profile query and the
    # close must happen inside the *same* thread dispatch: two separate
    # `await asyncio.to_thread(...)` calls each yield to the event loop, and
    # under a big enough burst of simultaneous requests that gap is long
    # enough for the connection to be observed sitting "idle in transaction"
    # (confirmed under real concurrent load against a real Postgres — see the
    # P2-M1 log row's 2026-09-28 follow-up). Doing both in one synchronous
    # function closes that gap entirely, not just narrows it.
    profile = await asyncio.to_thread(
        _load_profile_and_release, db, req.voice_profile_id
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

    if profile.embedding_version not in (None, EMBEDDING_VERSION):
        # Made by an embedding scheme this service no longer (or does not yet) speak with.
        raise HTTPException(
            status_code=409,
            detail="This voice profile was made with an older voice model; "
            "please upload the sample again.",
        )

    # Copy what inference needs into plain locals; the profile row's already-
    # loaded scalar columns stay readable after the session closed above. The
    # session reconnects lazily for the persist below.
    user_id = current_user.id
    profile_id = profile.id
    embedding_path = profile.embedding_path
    # A reference-audio engine (Chatterbox) also needs the stored sample; the SV2TTS call is
    # left exactly as it was.
    pipeline_extra = (
        {"reference_audio_path": profile.audio_sample_path}
        if get_engine_for_user(str(current_user.id)).needs_reference_audio
        else {}
    )
    override = _style_override(req)
    # Inline tags count as asking for a style even when no request-level emotion was sent.
    styled_requested = override is not None or style_markup.has_markup(req.text)
    if override:
        pipeline_extra["style_override"] = override
    if req.seed is not None:
        pipeline_extra["seed"] = req.seed
    requested = _requested_fields(override, req.seed)

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
        result = await run_inference_pipeline(
            req.text, embedding, str(user_id), **pipeline_extra
        )
        out_path, duration = result
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
            _record_failed_generation,
            db,
            user_id,
            profile_id,
            req.text,
            settings.TTS_ENGINE,
            requested,
        )
        free_gpu_memory()
        raise HTTPException(
            status_code=503,
            detail="Synthesis service is temporarily overloaded. Please try again shortly.",
        )
    except OutputQualityError as error:
        logger.error(
            "Synthesis refused by the quality gate (%s) — user_id=%s, profile_id=%s",
            ", ".join(error.reasons),
            user_id,
            profile_id,
        )
        await asyncio.to_thread(
            _record_failed_generation,
            db,
            user_id,
            profile_id,
            req.text,
            settings.TTS_ENGINE,
            requested,
        )
        raise HTTPException(
            status_code=502,
            detail="The synthesized audio did not meet the quality bar. "
            "Please try again, or shorten or reword the text.",
        )
    except EngineUnavailableError:
        logger.exception(
            "Speech engine unavailable — user_id=%s, profile_id=%s", user_id, profile_id
        )
        await asyncio.to_thread(
            _record_failed_generation,
            db,
            user_id,
            profile_id,
            req.text,
            settings.TTS_ENGINE,
            requested,
        )
        raise HTTPException(
            status_code=503,
            detail="The speech service is temporarily unavailable. Please try again shortly.",
        )
    except torch.cuda.OutOfMemoryError:
        logger.exception(
            "GPU OOM during synthesis — user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        await asyncio.to_thread(
            _record_failed_generation,
            db,
            user_id,
            profile_id,
            req.text,
            settings.TTS_ENGINE,
            requested,
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
            _record_failed_generation,
            db,
            user_id,
            profile_id,
            req.text,
            settings.TTS_ENGINE,
            requested,
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
        # Plain-tuple results (a test double) carry no engine facts: those columns stay NULL.
        engine=getattr(result, "engine", None),
        engine_version=getattr(result, "engine_version", None),
        engine_fallback_from=getattr(result, "engine_fallback_from", None),
        **requested,
        style_applied=(
            bool(getattr(result, "style_applied", False)) if styled_requested else None
        ),
        emotions_used=",".join(getattr(result, "emotions_used", ())) or None,
        sound_tags_dropped=",".join(getattr(result, "sound_tags_dropped", ())) or None,
        seed_applied=(
            bool(getattr(result, "seed_applied", False))
            if req.seed is not None
            else None
        ),
    )
    try:
        await asyncio.to_thread(_persist_generation, db, generation)
    except SQLAlchemyError as error:
        # HARDENING_PLAN.md P2-L2: no row will ever reference this WAV, so
        # remove it instead of leaving an orphan behind.
        logger.exception(
            "Failed to persist generation — user_id=%s, profile_id=%s",
            user_id,
            profile_id,
        )
        await asyncio.to_thread(db.rollback)
        await asyncio.to_thread(_remove_quietly, out_path)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(
            status_code=500, detail="Failed to save the synthesized audio"
        )

    return FileResponse(
        out_path,
        media_type="audio/wav",
        filename=f"synthesized_{generation.id}.wav",
        headers={
            **_engine_headers(generation),
            **_style_headers(styled_requested, result),
            **_seed_headers(req.seed, result),
            **_tag_headers(result),
        },
    )


@router.get("/capabilities", response_model=SynthesisCapabilitiesOut)
@limiter.limit(settings.API_RATE_LIMIT)
def get_capabilities(
    request: Request, current_user: User = Depends(get_current_user)
) -> SynthesisCapabilitiesOut:
    """Say whether an emotion the user picks would be applied for them."""
    try:
        user_id = str(current_user.id)
        engine = get_engine_for_user(user_id)
        applied = styled_synthesis.enabled_for(user_id) and styled_synthesis.applies(
            engine
        )
    except Exception:  # an engine that cannot be built just means no controls
        logger.exception("capabilities check failed")
        applied = False
    return SynthesisCapabilitiesOut(emotion_control=applied)


HISTORY_SEARCH_MAX_LENGTH = 200


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so a search matches the characters typed."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/history", response_model=List[GenerationOut])
@limiter.limit(settings.API_RATE_LIMIT)
def get_history(
    request: Request,
    response: Response,
    limit: int = Query(50, ge=1),
    offset: int = Query(0, ge=0),
    voice_profile_id: Optional[UUID] = Query(None),
    q: Optional[str] = Query(None, max_length=HISTORY_SEARCH_MAX_LENGTH),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return paginated synthesis history for the current user.

    The size of the whole history (not just this page) is sent in the
    ``X-Total-Count`` header, so a client can tell when it has reached the end.
    ``voice_profile_id`` narrows both to one voice; an unknown or foreign id
    simply matches nothing, so it cannot be used to probe for other profiles.
    ``q`` keeps the rows whose typed text contains it (case-insensitive, literal).
    """
    if limit > 50:
        limit = 50

    visible = (
        db.query(Generation)
        .join(VoiceProfile, Generation.voice_profile_id == VoiceProfile.id)
        .filter(
            Generation.user_id == current_user.id,
            Generation.deleted_at.is_(None),
            VoiceProfile.deleted_at == None,
        )
    )
    if voice_profile_id is not None:
        visible = visible.filter(Generation.voice_profile_id == voice_profile_id)
    needle = (q or "").strip()
    if needle:
        visible = visible.filter(
            Generation.input_text.ilike(f"%{_escape_like(needle)}%", escape="\\")
        )
    response.headers["X-Total-Count"] = str(visible.count())
    generations = (
        visible.with_entities(Generation, VoiceProfile.name)
        .order_by(Generation.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    logger.debug(
        "History fetched — user_id=%s, count=%d", current_user.id, len(generations)
    )

    results = []
    for gen, profile_name in generations:
        filename = (
            os.path.basename(gen.output_audio_path) if gen.output_audio_path else ""
        )
        results.append(
            GenerationOut(
                id=gen.id,
                voice_profile_id=gen.voice_profile_id,
                voice_profile_name=profile_name,
                status=gen.status,
                input_text=gen.input_text,
                output_filename=filename,
                duration_seconds=gen.duration_seconds,
                audio_available=_output_file(gen.output_audio_path) is not None,
                created_at=gen.created_at,
                engine=gen.engine,
                engine_fallback_from=gen.engine_fallback_from,
                emotion=gen.emotion,
                intensity=gen.intensity,
                style_applied=gen.style_applied,
                seed=gen.seed,
                seed_applied=gen.seed_applied,
                emotions_used=gen.emotions_used,
                sound_tags_dropped=gen.sound_tags_dropped,
            )
        )

    return results


@router.get("/{generation_id}/audio", response_class=FileResponse)
@limiter.limit(settings.API_RATE_LIMIT)
def get_generation_audio(
    request: Request,
    generation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the WAV of one of the caller's own completed generations.

    404 covers an unknown id, someone else's generation, a deleted one and a
    failed one alike, so ids cannot be probed. 410 means the generation exists
    but its file has expired and been pruned.
    """
    generation = (
        db.query(Generation)
        .filter(
            Generation.id == generation_id,
            Generation.user_id == current_user.id,
            Generation.deleted_at.is_(None),
            Generation.status == "completed",
        )
        .first()
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")

    path = _output_file(generation.output_audio_path)
    if path is None:
        raise HTTPException(
            status_code=410, detail="The audio for this generation has expired"
        )

    return FileResponse(
        path, media_type="audio/wav", filename=f"synthesized_{generation.id}.wav"
    )


@router.delete("/{generation_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(settings.API_RATE_LIMIT)
def delete_generation(
    request: Request,
    generation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Delete one of the caller's own generations: its audio file and the text they typed.

    The row is soft-deleted and scrubbed (GENERATION_DELETE_PLAN.md D1), then the file is removed
    after the commit. 404 covers an unknown id, someone else's generation and one already
    deleted alike, so ids cannot be probed. A failed generation (no audio) can be deleted too.
    Deliberately open to unverified users: removing your own data is never gated on email state.
    """
    generation = (
        db.query(Generation)
        .filter(
            Generation.id == generation_id,
            Generation.user_id == current_user.id,
            Generation.deleted_at.is_(None),
        )
        .first()
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")

    files = erase_generation(db, generation)
    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Failed to delete generation: id=%s", generation_id)
        if is_transient_db_error(error):
            raise db_unavailable()
        raise HTTPException(status_code=500, detail="Failed to delete the generation")
    remove_files(files)
    logger.info(
        "Generation deleted: id=%s by user_id=%s", generation_id, current_user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
