"""Audio file validation and preprocessing utilities."""

import os
import shutil
import uuid

import librosa
import numpy as np
from fastapi import HTTPException, UploadFile

from backend.core.config import settings

SAMPLE_RATE = 16000


def validate_audio_file(file: UploadFile) -> str:
    """Validate MIME type, size, and magic bytes; return the extension the magic bytes imply."""
    allowed_mimes = [
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/webm",
    ]
    if file.content_type not in allowed_mimes:
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

    magic = file.file.read(4)
    file.file.seek(0)
    is_wav = magic.startswith(b"RIFF")
    is_mp3 = (
        magic.startswith(b"ID3")
        or magic.startswith(b"\xff\xfb")
        or magic.startswith(b"\xff\xfa")
        or magic.startswith(b"\xff\xf3")
    )
    is_webm = magic.startswith(b"\x1a\x45\xdf\xa3")

    if is_wav:
        return ".wav"
    if is_mp3:
        return ".mp3"
    if is_webm:
        return ".webm"

    raise HTTPException(status_code=422, detail="Invalid file signature (magic bytes).")


def save_upload(file: UploadFile, user_id: str, ext: str) -> str:
    """Save an uploaded audio file to the user-specific upload directory under the given extension."""
    user_dir = os.path.join(settings.UPLOAD_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(user_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return file_path


def preprocess_audio(file_path: str) -> np.ndarray:
    """Load, trim silence, and normalize audio; reject too-long or too-quiet/short input."""
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

        y, sr = librosa.load(file_path, sr=SAMPLE_RATE)
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

        return y_trimmed / max_val
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Error processing audio file: {str(e)}"
        )
