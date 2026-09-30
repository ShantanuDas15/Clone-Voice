from typing import Optional

from pydantic import BaseModel


class TermsOut(BaseModel):
    version: str
    url: Optional[str] = None
