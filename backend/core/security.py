"""Password hashing and JWT token management."""

import hashlib
import hmac
import uuid
from functools import lru_cache
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
EMAIL_VERIFICATION_TOKEN_TYPE = "email_verification"
PASSWORD_RESET_TOKEN_TYPE = "password_reset"

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


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A real hash at the configured cost, to burn the same time as a true check."""
    return hash_password("not-a-real-password-timing-equaliser")


def verify_password_or_dummy(plain_password: str, hashed_password: Optional[str]) -> bool:
    """Verify a password; with no stored hash, spend the same time and return False.

    Without this, login answers in milliseconds for an unknown email and in
    a couple of hundred for a known one, which reveals who has an account.
    """
    if hashed_password:
        return verify_password(plain_password, hashed_password)
    verify_password(plain_password, _dummy_password_hash())
    return False


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


def password_fingerprint(hashed_password: Optional[str]) -> str:
    """Keyed, truncated digest of a stored password hash.

    A password-reset token carries this; it stops matching the moment the
    password changes, which makes the token single-use without a table. It is
    keyed with the JWT secret so a token never discloses anything about the
    hash it was derived from. An account with no password yet (Google-only)
    fingerprints the empty string, so its token dies the moment one is set.
    """
    return hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        (hashed_password or "").encode(),
        hashlib.sha256,
    ).hexdigest()[:24]


def _create_purpose_token(claims: dict, token_type: str, lifetime: timedelta) -> str:
    """Sign a short-lived JWT whose `type` scopes it to one purpose."""
    payload = {
        **claims,
        "type": token_type,
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(timezone.utc) + lifetime,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def create_email_verification_token(user: User) -> str:
    """Token proving the holder received mail at `user.email`."""
    return _create_purpose_token(
        {"sub": str(user.id), "email": user.email.lower()},
        EMAIL_VERIFICATION_TOKEN_TYPE,
        timedelta(hours=settings.EMAIL_VERIFICATION_EXPIRE_HOURS),
    )


def create_password_reset_token(user: User) -> str:
    """Single-use token to set (or reset) the account's password."""
    return _create_purpose_token(
        {"sub": str(user.id), "pwf": password_fingerprint(user.hashed_password)},
        PASSWORD_RESET_TOKEN_TYPE,
        timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
    )


def decode_purpose_token(token: str, expected_type: str) -> Optional[dict]:
    """Return the claims of a valid token of `expected_type`, else None.

    Unlike `decode_token` this never raises: the email endpoints answer every
    bad token (malformed, expired, wrong purpose) with one generic 400.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
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


def get_verified_user(user: User = Depends(get_current_user)) -> User:
    """`get_current_user`, but 403 while the email is unverified.

    Guards the actions that cost compute or create voice data. A no-op when
    `REQUIRE_EMAIL_VERIFICATION` is off.
    """
    if settings.REQUIRE_EMAIL_VERIFICATION and user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified",
        )
    return user
