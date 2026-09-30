from fastapi import APIRouter, Request

from backend.core.config import settings
from backend.core.rate_limit import limiter
from backend.schemas.terms import TermsOut

router = APIRouter()


@router.get("", response_model=TermsOut)
@limiter.limit("60/minute")
def get_terms(request: Request) -> TermsOut:
    """Return the acceptable-use terms version an upload must acknowledge."""
    return TermsOut(version=settings.TERMS_VERSION, url=settings.TERMS_URL or None)
