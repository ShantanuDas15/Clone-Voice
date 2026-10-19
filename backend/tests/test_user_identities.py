"""Google sign-in matches on the account id (`sub`), not on the email alone."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.user import User
from backend.models.user_identity import UserIdentity
from backend.tests.test_email_verification import (
    PASSWORD,
    _signup,  # noqa: F401
    _token_in,
    _user,
    outbox,
)

EMAIL = "ident@example.com"


def _google(client, sub="sub-1", email=EMAIL, **extra):
    """Run the Google callback for an email-verified identity."""
    info = {"email": email, "email_verified": True, "name": "Owner", **extra}
    if sub is not None:
        info["sub"] = sub
    with patch(
        "backend.api.auth.oauth.google.authorize_access_token",
        new_callable=AsyncMock,
        return_value={"userinfo": info},
    ):
        return client.get("/api/v1/auth/google/callback?code=c&state=s")


def _identities(db_session):
    db_session.expire_all()
    return db_session.query(UserIdentity).all()


def _ok(response) -> bool:
    return response.headers["location"].endswith("/auth/callback")


def test_new_google_user_gets_an_identity(client, db_session):
    assert _ok(_google(client))
    (identity,) = _identities(db_session)
    assert identity.provider == "google"
    assert identity.provider_subject == "sub-1"
    assert identity.email == EMAIL
    assert identity.user_id == _user(db_session, EMAIL).id


def test_repeat_sign_in_reuses_the_identity(client, db_session):
    _google(client)
    assert _ok(_google(client))
    assert len(_identities(db_session)) == 1
    assert db_session.query(User).count() == 1


def test_same_account_with_a_changed_email_signs_into_the_same_user(client, db_session):
    """The account id, not the address, identifies the person."""
    _google(client, sub="sub-1", email=EMAIL)
    assert _ok(_google(client, sub="sub-1", email="renamed@example.com"))
    assert db_session.query(User).count() == 1
    assert _user(db_session, EMAIL).id == _identities(db_session)[0].user_id


def test_other_google_account_with_a_linked_address_is_refused(client, db_session):
    """A recycled or reassigned address must not open someone else's account."""
    _google(client, sub="sub-owner")
    response = _google(client, sub="sub-intruder")
    assert response.headers["location"].endswith("/login?error=google_account_conflict")
    assert "refresh_token" not in response.cookies
    assert [i.provider_subject for i in _identities(db_session)] == ["sub-owner"]
    assert _ok(_google(client, sub="sub-owner"))  # the owner is unaffected


def test_local_account_gets_an_identity_when_google_is_linked(
    client, outbox, db_session
):
    _signup(client, EMAIL)
    assert _ok(_google(client))
    (identity,) = _identities(db_session)
    assert identity.user_id == _user(db_session, EMAIL).id


def test_legacy_google_user_gets_an_identity_on_next_sign_in(client, db_session):
    """Google users from before identities are matched by email one last time."""
    db_session.add(
        User(
            email=EMAIL,
            name="Legacy",
            provider="google",
            email_verified_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    assert _ok(_google(client, sub="sub-legacy"))

    assert db_session.query(User).count() == 1
    assert [i.provider_subject for i in _identities(db_session)] == ["sub-legacy"]


@pytest.mark.parametrize("sub", [None, "", "x" * 256])
def test_missing_or_unusable_subject_is_refused(client, db_session, sub):
    response = _google(client, sub=sub)
    assert response.headers["location"].endswith("/login?error=google_failed")
    assert "refresh_token" not in response.cookies
    assert db_session.query(User).count() == 0
    assert _identities(db_session) == []


def test_identity_of_a_deleted_user_is_refused(client, db_session):
    _google(client)
    user = _user(db_session, EMAIL)
    user.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    response = _google(client)

    assert response.headers["location"].endswith("/login?error=google_failed")
    assert "refresh_token" not in response.cookies


def test_a_subject_can_belong_to_only_one_identity(db_session):
    """The database, not just the code, refuses a duplicate Google account."""
    users = [
        User(email=f"u{i}@example.com", name="U", provider="google") for i in (1, 2)
    ]
    db_session.add_all(users)
    db_session.flush()
    db_session.add(
        UserIdentity(
            user_id=users[0].id,
            provider="google",
            provider_subject="dup",
            email="a@x.com",
        )
    )
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                UserIdentity(
                    user_id=users[1].id,
                    provider="google",
                    provider_subject="dup",
                    email="b@x.com",
                )
            )


def test_a_lost_race_on_commit_is_refused_cleanly(client, db_session):
    """If a concurrent sign-in wins, this one is rolled back and refused, not a
    500. (`rollback` is stubbed so the fixture's own transaction survives.)"""
    with patch.object(
        db_session, "commit", side_effect=IntegrityError("stmt", {}, Exception("dup"))
    ), patch.object(db_session, "rollback") as rollback:
        response = _google(client)
    rollback.assert_called_once()
    assert response.status_code == 302
    assert response.headers["location"].endswith("/login?error=google_failed")
    assert "refresh_token" not in response.cookies
