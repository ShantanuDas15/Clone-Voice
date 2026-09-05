from typing import List

import numpy as np
from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile,
                     status)
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.user import User
from backend.models.voice_profile import VoiceProfile
from backend.schemas.voice import VoiceProfileOut
from backend.services.audio_processing import (preprocess_audio, save_upload,
                                               validate_audio_file)

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
    validate_audio_file(file)
    file_path = save_upload(file, str(current_user.id))

    # Preprocess
    y_processed = preprocess_audio(file_path)

    # Mocking the embedding extraction for now (Milestone 1.6)
    embedding_path = file_path.replace(".wav", "_embed.npy").replace(
        ".mp3", "_embed.npy"
    )
    np.save(embedding_path, np.zeros(256))

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

    return profile


@router.get("/profiles", response_model=List[VoiceProfileOut])
def get_profiles(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    profiles = (
        db.query(VoiceProfile)
        .filter(
            VoiceProfile.user_id == current_user.id, VoiceProfile.deleted_at == None
        )
        .all()
    )
    return profiles


@router.delete("/profiles/{profile_id}")
def delete_profile(
    profile_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import uuid

    from sqlalchemy.sql import func

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
    return {"status": "deleted"}
