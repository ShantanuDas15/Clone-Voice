from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    voice_profile_id: UUID
    text: str = Field(..., min_length=1, max_length=500)


class GenerationOut(BaseModel):
    id: UUID
    voice_profile_id: UUID
    input_text: str
    output_audio_path: str
    duration_seconds: float
    created_at: datetime

    model_config = {"from_attributes": True}
