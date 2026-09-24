"""Server-side refresh-token registry: issue, rotate, revoke (P2-M4)."""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.security import REFRESH_TOKEN_TYPE, create_refresh_token, decode_token
from backend.models.refresh_token import RefreshToken

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def issue_refresh_token(db: Session, user_id: uuid.UUID) -> str:
    """Create a refresh JWT and persist its ``jti`` so it can be revoked."""
    jti = uuid.uuid4()
    token = create_refresh_token({"sub": str(user_id)}, jti=str(jti))
    db.add(
        RefreshToken(
            id=jti,
            user_id=user_id,
            expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
    )
    db.commit()
    return token


def revoke_all_for_user(db: Session, user_id: uuid.UUID) -> int:
    """Revoke every still-active refresh token of a user; return the count."""
    result = db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    db.commit()
    return result.rowcount


def consume_refresh_token(db: Session, jti: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Atomically revoke an active token; ``False`` if it can't be used.

    The single conditional UPDATE means two concurrent refreshes with the
    same token can't both succeed. If the token exists but was already
    revoked, it is being replayed (stolen or reused after rotation), so the
    user's whole token set is revoked.
    """
    now = _now()
    result = db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == jti,
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
    )
    db.commit()
    if result.rowcount == 1:
        return True

    row = db.get(RefreshToken, jti)
    if row is not None and row.user_id == user_id and row.revoked_at is not None:
        logger.warning(
            "Revoked refresh token replayed; revoking all sessions: user_id=%s",
            user_id,
        )
        revoke_all_for_user(db, user_id)
    return False


def parse_refresh_claims(token: str) -> Optional[tuple[uuid.UUID, uuid.UUID]]:
    """Return ``(jti, user_id)`` from a valid refresh JWT, else ``None``."""
    try:
        payload = decode_token(token, expected_type=REFRESH_TOKEN_TYPE)
        return uuid.UUID(payload["jti"]), uuid.UUID(payload["sub"])
    except (HTTPException, KeyError, ValueError, TypeError):
        return None
