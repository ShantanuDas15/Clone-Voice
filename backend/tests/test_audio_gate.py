"""The output quality gate and its retry loop (SPEECH_QUALITY_PLAN.md S3.4)."""

import asyncio
import io
import os
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core import metrics
from backend.core.config import Settings, settings
from backend.models.generation import Generation
from backend.services import tts_pipeline
from backend.services.audio_gate import (MAX_CLIPPING_RATIO, _longest_run,
                                         check_output, count_spoken_words,
                                         measure_output)
from backend.services.tts_pipeline import OutputQualityError

SR = 16000
TEXT = "Hello there my friend today."  # 5 words: expected about 1.7 s


def _voiced(seconds: float, amp: float = 0.2) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


def _gate(wav, text=TEXT, truncated=0, max_pause=0.7):
    return check_output(wav, SR, text, truncated, max_pause)


# --- the checks -------------------------------------------------------------


def test_plausible_speech_passes():
    result = _gate(_voiced(1.8))
    assert result.passed and result.reasons == ()
    assert result.measures.duration_ratio == pytest.approx(1.8 / 1.725, abs=0.01)


def test_empty_and_nonfinite_are_refused_with_no_measures():
    assert _gate(np.array([], dtype=np.float32)).reasons == ("empty",)
    bad = _voiced(1.8)
    bad[5] = np.nan
    assert _gate(bad).reasons == ("non_finite",)
    assert _gate(np.zeros((2, 100), dtype=np.float32)).reasons == ("empty",)


def test_a_truncated_decode_fails_whatever_the_audio_sounds_like():
    result = _gate(_voiced(1.8), truncated=1)
    assert not result.passed and "truncated" in result.reasons


def test_near_silence_fails_as_silent():
    assert "silent" in _gate(_voiced(1.8, amp=0.0005)).reasons
    assert "silent" in _gate(np.zeros(SR * 2, dtype=np.float32)).reasons


def test_a_quiet_voice_is_not_silent():
    # -34 dBFS: quieter than the loudest ordinary output but well above the floor.
    assert _gate(_voiced(1.8, amp=0.03)).passed


def test_mostly_silence_fails():
    # 0.1 s of tone, 0.9 s of silence, repeated: 90% silent, no single long gap.
    block = np.concatenate([_voiced(0.1), np.zeros(int(0.9 * SR), dtype=np.float32)])
    result = _gate(np.tile(block, 2))
    assert "mostly_silent" in result.reasons
    assert "long_silence" not in result.reasons


def test_a_gap_longer_than_any_configured_pause_fails():
    wav = np.concatenate(
        [_voiced(0.5), np.zeros(int(2.0 * SR), np.float32), _voiced(0.5)]
    )
    assert "long_silence" in _gate(wav, max_pause=0.7).reasons
    # The same gap is allowed when a pause that long is configured.
    assert "long_silence" not in _gate(wav, max_pause=1.5).reasons


def test_a_normal_typed_pause_is_not_a_failure():
    wav = np.concatenate(
        [_voiced(0.9), np.zeros(int(0.7 * SR), np.float32), _voiced(0.9)]
    )
    assert "long_silence" not in _gate(wav).reasons


def test_heavy_clipping_fails_light_clipping_does_not():
    heavy = _voiced(1.8)
    heavy[: int(0.05 * len(heavy))] = 1.0
    assert "clipping" in _gate(heavy).reasons
    light = _voiced(1.8)
    light[: int(0.005 * len(light))] = 1.0
    assert "clipping" not in _gate(light).reasons
    assert 0.005 < MAX_CLIPPING_RATIO


def test_implausible_duration_fails_for_text_long_enough_to_judge():
    assert "duration_too_long" in _gate(_voiced(8.0)).reasons
    assert "duration_too_short" in _gate(_voiced(0.3)).reasons


def test_single_words_and_short_phrases_are_exempt_from_the_duration_check():
    # Odd long words legitimately take seconds (measured: a 60-letter word, 3.0 s).
    assert _gate(_voiced(3.0), text="Supercalifragilistic").passed
    assert _gate(_voiced(2.0), text="Why not now").passed
    assert (
        _gate(_voiced(3.0), text="Supercalifragilistic").measures.duration_ratio is None
    )


def test_every_failing_reason_is_reported():
    wav = _voiced(8.0, amp=0.0005)
    assert set(_gate(wav, truncated=2).reasons) >= {
        "truncated",
        "silent",
        "duration_too_long",
    }


def test_count_spoken_words():
    assert count_spoken_words("at ten thirty, pee em!") == 5
    assert count_spoken_words("don't stop") == 2
    assert count_spoken_words("?!...") == 0


def test_longest_run():
    assert _longest_run(np.array([], dtype=bool)) == 0
    assert _longest_run(np.array([False, False])) == 0
    assert _longest_run(np.array([True, False, True, True, True, False])) == 3
    assert _longest_run(np.array([True, True])) == 2


def test_audio_shorter_than_one_frame_is_measured_not_crashed():
    m = measure_output(np.array([0.1] * 10, dtype=np.float32), SR, 1)
    assert m.silence_ratio == 1.0


# --- settings ---------------------------------------------------------------


def test_defaults_and_bounds():
    assert Settings().TTS_QUALITY_GATE_ENABLED is True
    assert Settings().TTS_QUALITY_MAX_ATTEMPTS == 2
    for bad in (0, 6):
        with pytest.raises(Exception):
            Settings(TTS_QUALITY_MAX_ATTEMPTS=bad)


# --- the pipeline's retry loop ----------------------------------------------


@pytest.fixture
def gate_on(monkeypatch):
    """Turn the gate on (the suite turns it off for the silent mock vocoder)."""
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", True)
    tts_pipeline.load_mock_models("cpu")


def _count(result: str) -> float:
    return metrics.QUALITY_GATE_RESULTS.labels(result)._value.get()


def _run(text=TEXT, user="gate-user"):
    return asyncio.run(
        tts_pipeline.run_inference_pipeline(text, np.ones(256, np.float32), user)
    )


def _outputs() -> list:
    return [p for p in Path(settings.OUTPUT_DIR).rglob("*") if p.is_file()]


def _vocode_returning(*waveforms):
    calls = iter(waveforms)
    seen = []

    def fake(mel):
        seen.append(1)
        return next(calls)

    return fake, seen


def test_a_good_first_attempt_is_returned_after_one_synthesis(gate_on):
    fake, seen = _vocode_returning(_voiced(1.8))
    before = _count("passed")
    with patch.object(tts_pipeline, "vocode", fake):
        path, _ = _run()
    assert len(seen) == 1 and os.path.exists(path)
    assert _count("passed") == before + 1


def test_a_bad_attempt_is_retried_and_the_good_one_is_served(gate_on):
    fake, seen = _vocode_returning(np.zeros(SR * 2, np.float32), _voiced(1.8))
    retried = _count("retried")
    with patch.object(tts_pipeline, "vocode", fake):
        path, duration = _run()
    assert len(seen) == 2
    assert duration == pytest.approx(1.8, abs=0.01)
    assert _count("retried") == retried + 1
    assert len(_outputs()) == 1


def test_when_every_attempt_fails_it_refuses_and_stores_nothing(gate_on):
    fake, seen = _vocode_returning(np.zeros(SR * 2, np.float32), _voiced(8.0, 0.0005))
    refused = _count("refused")
    with patch.object(tts_pipeline, "vocode", fake), pytest.raises(
        OutputQualityError
    ) as e:
        _run()
    assert len(seen) == 2  # bounded: TTS_QUALITY_MAX_ATTEMPTS
    assert "silent" in e.value.reasons
    assert _count("refused") == refused + 1
    assert _outputs() == []


def test_the_attempt_limit_is_a_setting(gate_on, monkeypatch):
    monkeypatch.setattr(settings, "TTS_QUALITY_MAX_ATTEMPTS", 1)
    fake, seen = _vocode_returning(np.zeros(SR * 2, np.float32))
    with patch.object(tts_pipeline, "vocode", fake), pytest.raises(OutputQualityError):
        _run()
    assert len(seen) == 1


def test_switched_off_the_gate_serves_whatever_the_vocoder_returned(
    gate_on, monkeypatch
):
    monkeypatch.setattr(settings, "TTS_QUALITY_GATE_ENABLED", False)
    fake, seen = _vocode_returning(np.zeros(SR * 2, np.float32))
    with patch.object(tts_pipeline, "vocode", fake):
        path, _ = _run()
    assert len(seen) == 1 and os.path.exists(path)


def test_failure_reasons_are_counted(gate_on):
    counter = metrics.QUALITY_GATE_FAILURES.labels("silent")._value
    before = counter.get()
    fake, _ = _vocode_returning(np.zeros(SR * 2, np.float32), _voiced(1.8))
    with patch.object(tts_pipeline, "vocode", fake):
        _run()
    assert counter.get() == before + 1


def test_a_decode_that_hits_the_frame_cap_is_counted_and_fails_the_gate(
    gate_on, monkeypatch
):
    monkeypatch.setattr(tts_pipeline.synth_hparams, "max_mel_frames", 8)
    mel, truncated = tts_pipeline._synthesize_counting_truncation(
        "A sentence long enough to pass the cap.", np.ones(256, np.float32)
    )
    assert truncated >= 1
    # The count belongs to one call: the next call starts again from zero.
    monkeypatch.setattr(tts_pipeline.synth_hparams, "max_mel_frames", 900)
    assert (
        tts_pipeline._synthesize_counting_truncation("Hi.", np.ones(256, np.float32))[1]
        == 0
    )


def test_a_truncated_synthesis_is_refused_even_if_the_audio_looks_fine(
    gate_on, monkeypatch
):
    monkeypatch.setattr(tts_pipeline.synth_hparams, "max_mel_frames", 8)
    monkeypatch.setattr(settings, "TTS_QUALITY_MAX_ATTEMPTS", 1)
    fake, _ = _vocode_returning(_voiced(1.8))
    with patch.object(tts_pipeline, "vocode", fake), pytest.raises(
        OutputQualityError
    ) as e:
        _run("A sentence long enough to pass the cap.")
    assert e.value.reasons == ("truncated",)


# --- the API ----------------------------------------------------------------


@pytest.fixture
def auth_headers(client: TestClient):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "gate@example.com", "password": "Password123!", "name": "G"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "gate@example.com", "password": "Password123!"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _wav_bytes() -> bytes:
    samples = (_voiced(3.0, 0.5) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(samples.tobytes())
    return buf.getvalue()


def test_a_refused_synthesis_is_a_502_with_a_failed_audit_row(
    client, auth_headers, db_session
):
    profile = client.post(
        "/api/v1/voice/upload",
        headers=auth_headers,
        data={"name": "G", "consent_confirmed": "true"},
        files={"file": ("a.wav", _wav_bytes(), "audio/wav")},
    ).json()["id"]
    with patch(
        "backend.api.synthesize.run_inference_pipeline",
        side_effect=OutputQualityError(("truncated",)),
    ):
        res = client.post(
            "/api/v1/synthesize",
            headers=auth_headers,
            json={"voice_profile_id": profile, "text": "Gate refusal"},
        )
    assert res.status_code == 502
    assert "quality" in res.json()["detail"]
    rows = (
        db_session.query(Generation)
        .filter(Generation.input_text == "Gate refusal")
        .all()
    )
    assert [r.status for r in rows] == ["failed"]


# --- retry after truncation uses smaller chunks (S3.4b) --------------------------


def _recording_synth(truncate_when):
    """A stand-in for ``synthesize_speech`` that records ``max_chars`` per call."""
    calls = []

    def fake(text, embedding, max_chars=None):
        calls.append(max_chars)
        tts_pipeline._decode_state.truncated = 1 if truncate_when(max_chars) else 0
        return np.zeros((80, 50), np.float32)

    return fake, calls


def test_a_truncated_attempt_is_retried_in_smaller_chunks_and_recovers(gate_on):
    synth, calls = _recording_synth(lambda max_chars: max_chars is None)
    vocode, _ = _vocode_returning(_voiced(1.8), _voiced(1.8))
    with patch.object(tts_pipeline, "synthesize_speech", synth), patch.object(
        tts_pipeline, "vocode", vocode
    ):
        path, _ = _run()
    assert calls == [None, settings.TTS_CHUNK_MAX_CHARS // 2]
    assert os.path.exists(path)


def test_a_failure_other_than_truncation_retries_with_the_same_chunking(gate_on):
    synth, calls = _recording_synth(lambda max_chars: False)
    vocode, _ = _vocode_returning(np.zeros(SR * 2, np.float32), _voiced(1.8))
    with patch.object(tts_pipeline, "synthesize_speech", synth), patch.object(
        tts_pipeline, "vocode", vocode
    ):
        _run()
    assert calls == [None, None]


def test_chunks_keep_halving_down_to_a_floor(gate_on, monkeypatch):
    monkeypatch.setattr(settings, "TTS_QUALITY_MAX_ATTEMPTS", 5)
    synth, calls = _recording_synth(lambda max_chars: True)
    vocode, _ = _vocode_returning(*[_voiced(1.8)] * 5)
    with patch.object(tts_pipeline, "synthesize_speech", synth), patch.object(
        tts_pipeline, "vocode", vocode
    ), pytest.raises(OutputQualityError):
        _run()
    assert calls == [None, 75, 37, 20, 20]


def test_a_smaller_chunk_limit_decodes_more_chunks(gate_on):
    text = "The committee reviewed the proposal carefully, and decided to postpone the vote."
    decodes = []
    real = tts_pipeline._synthesize_chunk

    def spy(chunk, embedding):
        decodes.append(chunk)
        return real(chunk, embedding)

    with patch.object(tts_pipeline, "_synthesize_chunk", spy):
        tts_pipeline.synthesize_speech(text, np.ones(256, np.float32))
        default_count = len(decodes)
        decodes.clear()
        tts_pipeline.synthesize_speech(text, np.ones(256, np.float32), 30)
    assert default_count == 1 and len(decodes) > 1
    assert all(len(d) <= 30 for d in decodes)
