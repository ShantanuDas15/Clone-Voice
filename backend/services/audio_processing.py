"""Audio file validation and preprocessing utilities."""

import asyncio
import logging
import os
import shutil
import uuid
from typing import Optional

import librosa
import numpy as np
from fastapi import HTTPException, UploadFile

from backend.core.config import settings

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# The level (RMS, dBFS) resemblyzer's speaker encoder was trained on: its own
# `audio_norm_target_dBFS`, pinned by a test so it cannot drift silently.
ENCODER_TARGET_DBFS = -30.0

# HARDENING_PLAN.md finding P2-L10: bounds how many uploads may run
# preprocess_audio's decode/resample/trim at once. Callers `async with` this
# around their `asyncio.to_thread(preprocess_audio, ...)` call; it is a plain
# semaphore (no queue-depth cap or timeout, unlike `_inference_semaphore` in
# tts_pipeline.py) since a stalled decode just delays that one upload, not a
# shared GPU/CPU model permit.
preprocess_semaphore = asyncio.Semaphore(settings.PREPROCESS_MAX_CONCURRENCY)


# Declared media types accepted for each container the content can be.
_MIME_TYPES_BY_EXTENSION = {
    # audio/vnd.wave is the IANA name (RFC 2361); Firefox on Linux labels WAVs with it.
    ".wav": {"audio/wav", "audio/x-wav", "audio/wave", "audio/vnd.wave"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".webm": {"audio/webm"},
}
_SNIFF_BYTES = 64
_MP3_SIGNATURES = (b"ID3", b"\xff\xfb", b"\xff\xfa", b"\xff\xf3")
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"


def _media_type(file: UploadFile) -> str:
    """The declared media type without parameters (``audio/webm;codecs=opus``)."""
    return (file.content_type or "").split(";", 1)[0].strip().lower()


def sniff_audio_extension(head: bytes) -> Optional[str]:
    """Return the extension the leading bytes of a file imply, else ``None``.

    Stricter than the first four bytes alone: a ``RIFF`` file must be a WAVE
    (not an AVI or WebP), and an EBML file must declare the ``webm`` doctype
    (not Matroska, which can carry video).
    """
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head.startswith(_MP3_SIGNATURES):
        return ".mp3"
    if head[:4] == _EBML_MAGIC and b"webm" in head:
        return ".webm"
    return None


def validate_audio_file(file: UploadFile) -> str:
    """Validate type, size and content; return the extension the content implies."""
    declared = _media_type(file)
    if not any(declared in types for types in _MIME_TYPES_BY_EXTENSION.values()):
        raise HTTPException(
            status_code=422, detail="Invalid audio format. Allowed: WAV, MP3, WEBM."
        )

    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)

    max_size_bytes = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
    if size == 0:
        raise HTTPException(status_code=422, detail="Empty file uploaded.")
    if size > max_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max allowed is {settings.MAX_AUDIO_SIZE_MB}MB.",
        )

    head = file.file.read(_SNIFF_BYTES)
    file.file.seek(0)
    extension = sniff_audio_extension(head)
    if extension is None:
        raise HTTPException(
            status_code=422, detail="Invalid file signature (magic bytes)."
        )
    if declared not in _MIME_TYPES_BY_EXTENSION[extension]:
        raise HTTPException(
            status_code=422,
            detail="File content does not match its declared audio type.",
        )
    return extension


def save_upload(file: UploadFile, user_id: str, ext: str) -> str:
    """Save an uploaded audio file to the user-specific upload directory under the given extension."""
    user_dir = os.path.join(settings.UPLOAD_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(user_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return file_path


def raise_to_encoder_level(
    y: np.ndarray, target_dbfs: float = ENCODER_TARGET_DBFS
) -> np.ndarray:
    """Boost quiet audio to `target_dbfs` RMS; never turn louder audio down.

    Mirrors resemblyzer's `normalize_volume(..., increase_only=True)`. Peak
    normalising every upload to full scale instead over-drives the encoder:
    measured on 20 real speakers it lowered the cloned voice's similarity to
    the real speaker by 0.02 (95% CI 0.011 to 0.028), see PREPROCESSING_STUDY.md.
    """
    rms = float(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) if len(y) else 0.0
    if rms <= 0.0:
        return y
    change_db = target_dbfs - 20.0 * np.log10(rms)
    if change_db <= 0.0:
        return y
    return (y * (10.0 ** (change_db / 20.0))).astype(np.float32)


def preprocess_audio(file_path: str) -> np.ndarray:
    """Load, trim silence and set the level for the encoder; reject bad input."""
    try:
        raw_duration = librosa.get_duration(path=file_path)
        if raw_duration > settings.MAX_AUDIO_DURATION_SECONDS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Audio too long. Max allowed duration is "
                    f"{settings.MAX_AUDIO_DURATION_SECONDS:g} seconds."
                ),
            )

        # Decode at most the limit plus one second: the duration above comes
        # from the file's own header, which an attacker controls, so the
        # decode itself must be bounded too.
        y, sr = librosa.load(
            file_path,
            sr=SAMPLE_RATE,
            duration=settings.MAX_AUDIO_DURATION_SECONDS + 1.0,
        )
        if len(y) / SAMPLE_RATE > settings.MAX_AUDIO_DURATION_SECONDS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Audio too long. Max allowed duration is "
                    f"{settings.MAX_AUDIO_DURATION_SECONDS:g} seconds."
                ),
            )
        y_trimmed, _ = librosa.effects.trim(y, top_db=30)

        voiced_seconds = len(y_trimmed) / SAMPLE_RATE
        max_val = float(np.max(np.abs(y_trimmed))) if len(y_trimmed) else 0.0
        if max_val <= 0.0 or voiced_seconds < settings.MIN_VOICED_DURATION_SECONDS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Audio has too little speech after removing silence. "
                    f"At least {settings.MIN_VOICED_DURATION_SECONDS:g} seconds "
                    "of speech is required."
                ),
            )

        return raise_to_encoder_level(y_trimmed)
    except HTTPException:
        raise
    except Exception:
        # Library error text can leak internals (paths, codec details): log it
        # server-side and return a generic detail (HARDENING_PLAN.md L1).
        logger.exception("Audio preprocessing failed for %s", file_path)
        raise HTTPException(
            status_code=422,
            detail="Could not process this audio file. "
            "Please upload a valid, uncorrupted recording.",
        )
