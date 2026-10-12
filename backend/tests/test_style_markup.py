"""Inline emotion tags: ``[angry]...[/angry]`` (SPEECH_QUALITY_PLAN.md S5.4b)."""

import asyncio
import os
import uuid

import pytest
import soundfile as sf
from pydantic import ValidationError

from backend.core.config import settings
from backend.schemas.synthesize import SynthesizeRequest
from backend.services import style_markup, styled_synthesis, tts_pipeline
from backend.services.style_markup import MarkupError, Run, parse, strip
from backend.services.text_analysis import StyleOverride
from backend.tests.test_chatterbox_engine import EMB, TOKEN, _Server, _tone
from backend.tests.test_styled_synthesis import (_direct, _OriginalModel,
                                                 _Recorder, _voice)

# --- the parser -----------------------------------------------------------------


def test_untagged_text_is_one_run():
    assert parse("Just text.") == [Run("Just text.", None)]
    assert not style_markup.has_markup("Just text.")


def test_a_tag_splits_the_text_into_runs():
    assert parse("Calm. [angry]Get out![/angry] Then left.") == [
        Run("Calm. ", None),
        Run("Get out!", "angry"),
        Run(" Then left.", None),
    ]


def test_tags_are_case_insensitive_and_strip_removes_them():
    text = "a [SAD]b[/Sad] c"
    assert parse(text)[1] == Run("b", "sad")
    assert strip(text) == "a b c"


def test_blank_runs_are_dropped():
    assert parse("[happy]Yay![/happy]") == [Run("Yay!", "happy")]
    assert parse("[happy] [/happy]") == []


@pytest.mark.parametrize(
    "text",
    [
        "[sad]never closed",
        "never opened[/sad]",
        "[sad]a[/angry]",
        "[sad]a [angry]b[/angry] c[/sad]",
        "[sad][sad]x[/sad][/sad]",
    ],
)
def test_malformed_tags_are_an_error(text):
    with pytest.raises(MarkupError):
        parse(text)


def test_other_brackets_are_not_markup():
    assert parse("see [laugh] there") == [Run("see [laugh] there", None)]
    assert not style_markup.has_markup("[laugh]")


# --- the request ------------------------------------------------------------------

PROFILE = str(uuid.uuid4())


def test_a_tagged_text_is_a_valid_request():
    req = SynthesizeRequest(voice_profile_id=PROFILE, text="Hi [sad]there.[/sad]")
    assert req.text == "Hi [sad]there.[/sad]"


@pytest.mark.parametrize(
    "text", ["[sad]open", "x[/sad]", "[sad]a[/angry]", "[laugh] ha"]
)
def test_bad_tags_and_other_brackets_are_rejected(text):
    with pytest.raises(ValidationError):
        SynthesizeRequest(voice_profile_id=PROFILE, text=text)


def test_a_bad_character_inside_a_tag_is_still_rejected():
    with pytest.raises(ValidationError):
        SynthesizeRequest(
            voice_profile_id=PROFILE, text="[sad]no emoji \U0001f600[/sad]"
        )


# --- the plan and the join -----------------------------------------------------------


def test_a_tag_sets_the_style_of_its_own_text_only():
    planned = styled_synthesis.plan(
        "It is fine. [angry]Get out![/angry] It is fine.", _Recorder()
    )
    assert [p.segment.text for p in planned] == [
        "It is fine.",
        "Get out!",
        "It is fine.",
    ]
    assert [p.emotion for p in planned] == ["neutral", "angry", "neutral"]
    assert [p.requested for p in planned] == [False, True, False]
    assert planned[1].style.exaggeration > planned[0].style.exaggeration == 0.5


def test_a_tag_wins_over_the_request_level_emotion():
    planned = styled_synthesis.plan(
        "[sad]Oh no.[/sad] Fine.", _Recorder(), override=StyleOverride("happy", 1.0)
    )
    assert [p.emotion for p in planned] == ["sad", "happy"]
    assert all(p.requested for p in planned)


def test_a_tag_in_mid_sentence_joins_with_a_word_gap_not_a_full_stop_pause():
    planned = styled_synthesis.plan("I am [angry]so[/angry] tired.", _Recorder())
    assert [p.segment.text for p in planned] == ["I am", "so", "tired."]
    assert [p.segment.boundary.value for p in planned[:2]] == ["word", "word"]


def test_the_engine_never_sees_the_tags():
    engine = _Recorder()
    asyncio.run(
        styled_synthesis.synthesize_styled(
            engine, "Calm. [angry]Out![/angry]", _voice(), run_stage=_direct
        )
    )
    assert [c[0] for c in engine.calls] == ["Calm.", "Out!"]


def test_all_blank_tagged_text_is_sent_bare():
    engine = _Recorder()
    asyncio.run(
        styled_synthesis.synthesize_styled(
            engine, "[sad] [/sad]", _voice(), run_stage=_direct
        )
    )
    assert engine.calls[0][0] == " "


# --- the pipeline --------------------------------------------------------------------


def _pipeline(monkeypatch, tmp_path, enabled, text):
    model = _OriginalModel()
    model.output = _tone(1.0, rate=24000)
    server = _Server(model)
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", enabled)
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(6.0), 16000)
    try:
        result = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                text, EMB, "markup-user", reference_audio_path=str(ref)
            )
        )
    finally:
        server.stop()
    os.remove(result[0])
    return model, result


def test_the_pipeline_styles_a_tagged_sentence(monkeypatch, tmp_path):
    model, result = _pipeline(
        monkeypatch, tmp_path, True, "It is fine. [angry]Get out![/angry]"
    )
    assert [c[0] for c in model.calls] == ["It is fine.", "Get out!"]
    assert model.calls[0][1] == 0.5 and model.calls[1][1] > 0.5
    assert result.style_applied is True


def test_with_styling_off_the_tags_are_dropped_and_the_text_is_one_call(
    monkeypatch, tmp_path
):
    model, result = _pipeline(
        monkeypatch, tmp_path, False, "It is fine. [angry]Get out![/angry]"
    )
    assert [c[0] for c in model.calls] == ["It is fine. Get out!"]
    assert result.style_applied is False


def test_sv2tts_speaks_the_bare_text(monkeypatch):
    seen = []
    from backend.services import sv2tts_engine

    real = sv2tts_engine.Sv2ttsEngine.synthesize

    async def spy(self, text, *args, **kwargs):
        seen.append(text)
        return await real(self, text, *args, **kwargs)

    monkeypatch.setattr(sv2tts_engine.Sv2ttsEngine, "synthesize", spy)
    tts_pipeline.load_mock_models("cpu")
    import numpy as np

    result = asyncio.run(
        tts_pipeline.run_inference_pipeline(
            "Hello. [sad]Goodbye.[/sad]", np.ones(256, np.float32) / 16, "who"
        )
    )
    os.remove(result[0])
    assert seen == ["Hello. Goodbye."]


# --- the API ------------------------------------------------------------------------

from backend.models.generation import Generation  # noqa: E402
from backend.tests.test_style_override import (_post, auth,  # noqa: E402,F401
                                               profile)


def test_a_tagged_request_succeeds_says_ignored_on_sv2tts_and_records_it(
    client, auth, profile, db_session  # noqa: F811
):
    response = client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": "Fine. [sad]Goodbye.[/sad]"},
    )
    assert response.status_code == 200
    assert response.headers["X-Voice-Style"] == "ignored"
    db_session.expire_all()
    row = db_session.query(Generation).one()
    assert (row.emotion, row.style_applied) == (None, False)
    assert row.input_text == "Fine. [sad]Goodbye.[/sad]"


def test_an_untagged_request_has_no_style_header(client, auth, profile):  # noqa: F811
    assert "X-Voice-Style" not in _post(client, auth, profile).headers


def test_malformed_tags_are_a_422(client, auth, profile):  # noqa: F811
    response = client.post(
        "/api/v1/synthesize",
        headers=auth,
        json={"voice_profile_id": profile, "text": "[sad]never closed"},
    )
    assert response.status_code == 422
    assert "never closed" in response.text
