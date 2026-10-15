"""A failed generation still records what was asked (SPEECH_QUALITY_PLAN.md S7.1e)."""

import pytest

from backend.api import synthesize as api
from backend.models.generation import Generation
from backend.services.tts_pipeline import (InferenceTimeoutError,
                                           OutputQualityError)
from backend.tests.test_seed import _post, auth, profile  # noqa: F401


def _failing(error):
    async def run(*_args, **_kwargs):
        raise error

    return run


def _row(db):
    db.expire_all()
    return db.query(Generation).filter(Generation.input_text == "Hello there.").one()


def test_a_failed_request_records_emotion_intensity_and_seed(
    client, auth, profile, db_session, monkeypatch
):
    monkeypatch.setattr(api, "run_inference_pipeline", _failing(RuntimeError("boom")))
    response = _post(client, auth, profile, emotion="angry", intensity=0.4, seed=11)
    assert response.status_code == 500
    row = _row(db_session)
    assert row.status == "failed"
    assert (row.emotion, row.intensity, row.seed) == ("angry", 0.4, 11)


def test_nothing_is_marked_applied_on_a_failed_row(
    client, auth, profile, db_session, monkeypatch
):
    monkeypatch.setattr(api, "run_inference_pipeline", _failing(RuntimeError("boom")))
    _post(client, auth, profile, emotion="sad", seed=3)
    row = _row(db_session)
    assert (row.style_applied, row.seed_applied) == (None, None)


def test_a_seed_of_zero_is_recorded_on_a_failed_row(
    client, auth, profile, db_session, monkeypatch
):
    monkeypatch.setattr(api, "run_inference_pipeline", _failing(RuntimeError("boom")))
    _post(client, auth, profile, seed=0)
    assert _row(db_session).seed == 0


def test_a_failed_request_with_no_options_records_none(
    client, auth, profile, db_session, monkeypatch
):
    monkeypatch.setattr(api, "run_inference_pipeline", _failing(RuntimeError("boom")))
    _post(client, auth, profile)
    row = _row(db_session)
    assert (row.emotion, row.intensity, row.seed) == (None, None, None)


@pytest.mark.parametrize(
    "error, status",
    [
        (InferenceTimeoutError(), 503),
        (OutputQualityError(["truncated"]), 502),
    ],
)
def test_every_failure_path_records_the_request(
    client, auth, profile, db_session, monkeypatch, error, status
):
    monkeypatch.setattr(api, "run_inference_pipeline", _failing(error))
    assert _post(client, auth, profile, seed=5).status_code == status
    assert _row(db_session).seed == 5
