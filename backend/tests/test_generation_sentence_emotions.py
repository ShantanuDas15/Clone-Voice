"""A generation records its per-sentence emotions and dropped sound tags (SPEECH_QUALITY_PLAN.md S7.1f)."""

import pytest

from backend.api import synthesize as api
from backend.models.generation import Generation
from backend.services.tts_pipeline import InferenceResult
from backend.tests.test_seed import auth, profile  # noqa: F401


def _post(client, auth, profile, text="Hello there."):
    return client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": text},
    )


def _row(db, text):
    db.expire_all()
    return db.query(Generation).filter(Generation.input_text == text).one()


def _speak_with(monkeypatch, **facts):
    real = api.run_inference_pipeline

    async def run(*args, **kwargs):
        r = await real(*args, **kwargs)
        return InferenceResult(r[0], r[1], "chatterbox", "1", **facts)

    monkeypatch.setattr(api, "run_inference_pipeline", run)


def test_a_plain_request_records_none(client, auth, profile, db_session):
    assert _post(client, auth, profile).status_code == 200
    row = _row(db_session, "Hello there.")
    assert (row.emotions_used, row.sound_tags_dropped) == (None, None)


def test_sentence_emotions_are_recorded_in_order(
    client, auth, profile, db_session, monkeypatch
):
    _speak_with(monkeypatch, emotions_used=("neutral", "angry", "sad"))
    assert _post(client, auth, profile).status_code == 200
    assert _row(db_session, "Hello there.").emotions_used == "neutral,angry,sad"


def test_dropped_sound_tags_are_recorded_by_the_real_pipeline(
    client, auth, profile, db_session
):
    text = "Ha [laugh] ok [cough]."
    assert _post(client, auth, profile, text).status_code == 200
    assert _row(db_session, text).sound_tags_dropped == "laugh,cough"


def test_history_returns_both_as_lists(client, auth, profile, monkeypatch):
    _speak_with(
        monkeypatch, emotions_used=("happy", "sad"), sound_tags_dropped=("laugh",)
    )
    _post(client, auth, profile, "Ha [laugh] ok.")
    (item,) = client.get("/api/v1/synthesize/history", headers=auth).json()
    assert item["emotions_used"] == ["happy", "sad"]
    assert item["sound_tags_dropped"] == ["laugh"]


@pytest.mark.parametrize("stored", [None, ""])
def test_history_returns_none_for_an_empty_value(
    client, auth, profile, db_session, stored
):
    _post(client, auth, profile)
    row = _row(db_session, "Hello there.")
    row.emotions_used = stored
    db_session.commit()
    (item,) = client.get("/api/v1/synthesize/history", headers=auth).json()
    assert item["emotions_used"] is None
