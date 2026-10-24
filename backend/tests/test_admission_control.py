"""Texts too long for this CPU are refused up front (SPEECH_QUALITY_PLAN.md S3.5f)."""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings, settings
from backend.services import tts_pipeline as tp
from backend.tests.test_synthesize import (
    auth_headers_syn,  # noqa: F401
    setup_models_for_synthesize,
    upload_profile,
)

SHORT = "The meeting starts at nine and ends at ten."
LONG = " ".join(["The meeting starts at nine and ends at ten."] * 10)  # 90 words


def test_nothing_is_refused_before_the_machine_has_been_timed(monkeypatch):
    monkeypatch.setattr(tp, "_vocoder_cost", None)
    tp.check_text_fits(LONG)


def test_a_short_text_fits_and_a_long_one_does_not_on_a_slow_machine(monkeypatch):
    monkeypatch.setattr(tp, "_vocoder_cost", (7.0, 1.1))
    tp.check_text_fits(SHORT)
    with pytest.raises(tp.TextTooLongError) as raised:
        tp.check_text_fits(LONG)
    # budget 30 s x 0.8 = 24 s; minus 7 s fixed = 17 s at 1.1 s per second = 15.5 s of audio
    # = about 47 words
    assert 44 <= raised.value.max_words <= 50


def test_the_same_long_text_fits_on_a_fast_machine(monkeypatch):
    monkeypatch.setattr(tp, "_vocoder_cost", (3.0, 0.6))
    tp.check_text_fits(LONG)


def test_the_check_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(tp, "_vocoder_cost", (50.0, 50.0))
    monkeypatch.setattr(settings, "TTS_ADMISSION_CONTROL", False)
    tp.check_text_fits(LONG)


def test_pauses_between_chunks_count_towards_the_audio_length():
    sentence = (
        " ".join(["alpha"] * 16) + "."
    )  # about 96 characters: two make two chunks
    text = sentence + " " + sentence
    speech_only = max(0.3, -0.50 + 0.339 * 32)
    assert tp.estimated_audio_seconds(text) == pytest.approx(
        speech_only + settings.TTS_PAUSE_SECONDS["statement"], abs=0.01
    )
    assert tp.estimated_audio_seconds(sentence) == pytest.approx(
        max(0.3, -0.50 + 0.339 * 16), abs=0.01
    )


def test_calibration_fits_a_fixed_and_a_per_second_cost(monkeypatch):
    monkeypatch.setattr(tp, "synthesize_speech", lambda *a, **k: np.zeros((80, 70)))
    clock = {"now": 0.0}
    monkeypatch.setattr(tp.time, "perf_counter", lambda: clock["now"])

    def fake_vocode(mel):
        seconds = mel.shape[1] * 0.0125
        clock["now"] += (
            4.0 + 1.5 * seconds
        )  # a machine with 4 s fixed and 1.5 s per second
        return np.zeros(int(seconds * 16000), dtype=np.float32)

    monkeypatch.setattr(tp, "vocode", fake_vocode)
    tp._calibrate_vocoder_speed()
    fixed, per_second = tp._vocoder_cost
    assert fixed == pytest.approx(4.0, abs=0.05)
    assert per_second == pytest.approx(1.5, abs=0.02)


def test_calibration_falls_back_to_a_proportional_cost_when_timing_is_noisy(
    monkeypatch,
):
    monkeypatch.setattr(tp, "synthesize_speech", lambda *a, **k: np.zeros((80, 70)))
    times = iter(
        [0.0, 5.0, 5.0, 5.0 + 4.0]
    )  # the longer mel "ran faster": a noisy clock
    monkeypatch.setattr(tp.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(
        tp, "vocode", lambda mel: np.zeros(int(mel.shape[1] * 200), dtype=np.float32)
    )
    tp._calibrate_vocoder_speed()
    fixed, per_second = tp._vocoder_cost
    assert fixed == 0.0 and per_second > 0


def test_calibration_does_nothing_when_the_check_is_off(monkeypatch):
    monkeypatch.setattr(settings, "TTS_ADMISSION_CONTROL", False)
    tp._calibrate_vocoder_speed()
    assert tp._vocoder_cost is None


def test_the_settings_default_on_with_a_margin_below_one():
    assert Settings.model_fields["TTS_ADMISSION_CONTROL"].default is True
    assert Settings.model_fields["TTS_ADMISSION_MARGIN"].default == 0.8


def test_the_endpoint_refuses_a_too_long_text_with_a_clear_422(
    client: TestClient, auth_headers_syn, monkeypatch  # noqa: F811
):
    profile_id = upload_profile(client, auth_headers_syn)
    monkeypatch.setattr(tp, "_vocoder_cost", (7.0, 1.1))
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": LONG[:500]},
    )
    assert res.status_code == 422
    assert "words or fewer" in res.json()["detail"]
    assert (
        client.get("/api/v1/synthesize/history", headers=auth_headers_syn).json() == []
    )


def test_the_endpoint_still_serves_a_short_text_on_a_slow_machine(
    client: TestClient, auth_headers_syn, monkeypatch  # noqa: F811
):
    profile_id = upload_profile(client, auth_headers_syn)
    monkeypatch.setattr(tp, "_vocoder_cost", (7.0, 1.1))
    res = client.post(
        "/api/v1/synthesize",
        headers=auth_headers_syn,
        json={"voice_profile_id": profile_id, "text": SHORT},
    )
    assert res.status_code == 200


def test_warmup_measures_the_machine_and_a_calibration_failure_does_not_fail_it(
    monkeypatch,
):
    import asyncio

    calls = []
    monkeypatch.setattr(tp, "_warmup_forward_pass", lambda: None)
    monkeypatch.setattr(tp, "_calibrate_vocoder_speed", lambda: calls.append("timed"))
    monkeypatch.setattr(tp, "_warmup_status", "pending")
    assert asyncio.run(tp.warmup_inference()) is True
    assert calls == ["timed"]

    def broken():
        raise RuntimeError("no timing today")

    monkeypatch.setattr(tp, "_calibrate_vocoder_speed", broken)
    assert asyncio.run(tp.warmup_inference()) is True
    assert tp.get_warmup_status() == "ok"
