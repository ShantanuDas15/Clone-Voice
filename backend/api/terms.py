from fastapi import APIRouter, Request

from backend.core.config import settings
from backend.core.rate_limit import limiter
from backend.schemas.terms import TermsOut

router = APIRouter()


@router.get("", response_model=TermsOut)
@limiter.limit("60/minute")
def get_terms(request: Request) -> TermsOut:
    """Return the terms version an upload must acknowledge, and the output retention."""
    days = settings.OUTPUT_RETENTION_DAYS
    return TermsOut(
        version=settings.TERMS_VERSION,
        url=settings.TERMS_URL or None,
        output_retention_days=days if days > 0 else None,
    )
