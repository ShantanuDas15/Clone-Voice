"""Authentication API routes and handlers."""

import logging
import uuid

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import (APIRouter, Cookie, Depends, HTTPException, Request,
                     Response, status)
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.security import (create_access_token, create_refresh_token,
                                   decode_token, get_current_user,
                                   hash_password, verify_password)
from backend.models.user import User
from backend.schemas.auth import (LoginRequest, SignupRequest, TokenResponse,
                                  UpdateUserRequest, UserOut)

logger = logging.getLogger(__name__)

router = APIRouter()

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
def signup(user_in: SignupRequest, db: Session = Depends(get_db)):
    """Register a new local user and return an access token."""
    if db.query(User).filter(User.email == user_in.email).first():
        logger.warning("Signup rejected: email already registered — %s", user_in.email)
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

    logger.info("New user registered: %s (id=%s)", new_user.email, new_user.id)
    access_token = create_access_token(data={"sub": str(new_user.id)})
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
def login(user_in: LoginRequest, response: Response, db: Session = Depends(get_db)):
    """Authenticate a local user and return access + refresh tokens."""
    user = db.query(User).filter(User.email == user_in.email).first()
    if (
        not user
        or not user.hashed_password
        or not verify_password(user_in.password, user.hashed_password)
    ):
        logger.warning("Failed login attempt for email: %s", user_in.email)
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    logger.info("User logged in: %s (id=%s)", user.email, user.id)
    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    response: Response, refresh_token: str = Cookie(None), db: Session = Depends(get_db)
):
    """Rotate a refresh token and issue a new access token."""
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    payload = decode_token(refresh_token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    user = db.query(User).filter(User.id == user_id, User.deleted_at == None).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    logger.debug("Refresh token rotated for user_id=%s", user_id)
    access_token = create_access_token(data={"sub": str(user.id)})
    new_refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )

    return TokenResponse(access_token=access_token)


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

    user = db.query(User).filter(User.email == email).first()
    if user:
        if user.provider == "local":
            user.provider = "google"
            if not user.avatar_url:
                user.avatar_url = user_info.get("picture")
            db.commit()
            db.refresh(user)
        logger.info("Existing user signed in via Google: %s", email)
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
        logger.info("New user created via Google OAuth: %s", email)

    access_token = create_access_token(data={"sub": str(user.id)})
    refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=7 * 24 * 60 * 60,
    )
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
