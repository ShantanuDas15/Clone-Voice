from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SynthesizeRequest(BaseModel):
    voice_profile_id: UUID
    text: str = Field(..., min_length=1, max_length=500)


class GenerationOut(BaseModel):
    id: UUID
    voice_profile_id: UUID
    input_text: str
    output_filename: str
    duration_seconds: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}
