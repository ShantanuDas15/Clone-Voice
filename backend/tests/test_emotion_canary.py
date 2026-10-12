"""A share of users gets sentence-by-sentence styling (SPEECH_QUALITY_PLAN.md S7.4b)."""

import asyncio
import os
import uuid

import pytest
import soundfile as sf

from backend.core.config import Settings, settings
from backend.services import styled_synthesis, tts_pipeline
from backend.services.tts_engine import canary_bucket
from backend.tests.test_chatterbox_engine import EMB, TOKEN, _Server, _tone
from backend.tests.test_styled_synthesis import _OriginalModel

USERS = [str(uuid.UUID(int=i * 7919)) for i in range(1, 400)]


@pytest.fixture(autouse=True)
def _off(monkeypatch):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", False)
    monkeypatch.setattr(settings, "EMOTION_CONTROL_PERCENT", 0)


def _share(percent, monkeypatch):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_PERCENT", percent)
    return [u for u in USERS if styled_synthesis.enabled_for(u)]


def test_it_is_off_by_default():
    assert Settings.model_fields["EMOTION_CONTROL_PERCENT"].default == 0
    assert not any(styled_synthesis.enabled_for(u) for u in USERS)


def test_the_global_flag_serves_everyone(monkeypatch):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_ENABLED", True)
    assert all(styled_synthesis.enabled_for(u) for u in USERS)


def test_a_percentage_serves_about_that_share(monkeypatch):
    share = len(_share(25, monkeypatch)) / len(USERS)
    assert 0.18 < share < 0.32
    assert len(_share(100, monkeypatch)) == len(USERS)


def test_raising_the_percentage_only_adds_users(monkeypatch):
    small = set(_share(10, monkeypatch))
    large = set(_share(40, monkeypatch))
    assert small < large


def test_a_user_never_flips_between_calls(monkeypatch):
    first = _share(30, monkeypatch)
    assert first == _share(30, monkeypatch)


def test_it_selects_different_users_than_the_engine_canary(monkeypatch):
    styled = set(_share(30, monkeypatch))
    engine = {u for u in USERS if canary_bucket(u) < 30}
    assert styled != engine and styled & engine and styled - engine


def test_the_engine_canary_bucket_is_unchanged_without_a_salt():
    assert canary_bucket("abc") == canary_bucket("abc", "")
    assert canary_bucket("abc") != canary_bucket("abc", "x:")


def _calls(monkeypatch, tmp_path, user_id):
    model = _OriginalModel()
    model.output = _tone(1.0, rate=24000)
    server = _Server(model)
    monkeypatch.setattr(settings, "TTS_ENGINE", "chatterbox")
    monkeypatch.setattr(settings, "TTS_WORKER_URL", server.url)
    monkeypatch.setattr(settings, "TTS_WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), _tone(6.0), 16000)
    try:
        result = asyncio.run(
            tts_pipeline.run_inference_pipeline(
                "It is fine. I hate this!!",
                EMB,
                user_id,
                reference_audio_path=str(ref),
            )
        )
    finally:
        server.stop()
    os.remove(result[0])
    return model.calls


def test_the_pipeline_styles_only_users_in_the_canary(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EMOTION_CONTROL_PERCENT", 50)
    inside = next(u for u in USERS if styled_synthesis.enabled_for(u))
    outside = next(u for u in USERS if not styled_synthesis.enabled_for(u))
    assert len(_calls(monkeypatch, tmp_path, inside)) == 2
    assert len(_calls(monkeypatch, tmp_path, outside)) == 1
