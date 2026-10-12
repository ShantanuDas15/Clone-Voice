"""A generation records the delivery that was asked for (SPEECH_QUALITY_PLAN.md S7.1b)."""

from backend.models.generation import Generation
from backend.tests.test_style_override import (_post, auth,  # noqa: F401
                                               profile)


def _row(db, text="Hello there."):
    db.expire_all()
    return db.query(Generation).filter(Generation.input_text == text).one()


def test_an_auto_request_records_no_style(client, auth, profile, db_session):
    assert _post(client, auth, profile).status_code == 200
    row = _row(db_session)
    assert (row.emotion, row.intensity, row.style_applied) == (None, None, None)


def test_a_requested_emotion_is_recorded_with_whether_it_was_applied(
    client, auth, profile, db_session
):
    assert _post(client, auth, profile, emotion="sad", intensity=0.4).status_code == 200
    row = _row(db_session)
    # SV2TTS has no delivery control, so the request was honoured only as "ignored".
    assert (row.emotion, row.intensity, row.style_applied) == ("sad", 0.4, False)


def test_an_emotion_without_intensity_records_none_for_it(
    client, auth, profile, db_session
):
    _post(client, auth, profile, emotion="angry")
    row = _row(db_session)
    assert (row.emotion, row.intensity) == ("angry", None)


def test_history_returns_the_style_fields(client, auth, profile):
    _post(client, auth, profile, emotion="happy", intensity=0.9)
    _post(client, auth, profile)
    items = client.get("/api/v1/synthesize/history", headers=auth).json()
    styled = [i for i in items if i["emotion"]]
    assert len(items) == 2 and len(styled) == 1
    assert (styled[0]["intensity"], styled[0]["style_applied"]) == (0.9, False)
    plain = next(i for i in items if not i["emotion"])
    assert (plain["intensity"], plain["style_applied"]) == (None, None)
