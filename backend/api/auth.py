"""Authentication API routes and handlers."""

import asyncio
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import (APIRouter, BackgroundTasks, Cookie, Depends,
                     HTTPException, Request, Response, status)
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.rate_limit import limiter
from backend.core.security import (EMAIL_VERIFICATION_TOKEN_TYPE,
                                   PASSWORD_RESET_TOKEN_TYPE,
                                   REFRESH_TOKEN_TYPE, create_access_token,
                                   create_email_verification_token,
                                   create_password_reset_token,
                                   decode_purpose_token, decode_token,
                                   get_current_user, hash_email_for_logging,
                                   hash_password, password_fingerprint,
                                   verify_password, verify_password_or_dummy)
from backend.models.user import User
from backend.models.user_identity import UserIdentity
from backend.schemas.auth import (ForgotPasswordRequest, LoginRequest,
                                  MessageResponse, ResetPasswordRequest,
                                  SignupRequest, TokenResponse,
                                  UpdateUserRequest, UserOut,
                                  VerifyEmailRequest)
from backend.services.email_service import (send_password_reset_email,
                                            send_verification_email)
from backend.services.refresh_tokens import (consume_refresh_token,
                                             issue_refresh_token,
                                             parse_refresh_claims,
                                             revoke_all_for_user)

logger = logging.getLogger(__name__)

router = APIRouter()

# Where the Google callback sends the browser, relative to FRONTEND_URL. The
# web app must serve both: the first calls POST /refresh, the second shows the
# `error` query code.
GOOGLE_SUCCESS_PATH = "/auth/callback"
GOOGLE_FAILURE_PATH = "/login"


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
def signup(
    request: Request,
    user_in: SignupRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Register a new local user, email a verification link, return a token."""
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
    # Sent after the response, so a slow or failing mail provider neither
    # delays nor breaks signup; the user can request another link.
    background_tasks.add_task(
        send_verification_email,
        new_user.id,
        new_user.email,
        new_user.name,
        create_email_verification_token(new_user),
    )
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
    user = (
        db.query(User)
        .filter(User.email == user_in.email, User.deleted_at.is_(None))
        .first()
    )
    # Always spend one bcrypt verification, even for an unknown email or an
    # account with no password, so response time does not reveal which
    # addresses are registered.
    password_ok = verify_password_or_dummy(
        user_in.password, user.hashed_password if user else None
    )
    if not user or not password_ok:
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
@limiter.limit(settings.AUTH_REFRESH_RATE_LIMIT)
def refresh(
    request: Request,
    response: Response,
    refresh_token: str = Cookie(None),
    db: Session = Depends(get_db),
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


def _user_from_token_claims(db: Session, claims: Optional[dict]) -> Optional[User]:
    """Load the live user a purpose token's `sub` names, or None."""
    if not claims:
        return None
    try:
        user_id = uuid.UUID(str(claims.get("sub")))
    except ValueError:
        return None
    return db.query(User).filter(User.id == user_id, User.deleted_at == None).first()


@router.post("/verify-email", response_model=MessageResponse)
@limiter.limit(settings.AUTH_TOKEN_RATE_LIMIT)
def verify_email(
    request: Request, body: VerifyEmailRequest, db: Session = Depends(get_db)
):
    """Mark the address verified when given a valid emailed token (idempotent)."""
    claims = decode_purpose_token(body.token, EMAIL_VERIFICATION_TOKEN_TYPE)
    user = _user_from_token_claims(db, claims)
    # The token is bound to the address it was sent to: it stops working if
    # the account's email ever changes.
    if user is None or claims.get("email") != user.email.lower():
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        db.commit()
        logger.info("Email verified: user_id=%s", user.id)
    return MessageResponse(detail="Email verified")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(settings.AUTH_EMAIL_RATE_LIMIT)
def resend_verification(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Email the signed-in user a fresh verification link."""
    if current_user.email_verified_at is not None:
        return MessageResponse(detail="Email already verified")
    background_tasks.add_task(
        send_verification_email,
        current_user.id,
        current_user.email,
        current_user.name,
        create_email_verification_token(current_user),
    )
    return MessageResponse(detail="Verification email sent")


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(settings.AUTH_EMAIL_RATE_LIMIT)
def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Email a link to set or reset the password of a known address.

    A Google-only account gets the same link: following it proves control of
    the inbox and adds email/password sign-in beside Google.

    The response is identical whether or not the address is registered, so
    this cannot be used to discover which emails have accounts.
    """
    user = (
        db.query(User).filter(User.email == body.email, User.deleted_at == None).first()
    )
    if user is not None:
        background_tasks.add_task(
            send_password_reset_email,
            user.id,
            user.email,
            user.name,
            create_password_reset_token(user),
            bool(user.hashed_password),
        )
    else:
        logger.info(
            "Password reset requested for an unknown address: email_hash=%s",
            hash_email_for_logging(body.email),
        )
    return MessageResponse(
        detail="If that address has an account, a reset link has been sent"
    )


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(settings.AUTH_TOKEN_RATE_LIMIT)
def reset_password(
    request: Request, body: ResetPasswordRequest, db: Session = Depends(get_db)
):
    """Set a new password with a valid, unused reset token."""
    claims = decode_purpose_token(body.token, PASSWORD_RESET_TOKEN_TYPE)
    user = _user_from_token_claims(db, claims)
    # The fingerprint no longer matches once the password has changed, so a
    # token cannot be replayed (or used after a Google link cleared it).
    if user is None or not hmac.compare_digest(
        str(claims.get("pwf", "")), password_fingerprint(user.hashed_password)
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.hashed_password = hash_password(body.new_password)
    if user.email_verified_at is None:
        # Opening the emailed link proves control of the inbox.
        user.email_verified_at = datetime.now(timezone.utc)
    db.commit()
    # Every existing session is suspect if the password had to be reset.
    revoked = revoke_all_for_user(db, user.id)
    logger.info("Password reset, revoked %d session(s): user_id=%s", revoked, user.id)
    return MessageResponse(detail="Password updated")


GOOGLE_PROVIDER = "google"


class GoogleSignInRefused(Exception):
    """Google sign-in must not go ahead; `code` is the login-page error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _link_google_to_existing_user(user: User, user_info: dict) -> bool:
    """Apply the account-linking rules; return True if sessions must be revoked.

    Only a `local` account changes. HARDENING_PLAN.md finding P2-H1: an
    *unverified* local signup never proved ownership of the address, while
    Google just did, so its password is dropped (whoever registered the
    address first must not keep signing in) and its sessions are revoked. A
    *verified* account already proved the inbox, so it is the same owner: the
    password stays and the person can sign in either way. A legacy Google
    account (no identity row yet) is left as it is.
    """
    if user.provider != "local":
        return False
    user.provider = GOOGLE_PROVIDER
    if not user.avatar_url:
        user.avatar_url = user_info.get("picture")
    if user.email_verified_at is not None:
        logger.info(
            "Linked Google to verified local account, kept password: user_id=%s",
            user.id,
        )
        return False
    user.hashed_password = None
    return True


def _sign_in_google_user(
    db: Session, subject: str, email: str, user_info: dict
) -> tuple[str, str]:
    """Find, link or create the Google user and issue a refresh token.

    The user is found by the Google account id (`subject`), never by email
    alone once an identity exists: an address can change hands, an account id
    cannot. Only the first sign-in of an account with no identity row yet (a
    new user, a local signup, or a Google user from before identities) falls
    back to the email, and it records the identity in the same transaction.
    Raises `GoogleSignInRefused` when the sign-in must not proceed.

    All blocking DB work for the callback lives here so the async route can run
    it off the event loop (HARDENING_PLAN.md finding P2-L5). Returns the user's
    id (as a string) and the new refresh token.
    """
    identity = (
        db.query(UserIdentity)
        .filter(
            UserIdentity.provider == GOOGLE_PROVIDER,
            UserIdentity.provider_subject == subject,
        )
        .first()
    )
    revoke_sessions = False
    if identity is not None:
        user = (
            db.query(User)
            .filter(User.id == identity.user_id, User.deleted_at.is_(None))
            .first()
        )
        if user is None:
            logger.warning("Google sign-in for a deleted account refused")
            raise GoogleSignInRefused("google_failed")
        logger.info("Existing user signed in via Google: user_id=%s", user.id)
    else:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            user = User(
                email=email,
                name=user_info.get("name") or "Google User",
                avatar_url=user_info.get("picture"),
                provider=GOOGLE_PROVIDER,
                email_verified_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.flush()
            logger.info("New user created via Google OAuth: user_id=%s", user.id)
        else:
            already_linked = (
                db.query(UserIdentity.id)
                .filter(
                    UserIdentity.user_id == user.id,
                    UserIdentity.provider == GOOGLE_PROVIDER,
                )
                .first()
            )
            if already_linked is not None:
                # This address belongs to an account already tied to a
                # different Google account: never hand it to this one.
                logger.warning(
                    "Google sign-in refused, address already linked to another "
                    "Google account: user_id=%s",
                    user.id,
                )
                raise GoogleSignInRefused("google_account_conflict")
            revoke_sessions = _link_google_to_existing_user(user, user_info)
        db.add(
            UserIdentity(
                user_id=user.id,
                provider=GOOGLE_PROVIDER,
                provider_subject=subject,
                email=email,
            )
        )

    if user.email_verified_at is None:
        # Google has verified this address (the callback refuses any it has
        # not), so the account is verified whichever way it began.
        user.email_verified_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first sign-in recorded this identity (or address)
        # first; the next attempt finds it.
        db.rollback()
        logger.warning("Google identity was linked concurrently; sign-in refused")
        raise GoogleSignInRefused("google_failed")
    db.refresh(user)

    if revoke_sessions:
        # A session the squatter already holds must not outlive the link (the
        # password alone isn't the only way in: refresh cookies work for up to
        # REFRESH_TOKEN_EXPIRE_DAYS). Only this first link revokes.
        revoked = revoke_all_for_user(db, user.id)
        logger.info(
            "Linked Google to unverified local account, revoked %d session(s): "
            "user_id=%s",
            revoked,
            user.id,
        )

    refresh_token = issue_refresh_token(db, user.id)
    return str(user.id), refresh_token


@router.get("/google")
async def google_login(request: Request):
    """Redirect user to Google OAuth consent screen."""
    redirect_uri = settings.GOOGLE_REDIRECT_URI or str(
        request.url_for("google_callback")
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


def _frontend_redirect(path: str, **query: str) -> RedirectResponse:
    """Redirect the browser into the web app (target comes from settings only)."""
    url = f"{settings.FRONTEND_URL.rstrip('/')}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"
    return response


def _google_failure(code: str) -> RedirectResponse:
    """Send the browser back to the login page with a stable error code."""
    return _frontend_redirect(GOOGLE_FAILURE_PATH, error=code)


@router.get("/google/callback", include_in_schema=False)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """Finish the Google sign-in and hand the browser back to the web app.

    This is a top-level browser navigation, so it answers with a redirect,
    never JSON. Success sets the refresh cookie and lands on
    `GOOGLE_SUCCESS_PATH`; the client then calls `POST /refresh` for its
    access token, so no token ever appears in a URL. Failure lands on
    `GOOGLE_FAILURE_PATH?error=<code>`, where the code is `google_failed`,
    `google_no_email`, `google_email_unverified` or `google_account_conflict`.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            user_info = await oauth.google.parse_id_token(request, token)
    except OAuthError as error:
        logger.warning("OAuth error during Google callback: %s", error.error)
        return _google_failure("google_failed")
    except Exception:
        logger.exception("Unexpected error during Google OAuth callback")
        return _google_failure("google_failed")

    email = user_info.get("email")
    if not email:
        return _google_failure("google_no_email")
    email = email.strip().lower()

    if user_info.get("email_verified") is not True:
        logger.warning("Google sign-in rejected: email not verified by provider")
        return _google_failure("google_email_unverified")

    subject = user_info.get("sub")
    if not isinstance(subject, str) or not 0 < len(subject) <= 255:
        logger.warning("Google sign-in rejected: no usable account id (sub)")
        return _google_failure("google_failed")

    try:
        _, refresh_token = await asyncio.to_thread(
            _sign_in_google_user, db, subject, email, user_info
        )
    except GoogleSignInRefused as refused:
        return _google_failure(refused.code)

    response = _frontend_redirect(GOOGLE_SUCCESS_PATH)
    _set_refresh_cookie(response, refresh_token)
    return response


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
