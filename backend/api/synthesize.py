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
from backend.services.tts_pipeline import (save_output, synthesize_speech,
                                           vocode)

router = APIRouter()


@router.post("", response_class=FileResponse)
def synthesize(
    req: SynthesizeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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
    except Exception as e:
        raise HTTPException(
            status_code=500, detail="Failed to load voice profile embedding"
        )

    mel = synthesize_speech(req.text, embedding)
    wav = vocode(mel)

    sample_rate = 16000

    out_path, duration = save_output(wav, sample_rate, str(current_user.id))

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

    return generations
