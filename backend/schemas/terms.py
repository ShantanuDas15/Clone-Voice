from typing import Optional

from pydantic import BaseModel


class TermsOut(BaseModel):
    version: str
    url: Optional[str] = None
    # Days a generated WAV is kept before it is pruned (the history row stays).
    # Null means outputs are kept until the user deletes them.
    output_retention_days: Optional[float] = None
