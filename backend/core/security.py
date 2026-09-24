"""Password hashing and JWT token management."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.models.user import User

# HARDENING_PLAN.md finding L9: must match the actual mounted path
# (main.py: API_V1_PREFIX + auth_router's prefix = "/api/v1/auth/login"),
# not the pre-versioning "api/auth/login" — only affects the OpenAPI docs'
# auth flow (Swagger UI's "Authorize" button), not token verification
# itself, since a bearer token is checked on its contents regardless of
# where the client fetched it from.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def hash_email_for_logging(email: str) -> str:
    """Return a short, non-reversible stand-in for an email address, safe to
    write to logs in place of the raw address (HARDENING_PLAN.md finding L10).

    Salted with JWT_SECRET_KEY (a secret already required to be strong — see
    `validate_jwt_secret_key`) so it can't be reversed via a rainbow table of
    common/guessable email addresses. Deterministic, so repeated attempts on
    the same address correlate in log review without the address itself ever
    being written anywhere. Not a security primitive — a normal user id is
    preferred wherever one already exists (e.g. a successful login); this is
    only for the paths (a failed login, in particular) where no row is ever
    looked up and an id isn't available.

    Args:
        email: The raw email address to identify.

    Returns:
        A 16-character hex digest.
    """
    digest = hashlib.sha256(
        f"{email.strip().lower()}:{settings.JWT_SECRET_KEY}".encode()
    ).hexdigest()
    return digest[:16]


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update(
        {"exp": expire, "jti": str(uuid.uuid4()), "type": ACCESS_TOKEN_TYPE}
    )
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_refresh_token(data: dict, jti: Optional[str] = None) -> str:
    """Sign a refresh JWT; ``jti`` lets the caller register the id it embeds."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    to_encode.update(
        {"exp": expire, "jti": jti or str(uuid.uuid4()), "type": REFRESH_TOKEN_TYPE}
    )
    return jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_token(token: str, expected_type: str = ACCESS_TOKEN_TYPE) -> dict:
    """Decode a JWT and reject it unless its `type` claim matches `expected_type`."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    payload = decode_token(token)
    user_id_str = payload.get("sub")
    if user_id_str is None:
        raise HTTPException(
            status_code=401, detail="Invalid authentication credentials"
        )

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    user = db.query(User).filter(User.id == user_id, User.deleted_at == None).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user
