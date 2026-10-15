"""A generation records the seed that was asked for (SPEECH_QUALITY_PLAN.md S7.1d)."""

from backend.models.generation import Generation
from backend.tests.test_seed import _post, auth, profile  # noqa: F401


def _row(db):
    db.expire_all()
    return db.query(Generation).filter(Generation.input_text == "Hello there.").one()


def test_a_request_without_a_seed_records_none(client, auth, profile, db_session):
    assert _post(client, auth, profile).status_code == 200
    row = _row(db_session)
    assert (row.seed, row.seed_applied) == (None, None)


def test_a_seed_that_reached_the_engine_is_recorded_as_applied(
    client, auth, profile, db_session
):
    assert _post(client, auth, profile, seed=9).status_code == 200
    row = _row(db_session)
    assert (row.seed, row.seed_applied) == (9, True)


def test_the_largest_seed_round_trips(client, auth, profile, db_session):
    _post(client, auth, profile, seed=2**31 - 1)
    assert _row(db_session).seed == 2**31 - 1


def test_a_seed_of_zero_is_recorded_not_mistaken_for_none(
    client, auth, profile, db_session
):
    _post(client, auth, profile, seed=0)
    row = _row(db_session)
    assert (row.seed, row.seed_applied) == (0, True)


def test_history_returns_the_seed_fields(client, auth, profile):
    _post(client, auth, profile, seed=5)
    items = client.get("/api/v1/synthesize/history", headers=auth).json()
    assert [(i["seed"], i["seed_applied"]) for i in items] == [(5, True)]


def test_a_seed_an_engine_could_not_apply_is_recorded_as_ignored(
    client, auth, profile, db_session, monkeypatch
):
    from backend.api import synthesize as api
    from backend.services.tts_pipeline import InferenceResult

    real = api.run_inference_pipeline

    async def unseeded(*args, **kwargs):
        r = await real(*args, **kwargs)
        return InferenceResult(r[0], r[1], "other", "1")

    monkeypatch.setattr(api, "run_inference_pipeline", unseeded)
    assert _post(client, auth, profile, seed=9).status_code == 200
    row = _row(db_session)
    assert (row.seed, row.seed_applied) == (9, False)
