"""The speaker-is-an-adult attestation on voice upload (SPEECH_QUALITY_PLAN.md decision Q4)."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.models.voice_profile import VoiceProfile
from backend.tests.test_voice import auth_headers  # noqa: F401  (pytest fixture)
from backend.tests.test_voice import create_dummy_wav

FLAG = "backend.core.config.settings.REQUIRE_ADULT_CONFIRMATION"


def _upload(client: TestClient, headers, **extra):
    """POST a valid sample with consent, plus any extra form fields."""
    return client.post(
        "/api/v1/voice/upload",
        headers=headers,
        data={"name": "Adult Voice", "consent_confirmed": "true", **extra},
        files={"file": ("a.wav", create_dummy_wav(), "audio/wav")},
    )


def _add(client: TestClient, headers, profile_id: str, **extra):
    """POST one more clip to an existing profile, with consent plus extra fields."""
    return client.post(
        f"/api/v1/voice/profiles/{profile_id}/samples",
        headers=headers,
        data={"consent_confirmed": "true", **extra},
        files={"file": ("b.wav", create_dummy_wav(), "audio/wav")},
    )


def _rows(db_session):
    """Every voice profile row, fresh from the database."""
    db_session.expire_all()
    return db_session.query(VoiceProfile).all()


def test_flag_defaults_to_off_so_existing_clients_keep_working(
    client: TestClient, auth_headers, db_session
) -> None:
    from backend.core.config import settings

    assert settings.REQUIRE_ADULT_CONFIRMATION is False
    response = _upload(client, auth_headers)
    assert response.status_code == 201
    assert _rows(db_session)[0].adult_confirmed_at is None


def test_the_attestation_is_recorded_when_sent_even_with_the_flag_off(
    client: TestClient, auth_headers, db_session
) -> None:
    response = _upload(client, auth_headers, speaker_is_adult="true")
    assert response.status_code == 201
    row = _rows(db_session)[0]
    assert row.adult_confirmed_at is not None
    assert row.adult_confirmed_at == row.consent_confirmed_at


def test_a_false_attestation_is_not_recorded(
    client: TestClient, auth_headers, db_session
) -> None:
    assert _upload(client, auth_headers, speaker_is_adult="false").status_code == 201
    assert _rows(db_session)[0].adult_confirmed_at is None


def test_with_the_flag_on_a_missing_attestation_is_refused(
    client: TestClient, auth_headers, db_session
) -> None:
    with patch(FLAG, True):
        response = _upload(client, auth_headers)
    assert response.status_code == 422
    assert "adult" in response.json()["detail"].lower()
    assert _rows(db_session) == []


def test_with_the_flag_on_a_false_attestation_is_refused(
    client: TestClient, auth_headers, db_session
) -> None:
    with patch(FLAG, True):
        response = _upload(client, auth_headers, speaker_is_adult="false")
    assert response.status_code == 422
    assert _rows(db_session) == []


def test_with_the_flag_on_the_attestation_is_accepted_and_recorded(
    client: TestClient, auth_headers, db_session
) -> None:
    with patch(FLAG, True):
        response = _upload(client, auth_headers, speaker_is_adult="true")
    assert response.status_code == 201
    assert _rows(db_session)[0].adult_confirmed_at is not None


def test_the_refusal_happens_before_any_file_work(
    client: TestClient, auth_headers, db_session
) -> None:
    """A refused upload stores no audio, so a child's clip is never written to disk."""
    from backend.core.config import settings

    root = os.path.join(settings.UPLOAD_DIR)
    before = (
        sum(len(names) for _, _, names in os.walk(root)) if os.path.isdir(root) else 0
    )
    with patch(FLAG, True):
        assert _upload(client, auth_headers).status_code == 422
    after = (
        sum(len(names) for _, _, names in os.walk(root)) if os.path.isdir(root) else 0
    )
    assert after == before


def test_the_consent_checkbox_is_still_required_first(
    client: TestClient, auth_headers
) -> None:
    with patch(FLAG, True):
        response = client.post(
            "/api/v1/voice/upload",
            headers=auth_headers,
            data={
                "name": "x",
                "consent_confirmed": "false",
                "speaker_is_adult": "true",
            },
            files={"file": ("a.wav", create_dummy_wav(), "audio/wav")},
        )
    assert response.status_code == 422
    assert "right to use" in response.json()["detail"]


def test_adding_a_clip_also_needs_the_attestation_when_the_flag_is_on(
    client: TestClient, auth_headers, db_session
) -> None:
    profile_id = _upload(client, auth_headers, speaker_is_adult="true").json()["id"]

    with patch(FLAG, True):
        refused = _add(client, auth_headers, profile_id)
        accepted = _add(client, auth_headers, profile_id, speaker_is_adult="true")

    assert refused.status_code == 422
    assert accepted.status_code == 201
    assert len(accepted.json()["samples"]) == 2


def test_adding_a_clip_without_the_attestation_works_with_the_flag_off(
    client: TestClient, auth_headers
) -> None:
    profile_id = _upload(client, auth_headers).json()["id"]
    assert _add(client, auth_headers, profile_id).status_code == 201


def test_the_account_export_lists_when_the_adult_attestation_was_given(
    client: TestClient, db_session
) -> None:
    from datetime import datetime, timezone

    from backend.models.user import User
    from backend.tests.test_account_export import PASSWORD, URL
    from backend.tests.test_account_export import _json, _open, _signup, _voice

    headers = _signup(client)
    user = db_session.query(User).one()
    attested, _, _ = _voice(db_session, user, "attested")
    plain, _, _ = _voice(db_session, user, "plain")
    attested.adult_confirmed_at = datetime(2026, 10, 22, tzinfo=timezone.utc)
    db_session.commit()

    response = client.post(URL, headers=headers, json={"password": PASSWORD})

    by_name = {p["name"]: p for p in _json(_open(response), "voice_profiles.json")}
    assert by_name["attested"]["adult_confirmed_at"].startswith("2026-10-22")
    assert by_name["plain"]["adult_confirmed_at"] is None
