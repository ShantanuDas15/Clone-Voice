"""Authentication API routes and handlers."""

import logging

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    decode_token,
    get_current_user,
    hash_email_for_logging,
    hash_password,
    verify_password,
)
from backend.models.user import User
from backend.schemas.auth import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UpdateUserRequest,
    UserOut,
)
from backend.services.refresh_tokens import (
    consume_refresh_token,
    issue_refresh_token,
    parse_refresh_claims,
    revoke_all_for_user,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh cookie, aged to match the token's own lifetime."""
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID or "mock-client-id",
    client_secret=settings.GOOGLE_CLIENT_SECRET or "mock-client-secret",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.post(
    "/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(settings.AUTH_SIGNUP_RATE_LIMIT)
def signup(request: Request, user_in: SignupRequest, db: Session = Depends(get_db)):
    """Register a new local user and return an access token."""
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        # HARDENING_PLAN.md finding L10: log the existing row's id, never the
        # raw email (PII).
        logger.warning(
            "Signup rejected: email already registered — user_id=%s",
            existing_user.id,
        )
        raise HTTPException(status_code=409, detail="Email already registered")

    new_user = User(
        email=user_in.email,
        name=user_in.name,
        hashed_password=hash_password(user_in.password),
        provider="local",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info("New user registered: user_id=%s", new_user.id)
    access_token = create_access_token(data={"sub": str(new_user.id)})
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.AUTH_LOGIN_RATE_LIMIT)
def login(
    request: Request,
    user_in: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate a local user and return access + refresh tokens."""
    user = db.query(User).filter(User.email == user_in.email).first()
    if (
        not user
        or not user.hashed_password
        or not verify_password(user_in.password, user.hashed_password)
    ):
        # HARDENING_PLAN.md finding L10: no DB row here on an unknown email,
        # so there's no user_id to log — a salted, non-reversible hash lets
        # repeated attempts on the same address still correlate in logs
        # without ever writing the raw address.
        logger.warning(
            "Failed login attempt for email_hash=%s",
            hash_email_for_logging(user_in.email),
        )
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    logger.info("User logged in: user_id=%s", user.id)
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = issue_refresh_token(db, user.id)

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response, refresh_token: str = Cookie(None), db: Session = Depends(get_db)
):
    """Rotate a refresh token and issue a new access token."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    # Signature/type problems raise 401 here; a token that verifies but has
    # no usable jti/sub (e.g. issued before P2-M4) is rejected just below.
    decode_token(refresh_token, expected_type=REFRESH_TOKEN_TYPE)
    claims = parse_refresh_claims(refresh_token)
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    jti, user_id = claims

    user = db.query(User).filter(User.id == user_id, User.deleted_at == None).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    # HARDENING_PLAN.md finding P2-M4: the presented token is single-use.
    if not consume_refresh_token(db, jti, user_id):
        raise HTTPException(status_code=401, detail="Refresh token revoked or expired")

    logger.debug("Refresh token rotated for user_id=%s", user_id)
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = issue_refresh_token(db, user.id)

    _set_refresh_cookie(response, new_refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response, refresh_token: str = Cookie(None), db: Session = Depends(get_db)
):
    """Revoke the caller's refresh token and clear the cookie (idempotent)."""
    claims = parse_refresh_claims(refresh_token) if refresh_token else None
    if claims is not None:
        jti, user_id = claims
        consume_refresh_token(db, jti, user_id)
    response.delete_cookie(
        key="refresh_token", httponly=True, secure=True, samesite="lax"
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return current_user


@router.get("/google")
async def google_login(request: Request):
    """Redirect user to Google OAuth consent screen."""
    redirect_uri = settings.GOOGLE_REDIRECT_URI or str(
        request.url_for("google_callback")
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", response_model=TokenResponse)
async def google_callback(
    request: Request, response: Response, db: Session = Depends(get_db)
):
    """Handle the Google OAuth callback and return tokens."""
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            user_info = await oauth.google.parse_id_token(request, token)
    except OAuthError as error:
        logger.warning("OAuth error during Google callback: %s", error.error)
        raise HTTPException(status_code=400, detail=f"OAuth error: {error.error}")
    except Exception:
        logger.exception("Unexpected error during Google OAuth callback")
        raise HTTPException(status_code=400, detail="Invalid code or state")

    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="No email provided by Google")

    if user_info.get("email_verified") is not True:
        logger.warning("Google sign-in rejected: email not verified by provider")
        raise HTTPException(status_code=400, detail="Google email is not verified")

    user = db.query(User).filter(User.email == email).first()
    if user:
        if user.provider == "local":
            user.provider = "google"
            # HARDENING_PLAN.md finding P2-H1: local signup never verified
            # email ownership, while Google just did. Drop the password so
            # whoever registered the address first can't keep signing in.
            user.hashed_password = None
            if not user.avatar_url:
                user.avatar_url = user_info.get("picture")
            db.commit()
            db.refresh(user)
            # A session the squatter already holds must not outlive the link
            # (the password alone isn't the only way in: refresh cookies work
            # for up to REFRESH_TOKEN_EXPIRE_DAYS). Google-to-Google sign-ins
            # leave other devices alone; only this first link revokes.
            revoked = revoke_all_for_user(db, user.id)
            logger.info(
                "Linked Google to local account, revoked %d session(s): user_id=%s",
                revoked,
                user.id,
            )
        logger.info("Existing user signed in via Google: user_id=%s", user.id)
    else:
        user = User(
            email=email,
            name=user_info.get("name") or "Google User",
            avatar_url=user_info.get("picture"),
            provider="google",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("New user created via Google OAuth: user_id=%s", user.id)

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = issue_refresh_token(db, user.id)

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.patch("/me", response_model=UserOut)
def update_me(
    user_update: UpdateUserRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current authenticated user's profile."""
    if user_update.name is not None:
        logger.debug("Updating name for user_id=%s", current_user.id)
        current_user.name = user_update.name
        db.commit()
        db.refresh(current_user)
    return current_user
