"""Email verification and password reset (HARDENING_PLAN.md P2-H1 follow-up).

No test contacts a mail provider: delivery is captured through the `outbox`
fixture, and the SMTP / Resend transports are patched at their boundary.
"""

import io
import json
import re
import uuid
import wave
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.config import Settings, settings
from backend.core.security import (EMAIL_VERIFICATION_TOKEN_TYPE,
                                   PASSWORD_RESET_TOKEN_TYPE,
                                   create_access_token,
                                   create_email_verification_token,
                                   create_password_reset_token,
                                   password_fingerprint)
from backend.main import app
from backend.models.user import User
from backend.services import email_service

PASSWORD = "Password123!"


@pytest.fixture
def outbox(monkeypatch) -> list[EmailMessage]:
    """Capture every message instead of delivering it."""
    sent: list[EmailMessage] = []
    monkeypatch.setattr(email_service, "deliver", sent.append)
    return sent


@pytest.fixture
def verification_required(monkeypatch) -> None:
    """Turn the gate back on (conftest switches it off for the wider suite)."""
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)


def _signup(client: TestClient, email: str = "new@example.com") -> dict:
    """Sign up and return Bearer headers for the new (unverified) user."""
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "New User"},
    )
    assert resp.status_code == 201
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _token_in(message: EmailMessage) -> str:
    """Extract the token query parameter from the link in a message."""
    link = re.search(r"https?://\S+", message.get_content()).group(0)
    return parse_qs(urlparse(link).query)["token"][0]


def _user(db_session, email: str) -> User:
    db_session.expire_all()
    return db_session.query(User).filter_by(email=email).one()


def _wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 16000 * 3)
    return buf.getvalue()


# --- Signup and verification -------------------------------------------------


def test_signup_sends_verification_link(client: TestClient, outbox, db_session):
    headers = _signup(client)

    assert len(outbox) == 1
    message = outbox[0]
    assert message["To"] == "new@example.com"
    link = urlparse(re.search(r"https?://\S+", message.get_content()).group(0))
    assert link.path == "/verify-email"
    assert f"{link.scheme}://{link.netloc}" == settings.FRONTEND_URL.rstrip("/")

    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["email_verified_at"] is None


def test_verify_email_marks_user_verified_and_is_idempotent(
    client: TestClient, outbox, db_session
):
    headers = _signup(client)
    token = _token_in(outbox[0])

    for _ in range(2):
        resp = client.post("/api/v1/auth/verify-email", json={"token": token})
        assert resp.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).json()["email_verified_at"]


def _expired(claims: dict, token_type: str) -> str:
    payload = {
        **claims,
        "type": token_type,
        "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


def test_verify_email_rejects_bad_tokens(client: TestClient, outbox, db_session):
    _signup(client)
    user = _user(db_session, "new@example.com")
    good = create_email_verification_token(user)
    assert good  # sanity: a real token exists to compare against

    bad_tokens = {
        "garbage": "not-a-jwt",
        "expired": _expired(
            {"sub": str(user.id), "email": user.email}, EMAIL_VERIFICATION_TOKEN_TYPE
        ),
        "access token": create_access_token({"sub": str(user.id)}),
        "reset token": create_password_reset_token(user),
        "other address": jwt.encode(
            {
                "sub": str(user.id),
                "email": "someone-else@example.com",
                "type": EMAIL_VERIFICATION_TOKEN_TYPE,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        ),
        "unknown user": jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "email": user.email,
                "type": EMAIL_VERIFICATION_TOKEN_TYPE,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        ),
        "wrong key": jwt.encode(
            {
                "sub": str(user.id),
                "email": user.email,
                "type": EMAIL_VERIFICATION_TOKEN_TYPE,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            "k" * 40,
            algorithm="HS256",
        ),
    }
    for label, token in bad_tokens.items():
        resp = client.post("/api/v1/auth/verify-email", json={"token": token})
        assert resp.status_code == 400, label
        assert resp.json()["detail"] == "Invalid or expired token", label
    assert _user(db_session, "new@example.com").email_verified_at is None


def test_verify_email_rejects_soft_deleted_user(client: TestClient, outbox, db_session):
    _signup(client)
    token = _token_in(outbox[0])
    _user(db_session, "new@example.com").deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    resp = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 400


def test_verify_email_validates_body(client: TestClient):
    assert client.post("/api/v1/auth/verify-email", json={}).status_code == 422
    assert (
        client.post("/api/v1/auth/verify-email", json={"token": ""}).status_code == 422
    )
    assert (
        client.post("/api/v1/auth/verify-email", json={"token": "x" * 5000}).status_code
        == 422
    )


# --- The verification gate ---------------------------------------------------


def test_unverified_user_cannot_upload_or_synthesize(
    client: TestClient, outbox, verification_required
):
    headers = _signup(client)

    upload = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "V", "consent_confirmed": "true"},
        files={"file": ("v.wav", _wav(), "audio/wav")},
    )
    synth = client.post(
        "/api/v1/synthesize",
        headers=headers,
        json={"text": "hello", "voice_profile_id": str(uuid.uuid4())},
    )
    assert upload.status_code == 403
    assert synth.status_code == 403
    assert upload.json()["detail"] == "Email address not verified"

    # Reading and account endpoints stay available so the user can recover.
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.get("/api/v1/voice/profiles", headers=headers).status_code == 200
    assert client.get("/api/v1/synthesize/history", headers=headers).status_code == 200


def test_verified_user_passes_the_gate(
    client: TestClient, outbox, verification_required
):
    headers = _signup(client)
    client.post("/api/v1/auth/verify-email", json={"token": _token_in(outbox[0])})

    upload = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "V", "consent_confirmed": "true"},
        files={"file": ("v.wav", _wav(), "audio/wav")},
    )
    assert upload.status_code == 201


def test_gate_is_off_when_not_required(client: TestClient, outbox, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", False)
    headers = _signup(client)
    upload = client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "V", "consent_confirmed": "true"},
        files={"file": ("v.wav", _wav(), "audio/wav")},
    )
    assert upload.status_code == 201


# --- Resend ------------------------------------------------------------------


def test_resend_requires_authentication(client: TestClient, outbox):
    assert client.post("/api/v1/auth/resend-verification").status_code == 401
    assert outbox == []


def test_resend_sends_a_fresh_working_link(client: TestClient, outbox):
    headers = _signup(client)
    outbox.clear()

    resp = client.post("/api/v1/auth/resend-verification", headers=headers)
    assert resp.status_code == 202
    assert len(outbox) == 1
    assert (
        client.post(
            "/api/v1/auth/verify-email", json={"token": _token_in(outbox[0])}
        ).status_code
        == 200
    )


def test_resend_is_a_no_op_once_verified(client: TestClient, outbox):
    headers = _signup(client)
    client.post("/api/v1/auth/verify-email", json={"token": _token_in(outbox[0])})
    outbox.clear()

    resp = client.post("/api/v1/auth/resend-verification", headers=headers)
    assert resp.status_code == 202
    assert resp.json()["detail"] == "Email already verified"
    assert outbox == []


# --- Forgot / reset password -------------------------------------------------


def test_forgot_password_is_identical_for_known_and_unknown_addresses(
    client: TestClient, outbox
):
    _signup(client)
    outbox.clear()

    known = client.post(
        "/api/v1/auth/forgot-password", json={"email": "new@example.com"}
    )
    unknown = client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [m["To"] for m in outbox] == ["new@example.com"]


def test_forgot_password_offers_google_accounts_a_set_password_link(
    client: TestClient, outbox
):
    """A Google-only account gets a link that adds a password (see
    test_unified_sign_in.py); the response stays identical to a known address."""
    claims = {
        "email": "g@example.com",
        "email_verified": True,
        "sub": "sub-" + "g@example.com",
        "name": "G",
    }
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": claims},
    ):
        client.get("/api/v1/auth/google/callback?code=c&state=s")

    resp = client.post("/api/v1/auth/forgot-password", json={"email": "g@example.com"})
    assert resp.status_code == 202
    assert [m["To"] for m in outbox] == ["g@example.com"]
    assert outbox[0]["Subject"] == "Set a password for your CloneVoice account"


def test_forgot_password_rejects_malformed_email(client: TestClient):
    resp = client.post("/api/v1/auth/forgot-password", json={"email": "nope"})
    assert resp.status_code == 422


def _request_reset(client: TestClient, outbox, email: str = "new@example.com") -> str:
    outbox.clear()
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    return _token_in(outbox[0])


def test_reset_password_changes_password_and_revokes_sessions(
    client: TestClient, outbox
):
    _signup(client)
    login = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    refresh_cookie = client.cookies.get("refresh_token")
    token = _request_reset(client, outbox)

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "BrandNewPass456!"},
    )
    assert resp.status_code == 200

    old = client.post(
        "/api/v1/auth/login", json={"email": "new@example.com", "password": PASSWORD}
    )
    new = client.post(
        "/api/v1/auth/login",
        json={"email": "new@example.com", "password": "BrandNewPass456!"},
    )
    assert old.status_code == 401
    assert new.status_code == 200

    client.cookies.clear()
    client.cookies.set("refresh_token", refresh_cookie)
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_reset_token_is_single_use(client: TestClient, outbox):
    _signup(client)
    token = _request_reset(client, outbox)
    body = {"token": token, "new_password": "BrandNewPass456!"}

    assert client.post("/api/v1/auth/reset-password", json=body).status_code == 200
    replay = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "AnotherPass789!"},
    )
    assert replay.status_code == 400
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "new@example.com", "password": "BrandNewPass456!"},
        ).status_code
        == 200
    )


def test_older_reset_token_dies_when_a_newer_one_is_used(client: TestClient, outbox):
    _signup(client)
    first = _request_reset(client, outbox)
    second = _request_reset(client, outbox)

    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": second, "new_password": "BrandNewPass456!"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/reset-password",
            json={"token": first, "new_password": "AnotherPass789!"},
        ).status_code
        == 400
    )


def test_reset_password_marks_email_verified(client: TestClient, outbox, db_session):
    """Opening the emailed link proves inbox control, so it verifies the
    address; this is also what lets a real owner take back an address a
    squatter registered first."""
    _signup(client)
    token = _request_reset(client, outbox)
    assert _user(db_session, "new@example.com").email_verified_at is None

    client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "BrandNewPass456!"},
    )
    assert _user(db_session, "new@example.com").email_verified_at is not None


def test_reset_password_rejects_bad_tokens_and_weak_passwords(
    client: TestClient, outbox, db_session
):
    _signup(client)
    user = _user(db_session, "new@example.com")
    bad = {
        "garbage": "nope",
        "verification token": create_email_verification_token(user),
        "access token": create_access_token({"sub": str(user.id)}),
        "expired": _expired(
            {"sub": str(user.id), "pwf": password_fingerprint(user.hashed_password)},
            PASSWORD_RESET_TOKEN_TYPE,
        ),
        "wrong fingerprint": jwt.encode(
            {
                "sub": str(user.id),
                "pwf": "0" * 24,
                "type": PASSWORD_RESET_TOKEN_TYPE,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
            settings.JWT_SECRET_KEY,
            algorithm="HS256",
        ),
    }
    for label, token in bad.items():
        resp = client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "BrandNewPass456!"},
        )
        assert resp.status_code == 400, label

    good = create_password_reset_token(user)
    for weak in ("short", "x" * 129):
        resp = client.post(
            "/api/v1/auth/reset-password", json={"token": good, "new_password": weak}
        )
        assert resp.status_code == 422
    # Neither failure consumed the token or changed the password.
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "new@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_reset_token_is_useless_after_google_link_clears_the_password(
    client: TestClient, outbox
):
    _signup(client)
    token = _request_reset(client, outbox)
    claims = {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "sub-" + "new@example.com",
        "name": "Owner",
    }
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": claims},
    ):
        client.get("/api/v1/auth/google/callback?code=c&state=s")

    resp = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "BrandNewPass456!"},
    )
    assert resp.status_code == 400


# --- Google -----------------------------------------------------------------


def test_google_accounts_are_verified(client: TestClient, db_session):
    claims = {
        "email": "g@example.com",
        "email_verified": True,
        "sub": "sub-" + "g@example.com",
        "name": "G",
    }
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": claims},
    ):
        client.get("/api/v1/auth/google/callback?code=c&state=s")
    assert _user(db_session, "g@example.com").email_verified_at is not None


def test_google_link_verifies_an_unverified_local_account(
    client: TestClient, outbox, db_session
):
    _signup(client)
    assert _user(db_session, "new@example.com").email_verified_at is None
    claims = {
        "email": "new@example.com",
        "email_verified": True,
        "sub": "sub-" + "new@example.com",
        "name": "Owner",
    }
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": claims},
    ):
        client.get("/api/v1/auth/google/callback?code=c&state=s")
    assert _user(db_session, "new@example.com").email_verified_at is not None


# --- Rate limits -------------------------------------------------------------


def test_forgot_password_is_rate_limited(client: TestClient, outbox):
    app.state.limiter.enabled = True
    try:
        codes = [
            client.post(
                "/api/v1/auth/forgot-password", json={"email": "x@example.com"}
            ).status_code
            for _ in range(6)
        ]
    finally:
        app.state.limiter.enabled = False
        app.state.limiter.reset()
    assert codes[:5] == [202] * 5
    assert codes[5] == 429


# --- Email delivery ----------------------------------------------------------


def _message() -> EmailMessage:
    return email_service.build_verification_message("to@example.com", "Ann", "tok")


def test_messages_carry_a_link_and_the_expiry(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.example.com/")
    monkeypatch.setattr(settings, "EMAIL_FROM", "CloneVoice <no-reply@example.com>")

    verify = email_service.build_verification_message("to@example.com", "Ann", "a b")
    reset = email_service.build_password_reset_message("to@example.com", "Ann", "tok")

    assert "https://app.example.com/verify-email?token=a+b" in verify.get_content()
    assert "https://app.example.com/reset-password?token=tok" in reset.get_content()
    assert "24 hours" in verify.get_content()
    assert "30 minutes" in reset.get_content()
    assert verify["From"] == "CloneVoice <no-reply@example.com>"


def test_smtp_backend_uses_starttls_and_login(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "pw")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)

    with patch("backend.services.email_service.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        email_service.deliver(_message())

    smtp_cls.assert_called_once_with(
        "smtp.example.com",
        settings.SMTP_PORT,
        timeout=email_service.DELIVERY_TIMEOUT_SECONDS,
    )
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user", "pw")
    smtp.send_message.assert_called_once()


def test_smtp_backend_skips_starttls_and_login_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "localhost")
    monkeypatch.setattr(settings, "SMTP_USERNAME", "")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", False)

    with patch("backend.services.email_service.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        email_service.deliver(_message())

    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    smtp.send_message.assert_called_once()


def test_resend_backend_posts_json_with_bearer_key(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "resend")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(settings, "EMAIL_FROM", "no-reply@example.com")

    with patch("backend.services.email_service.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value = MagicMock()
        email_service.deliver(_message())

    request = urlopen.call_args.args[0]
    assert request.full_url == email_service.RESEND_API_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer re_test_key"
    body = json.loads(request.data)
    assert body["to"] == ["to@example.com"]
    assert body["subject"] == "Verify your CloneVoice email address"
    assert "verify-email?token=tok" in body["text"]
    assert urlopen.call_args.kwargs["timeout"] == email_service.DELIVERY_TIMEOUT_SECONDS


def test_disabled_backend_sends_nothing_and_does_not_raise(monkeypatch, caplog):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "disabled")
    with patch("backend.services.email_service.smtplib.SMTP") as smtp, patch(
        "backend.services.email_service.urllib.request.urlopen"
    ) as urlopen:
        with caplog.at_level("WARNING"):
            email_service.deliver(_message())
    smtp.assert_not_called()
    urlopen.assert_not_called()
    assert "EMAIL_BACKEND=disabled" in caplog.text


def test_delivery_failure_is_logged_without_the_address_or_link(monkeypatch, caplog):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "smtp")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    user_id = uuid.uuid4()

    with patch(
        "backend.services.email_service.smtplib.SMTP",
        side_effect=OSError("connection refused"),
    ), caplog.at_level("ERROR"):
        email_service.send_verification_email(
            user_id, "victim@example.com", "Ann", "secret-token"
        )  # must not raise

    assert str(user_id) in caplog.text
    assert "victim@example.com" not in caplog.text
    assert "secret-token" not in caplog.text


def test_unexpected_delivery_error_is_also_contained(monkeypatch, caplog):
    monkeypatch.setattr(email_service, "deliver", MagicMock(side_effect=RuntimeError))
    with caplog.at_level("ERROR"):
        email_service.send_password_reset_email(uuid.uuid4(), "a@b.co", "A", "t")
    assert "Unexpected email failure" in caplog.text


def test_signup_still_succeeds_when_email_delivery_fails(
    client: TestClient, monkeypatch
):
    monkeypatch.setattr(
        email_service, "deliver", MagicMock(side_effect=OSError("smtp down"))
    )
    resp = client.post(
        "/api/v1/auth/signup",
        json={"email": "ok@example.com", "password": PASSWORD, "name": "Ok"},
    )
    assert resp.status_code == 201


# --- Configuration -----------------------------------------------------------


def _cfg(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        DATABASE_URL="sqlite://",
        JWT_SECRET_KEY="x" * 40,
        **overrides,
    )


def test_default_email_config_is_fail_safe():
    cfg = _cfg()
    assert cfg.EMAIL_BACKEND == "disabled"
    assert cfg.REQUIRE_EMAIL_VERIFICATION is True


@pytest.mark.parametrize(
    "overrides, missing",
    [
        ({"EMAIL_BACKEND": "resend", "EMAIL_FROM": "a@b.co"}, "RESEND_API_KEY"),
        ({"EMAIL_BACKEND": "resend", "RESEND_API_KEY": "k"}, "EMAIL_FROM"),
        ({"EMAIL_BACKEND": "smtp", "EMAIL_FROM": "a@b.co"}, "SMTP_HOST"),
        ({"EMAIL_BACKEND": "smtp", "SMTP_HOST": "h"}, "EMAIL_FROM"),
        ({"EMAIL_BACKEND": "console"}, "EMAIL_FROM"),
    ],
)
def test_incomplete_email_backend_fails_at_startup(overrides, missing):
    with pytest.raises(ValidationError, match=missing):
        _cfg(**overrides)


def test_complete_email_backends_are_accepted():
    _cfg(EMAIL_BACKEND="resend", RESEND_API_KEY="k", EMAIL_FROM="a@b.co")
    _cfg(EMAIL_BACKEND="smtp", SMTP_HOST="h", EMAIL_FROM="a@b.co")
    _cfg(EMAIL_BACKEND="console", EMAIL_FROM="a@b.co")


@pytest.mark.parametrize(
    "name", ["EMAIL_VERIFICATION_EXPIRE_HOURS", "PASSWORD_RESET_EXPIRE_MINUTES"]
)
@pytest.mark.parametrize("value", [0, -1])
def test_token_lifetimes_must_be_positive(name, value):
    with pytest.raises(ValidationError):
        _cfg(**{name: value})


def test_unknown_email_backend_is_rejected():
    with pytest.raises(ValidationError):
        _cfg(EMAIL_BACKEND="carrier-pigeon")


# --- Password length bounds (pre-existing 500 found while adding reset) ------


def test_oversized_passwords_are_422_not_500(client: TestClient):
    """passlib raises above 4096 characters; that must never reach a 500."""
    huge = "a" * 5000
    signup = client.post(
        "/api/v1/auth/signup",
        json={"email": "big@example.com", "password": huge, "name": "Big"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": "big@example.com", "password": huge}
    )
    assert signup.status_code == 422
    assert login.status_code == 422


def test_long_but_legal_password_round_trips(client: TestClient):
    password = "p" * 128
    client.post(
        "/api/v1/auth/signup",
        json={"email": "long@example.com", "password": password, "name": "Long"},
    )
    resp = client.post(
        "/api/v1/auth/login", json={"email": "long@example.com", "password": password}
    )
    assert resp.status_code == 200
