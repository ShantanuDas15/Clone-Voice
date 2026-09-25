"""Tests for refresh-token revocation and /logout (HARDENING_PLAN.md P2-M4)."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.security import create_refresh_token
from backend.models.refresh_token import RefreshToken
from backend.services.refresh_tokens import prune_expired_refresh_tokens
from backend.services.storage_cleanup import _run_cleanup_pass

BASE = "/api/v1/auth"


def _login(client: TestClient, email: str = "rt@example.com") -> str:
    """Sign up + log in; return the refresh cookie value."""
    client.post(
        f"{BASE}/signup",
        json={"email": email, "password": "Password123!", "name": "RT User"},
    )
    resp = client.post(
        f"{BASE}/login", json={"email": email, "password": "Password123!"}
    )
    assert resp.status_code == 200
    return resp.cookies.get("refresh_token")


def _post_with_cookie(client: TestClient, path: str, token):
    """POST with exactly one refresh cookie set on the client's jar."""
    client.cookies.clear()
    if token:
        client.cookies.set("refresh_token", token)
    resp = client.post(path)
    client.cookies.clear()
    return resp


def _refresh(client: TestClient, token: str):
    return _post_with_cookie(client, f"{BASE}/refresh", token)


def _logout(client: TestClient, token):
    return _post_with_cookie(client, f"{BASE}/logout", token)


def _jti(token: str) -> uuid.UUID:
    return uuid.UUID(
        jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])[
            "jti"
        ]
    )


def test_login_stores_refresh_jti(client, db_session) -> None:
    token = _login(client)
    row = db_session.get(RefreshToken, _jti(token))
    assert row is not None and row.revoked_at is None


def test_rotation_revokes_old_token(client, db_session) -> None:
    old = _login(client)
    resp = _refresh(client, old)
    assert resp.status_code == 200
    new = resp.cookies.get("refresh_token")
    assert new != old
    db_session.expire_all()
    assert db_session.get(RefreshToken, _jti(old)).revoked_at is not None
    assert db_session.get(RefreshToken, _jti(new)).revoked_at is None


def test_old_token_cannot_be_reused(client) -> None:
    old = _login(client)
    assert _refresh(client, old).status_code == 200
    assert _refresh(client, old).status_code == 401


def test_replay_of_rotated_token_revokes_the_whole_family(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_SECONDS", 0)
    old = _login(client)
    new = _refresh(client, old).cookies.get("refresh_token")
    assert _refresh(client, old).status_code == 401  # replay detected
    assert _refresh(client, new).status_code == 401  # legit descendant revoked too


def test_new_token_works_after_rotation(client) -> None:
    old = _login(client)
    new = _refresh(client, old).cookies.get("refresh_token")
    assert _refresh(client, new).status_code == 200


def test_unregistered_but_validly_signed_token_is_rejected(client) -> None:
    _login(client)
    forged = create_refresh_token({"sub": str(uuid.uuid4())})
    assert _refresh(client, forged).status_code == 401


def test_token_without_a_stored_row_is_rejected(client, db_session) -> None:
    """E.g. a token minted before this feature shipped."""
    token = _login(client)
    row = db_session.get(RefreshToken, _jti(token))
    db_session.delete(row)
    db_session.commit()
    assert _refresh(client, token).status_code == 401


def test_expired_row_is_rejected(client, db_session) -> None:
    token = _login(client)
    row = db_session.get(RefreshToken, _jti(token))
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    assert _refresh(client, token).status_code == 401


def test_logout_revokes_token_and_clears_cookie(client, db_session) -> None:
    token = _login(client)
    resp = _logout(client, token)
    assert resp.status_code == 204
    assert "refresh_token=" in resp.headers["set-cookie"]
    assert "Max-Age=0" in resp.headers["set-cookie"]
    db_session.expire_all()
    assert db_session.get(RefreshToken, _jti(token)).revoked_at is not None
    assert _refresh(client, token).status_code == 401


@pytest.mark.parametrize("cookie", [None, "garbage", "a.b.c"])
def test_logout_is_idempotent_for_missing_or_bad_cookie(client, cookie) -> None:
    assert _logout(client, cookie).status_code == 204


def test_logout_twice_is_ok(client) -> None:
    token = _login(client)
    for _ in range(2):
        r = _logout(client, token)
        assert r.status_code == 204


def test_logout_does_not_revoke_other_sessions(client) -> None:
    a = _login(client)
    b = client.post(
        f"{BASE}/login", json={"email": "rt@example.com", "password": "Password123!"}
    ).cookies.get("refresh_token")
    _logout(client, a)
    assert _refresh(client, b).status_code == 200


def test_access_token_still_rejected_at_logout_cookie(client) -> None:
    """An access token in the cookie is ignored (204) and revokes nothing."""
    access = client.post(
        f"{BASE}/signup",
        json={"email": "x@example.com", "password": "Password123!", "name": "X"},
    ).json()["access_token"]
    assert _logout(client, access).status_code == 204


@pytest.mark.parametrize("days", [1, 7, 30])
def test_cookie_max_age_follows_setting(client, monkeypatch, days) -> None:
    monkeypatch.setattr(settings, "REFRESH_TOKEN_EXPIRE_DAYS", days)
    client.post(
        f"{BASE}/signup",
        json={"email": "age@example.com", "password": "Password123!", "name": "A"},
    )
    resp = client.post(
        f"{BASE}/login", json={"email": "age@example.com", "password": "Password123!"}
    )
    assert f"Max-Age={days * 86400}" in resp.headers["set-cookie"]


# ---- grace window: two tabs refreshing with one cookie -----------------------


def test_replay_inside_grace_window_is_refused_without_revoking_family(client) -> None:
    old = _login(client)
    new = _refresh(client, old).cookies.get("refresh_token")
    assert _refresh(client, old).status_code == 401  # the losing tab
    assert _refresh(client, new).status_code == 200  # the winner's cookie survives


def test_replay_after_grace_window_revokes_family(client, db_session) -> None:
    old = _login(client)
    new = _refresh(client, old).cookies.get("refresh_token")
    row = db_session.get(RefreshToken, _jti(old))
    row.revoked_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.REFRESH_REUSE_GRACE_SECONDS + 5
    )
    db_session.commit()
    assert _refresh(client, old).status_code == 401
    assert _refresh(client, new).status_code == 401


def test_grace_window_of_zero_is_strict(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "REFRESH_REUSE_GRACE_SECONDS", 0)
    old = _login(client)
    new = _refresh(client, old).cookies.get("refresh_token")
    assert _refresh(client, old).status_code == 401
    assert _refresh(client, new).status_code == 401


def test_logged_out_token_never_refreshes_inside_grace(client) -> None:
    token = _login(client)
    assert _logout(client, token).status_code == 204
    assert _refresh(client, token).status_code == 401


# ---- pruning of long-expired rows -------------------------------------------


def _row(db_session, user_id, expires_in_days: float, revoked: bool = False):
    row = RefreshToken(
        id=uuid.uuid4(),
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _user_id(client, db_session):
    _login(client)
    return db_session.query(RefreshToken.user_id).first()[0]


def test_prune_deletes_only_rows_expired_beyond_the_cutoff(client, db_session) -> None:
    uid = _user_id(client, db_session)
    old_expired = _row(db_session, uid, -3)
    old_revoked = _row(db_session, uid, -3, revoked=True)
    just_expired = _row(db_session, uid, -0.5)
    active = _row(db_session, uid, 5)

    assert prune_expired_refresh_tokens(db_session, older_than_days=1) == 2

    left = {r[0] for r in db_session.query(RefreshToken.id).all()}
    assert old_expired not in left and old_revoked not in left
    assert {just_expired, active} <= left


@pytest.mark.parametrize("days", [0, -1])
def test_prune_disabled_for_non_positive_days(client, db_session, days) -> None:
    uid = _user_id(client, db_session)
    _row(db_session, uid, -30)
    assert prune_expired_refresh_tokens(db_session, older_than_days=days) == 0


def test_prune_uses_the_setting_by_default(client, db_session, monkeypatch) -> None:
    uid = _user_id(client, db_session)
    _row(db_session, uid, -3)
    monkeypatch.setattr(settings, "REFRESH_TOKEN_PRUNE_AFTER_DAYS", 5)
    assert prune_expired_refresh_tokens(db_session) == 0
    monkeypatch.setattr(settings, "REFRESH_TOKEN_PRUNE_AFTER_DAYS", 2)
    assert prune_expired_refresh_tokens(db_session) == 1


def test_cleanup_pass_prunes_expired_refresh_tokens(
    client, db_session, tmp_path
) -> None:
    uid = _user_id(client, db_session)
    stale = _row(db_session, uid, -10)
    active = _row(db_session, uid, 5)

    _run_cleanup_pass([str(tmp_path)], 24, lambda: db_session)

    left = {r[0] for r in db_session.query(RefreshToken.id).all()}
    assert stale not in left and active in left
