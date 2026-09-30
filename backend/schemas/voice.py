from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class VoiceProfileOut(BaseModel):
    id: UUID
    name: str
    status: str
    consent_confirmed_at: datetime
    terms_version: str
    created_at: datetime

    model_config = {"from_attributes": True}
