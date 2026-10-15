"""A request is told which sound tags the speaking engine could not make (SPEECH_QUALITY_PLAN.md S6.2c)."""

import pytest

from backend.api import synthesize as api
from backend.services import style_markup
from backend.services.tts_pipeline import InferenceResult
from backend.tests.test_seed import auth, profile  # noqa: F401


@pytest.mark.parametrize(
    "text, supported, expected",
    [
        ("Hello there.", (), ()),
        ("Ha [laugh] ok.", (), ("laugh",)),
        ("Ha [laugh] ok.", ("laugh",), ()),
        ("[LAUGH] a [Cough] b [laugh]", (), ("laugh", "cough")),
        ("[laugh] [cough] x", ("laugh",), ("cough",)),
        ("[sad]Hi.[/sad]", (), ()),
        ("[giggle] is not a tag", (), ()),
    ],
)
def test_dropped_nonverbal(text, supported, expected):
    assert style_markup.dropped_nonverbal(text, supported) == expected


def _post(client, auth, profile, text):
    return client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": text},
    )


def test_an_engine_without_sound_tags_reports_each_one_dropped(client, auth, profile):
    response = _post(client, auth, profile, "Ha [laugh] ok [cough] and [LAUGH] done.")
    assert response.status_code == 200
    assert response.headers["X-Voice-Tags-Dropped"] == "laugh,cough"


def test_text_without_sound_tags_sends_no_header(client, auth, profile):
    response = _post(client, auth, profile, "Hello there.")
    assert "X-Voice-Tags-Dropped" not in response.headers


def test_an_engine_that_makes_the_sound_reports_nothing(
    client, auth, profile, monkeypatch
):
    real = api.run_inference_pipeline

    async def spoken(*args, **kwargs):
        r = await real(*args, **kwargs)
        return InferenceResult(r[0], r[1], "turbo", "1", sound_tags_dropped=())

    monkeypatch.setattr(api, "run_inference_pipeline", spoken)
    response = _post(client, auth, profile, "Ha [laugh] ok.")
    assert "X-Voice-Tags-Dropped" not in response.headers


def test_the_header_is_exposed_to_browsers():
    from backend.main import app

    cors = next(m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware")
    assert "X-Voice-Tags-Dropped" in cors.kwargs["expose_headers"]
