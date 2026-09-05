import os
import shutil
import uuid

import librosa
import numpy as np
from fastapi import HTTPException, UploadFile

from backend.core.config import settings


def validate_audio_file(file: UploadFile) -> None:
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

    if not (is_wav or is_mp3 or is_webm):
        raise HTTPException(
            status_code=422, detail="Invalid file signature (magic bytes)."
        )


def save_upload(file: UploadFile, user_id: str) -> str:
    user_dir = os.path.join(settings.UPLOAD_DIR, user_id)
    os.makedirs(user_dir, exist_ok=True)

    ext = os.path.splitext(file.filename or "")[1]
    if not ext:
        ext = ".wav"

    filename = f"{uuid.uuid4()}{ext}"
    file_path = os.path.join(user_dir, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return file_path


def preprocess_audio(file_path: str) -> np.ndarray:
    try:
        y, sr = librosa.load(file_path, sr=16000)
        y_trimmed, _ = librosa.effects.trim(y, top_db=30)

        max_val = np.max(np.abs(y_trimmed))
        if max_val > 0:
            y_normalized = y_trimmed / max_val
        else:
            y_normalized = y_trimmed

        return y_normalized
    except Exception as e:
        raise HTTPException(
            status_code=422, detail=f"Error processing audio file: {str(e)}"
        )
