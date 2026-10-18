"""S7.4c: the synthesize rate limit follows the engine that serves the caller, canary included."""

import uuid
from datetime import timedelta
from functools import lru_cache

import jwt
import pytest
from fastapi import Request

from backend.core import rate_limit
from backend.core.config import settings
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.models.user import User
from backend.services.tts_engine import (
    canary_bucket,
    engine_name_for_user,
    get_engine_for_user,
)
from backend.tests.test_rate_limit import fresh_limiter  # noqa: F401

CANARY = "chatterbox_nano"
LIMITS = {CANARY: "1/minute"}


@pytest.fixture(autouse=True)
def canary_half_on(monkeypatch):
    """Half the users are canary on a slow engine with its own, tighter limit."""
    monkeypatch.setattr(settings, "TTS_CANARY_ENGINE", CANARY)
    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 50)
    monkeypatch.setattr(settings, "SYNTHESIZE_RATE_LIMIT", "3/minute")
    monkeypatch.setattr(settings, "SYNTHESIZE_RATE_LIMIT_BY_ENGINE", dict(LIMITS))


def _id_in_canary(canary: bool) -> str:
    """A fresh user id that does (or does not) fall in the canary share."""
    while True:
        candidate = str(uuid.uuid4())
        if (canary_bucket(candidate) < settings.TTS_CANARY_PERCENT) is canary:
            return candidate


def _request(authorization: str = "", client: str = "203.0.113.7") -> Request:
    """A bare request carrying only an Authorization header and a peer address."""
    headers = [(b"authorization", authorization.encode())] if authorization else []
    return Request(
        {"type": "http", "headers": headers, "client": (client, 5000), "method": "POST"}
    )


def _bearer(user_id: str) -> str:
    return "Bearer " + create_access_token({"sub": user_id})


# --- engine_name_for_user ----------------------------------------------------


def test_the_name_follows_the_canary_share_and_matches_the_engine_served():
    inside, outside = _id_in_canary(True), _id_in_canary(False)

    assert engine_name_for_user(inside) == CANARY
    assert engine_name_for_user(outside) == settings.TTS_ENGINE
    assert get_engine_for_user(inside).name == CANARY
    assert get_engine_for_user(outside).name == settings.TTS_ENGINE


def test_the_name_is_stable_and_off_means_everyone_on_the_primary(monkeypatch):
    user = _id_in_canary(True)
    assert {engine_name_for_user(user) for _ in range(5)} == {CANARY}

    monkeypatch.setattr(settings, "TTS_CANARY_PERCENT", 0)
    assert engine_name_for_user(user) == settings.TTS_ENGINE


def test_looking_up_a_name_never_builds_an_engine(monkeypatch):
    @lru_cache(maxsize=None)  # the shared fixtures call `_build.cache_clear()`
    def boom(name):
        raise AssertionError("an engine was built")

    monkeypatch.setattr("backend.services.tts_engine._build", boom)

    assert engine_name_for_user(_id_in_canary(True)) == CANARY


# --- synthesize_key ----------------------------------------------------------


def test_the_key_carries_the_callers_engine_and_address():
    inside, outside = _id_in_canary(True), _id_in_canary(False)

    assert (
        rate_limit.synthesize_key(_request(_bearer(inside))) == f"{CANARY}|203.0.113.7"
    )
    assert (
        rate_limit.synthesize_key(_request(_bearer(outside)))
        == f"{settings.TTS_ENGINE}|203.0.113.7"
    )


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer",
        "Bearer ",
        "Bearer not-a-jwt",
        "Basic dXNlcjpwYXNz",
        "bearer-without-space",
    ],
)
def test_an_unidentifiable_caller_is_limited_as_the_primary_engine(authorization):
    key = rate_limit.synthesize_key(_request(authorization))

    assert key == f"{settings.TTS_ENGINE}|203.0.113.7"


def test_a_token_that_does_not_prove_anything_cannot_pick_the_canary_limit():
    inside = _id_in_canary(True)
    primary_key = f"{settings.TTS_ENGINE}|203.0.113.7"
    forged = jwt.encode(
        {"sub": inside, "type": "access"},
        "a-different-signing-secret-of-adequate-length-0123456789",
        "HS256",
    )
    expired = create_access_token({"sub": inside}, expires_delta=timedelta(seconds=-5))
    wrong_type = create_refresh_token({"sub": inside})
    no_subject = create_access_token({"name": "x"})
    numeric_subject = create_access_token({"sub": 12345})

    for token in (forged, expired, wrong_type, no_subject, numeric_subject):
        assert rate_limit.synthesize_key(_request(f"Bearer {token}")) == primary_key


def test_the_key_still_uses_the_proxy_aware_client_address(monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 1)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"198.51.100.9, 10.0.0.1")],
            "client": ("10.0.0.1", 1),
            "method": "POST",
        }
    )

    assert rate_limit.synthesize_key(request).endswith("|10.0.0.1")


# --- synthesize_limit --------------------------------------------------------


def test_the_limit_is_read_from_the_engine_in_the_key():
    assert rate_limit.synthesize_limit(f"{CANARY}|1.2.3.4") == "1/minute"
    assert rate_limit.synthesize_limit("sv2tts|1.2.3.4") == "3/minute"
    assert rate_limit.synthesize_limit("unknown_engine|1.2.3.4") == "3/minute"


def test_a_direct_call_uses_the_active_engine(monkeypatch):
    assert rate_limit.synthesize_limit() == "3/minute"
    monkeypatch.setattr(settings, "TTS_ENGINE", CANARY)
    assert rate_limit.synthesize_limit() == "1/minute"
    assert rate_limit.synthesize_limit("no-separator-here") == "1/minute"


# --- the route ---------------------------------------------------------------


def _make_user(db, user_id: str) -> dict:
    db.add(
        User(
            id=uuid.UUID(user_id),
            email=f"{user_id}@example.com",
            name="Canary test",
            provider="local",
        )
    )
    db.commit()
    return {"Authorization": _bearer(user_id)}


def _post(client, headers) -> int:
    """POST /synthesize for an unknown voice: reaches the limit, then answers 404."""
    body = {"voice_profile_id": str(uuid.uuid4()), "text": "Rate limit test payload"}
    return client.post("/api/v1/synthesize", headers=headers, json=body).status_code


def test_a_canary_user_is_limited_at_the_canary_engines_override(
    client, db_session, fresh_limiter
):
    headers = _make_user(db_session, _id_in_canary(True))
    codes = [_post(client, headers) for _ in range(3)]

    assert codes[0] != 429 and codes[1:] == [429, 429]


def test_a_user_outside_the_canary_keeps_the_default_and_is_not_affected(
    client, db_session, fresh_limiter
):
    canary = _make_user(db_session, _id_in_canary(True))
    regular = _make_user(db_session, _id_in_canary(False))
    canary_codes = [_post(client, canary) for _ in range(2)]
    regular_codes = [_post(client, regular) for _ in range(4)]

    assert canary_codes[-1] == 429  # the canary user hit their tight limit
    assert 429 not in regular_codes[:3] and regular_codes[3] == 429  # 3/minute


def test_two_canary_users_behind_one_address_share_the_engines_window(
    client, db_session, fresh_limiter
):
    """The limit stays per address (as before); the engine only chooses its size."""
    first = _make_user(db_session, _id_in_canary(True))
    second = _make_user(db_session, _id_in_canary(True))
    codes = [_post(client, first), _post(client, second)]

    assert codes[0] != 429 and codes[1] == 429


def test_decode_token_is_what_vouches_for_the_subject():
    """The key trusts exactly what the auth dependency trusts: a verified access token."""
    user = _id_in_canary(True)

    assert decode_token(_bearer(user).split(" ", 1)[1])["sub"] == user
