"""A voice profile records its embedding scheme and is refused if it does not match (S4.5a)."""

from backend.models.voice_profile import VoiceProfile
from backend.services.voice_embedding import EMBEDDING_VERSION
from backend.tests.test_style_override import (_post, auth,  # noqa: F401
                                               profile)


def _row(db):
    db.expire_all()
    return db.query(VoiceProfile).one()


def test_the_version_names_the_sv2tts_scheme():
    assert EMBEDDING_VERSION == "sv2tts-1"


def test_an_upload_records_the_version_and_returns_it(
    client, auth, profile, db_session  # noqa: F811
):
    assert _row(db_session).embedding_version == EMBEDDING_VERSION
    listed = client.get("/api/v1/voice/profiles", headers=auth).json()
    assert listed[0]["embedding_version"] == EMBEDDING_VERSION


def test_a_matching_profile_synthesizes(client, auth, profile):  # noqa: F811
    assert _post(client, auth, profile).status_code == 200


def test_a_profile_from_before_the_version_was_recorded_still_synthesizes(
    client, auth, profile, db_session  # noqa: F811
):
    row = _row(db_session)
    row.embedding_version = None
    db_session.commit()
    assert _post(client, auth, profile).status_code == 200


def test_a_profile_from_another_scheme_is_a_409_and_runs_no_inference(
    client, auth, profile, db_session, monkeypatch  # noqa: F811
):
    from backend.api import synthesize as api

    row = _row(db_session)
    row.embedding_version = "ecapa-1"
    db_session.commit()
    ran = []

    async def boom(*args, **kwargs):
        ran.append(1)

    monkeypatch.setattr(api, "run_inference_pipeline", boom)
    response = _post(client, auth, profile)
    assert response.status_code == 409 and "upload the sample again" in response.text
    assert not ran
