"""Tests for output levelling and cleanup (SPEECH_QUALITY_PLAN.md S3.3)."""

import asyncio
import os
import shutil

import numpy as np
import pytest
import soundfile as sf
from pydantic import ValidationError

from backend.core.config import Settings, settings
from backend.services import tts_pipeline
from backend.services.audio_polish import (
    MAX_GAIN_DB,
    apply_edge_fades,
    integrated_loudness,
    polish_waveform,
    true_peak,
)

SR = 16000


def _sine(freq: float, amp: float, seconds: float = 3.0) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# --- integrated_loudness ---------------------------------------------------------


def test_full_scale_1khz_sine_is_about_minus_3_lufs():
    """BS.1770 calibration: a full-scale 1 kHz sine measures about -3.0 LUFS."""
    assert integrated_loudness(_sine(1000, 1.0), SR) == pytest.approx(-3.0, abs=0.3)


def test_loudness_moves_one_for_one_with_gain():
    """Halving the amplitude lowers the loudness by 6.02 LU."""
    loud = integrated_loudness(_sine(500, 0.5), SR)
    quiet = integrated_loudness(_sine(500, 0.25), SR)
    assert loud - quiet == pytest.approx(6.02, abs=0.01)


def test_loudness_of_silence_is_none():
    """Digital silence is under the absolute gate: there is no level."""
    assert integrated_loudness(np.zeros(SR, dtype=np.float32), SR) is None


def test_loudness_of_empty_or_nonfinite_is_none():
    """Empty and NaN input yield no measurement rather than a crash."""
    assert integrated_loudness(np.array([], dtype=np.float32), SR) is None
    bad = _sine(500, 0.5)
    bad[10] = np.nan
    assert integrated_loudness(bad, SR) is None


def test_loudness_rejects_non_mono():
    """A 2-D array is a caller bug, not audio."""
    with pytest.raises(ValueError):
        integrated_loudness(np.zeros((2, SR), dtype=np.float32), SR)


def test_audio_shorter_than_one_block_is_still_measured():
    """A 100 ms clip (under the 400 ms block) gets a reading."""
    assert integrated_loudness(_sine(500, 0.5, 0.1), SR) is not None


def test_relative_gate_ignores_a_long_quiet_tail():
    """Speech followed by much quieter room tone measures as the speech, not the average."""
    speech = _sine(500, 0.3, 2.0)
    tail = _sine(500, 0.3 * 10 ** (-30 / 20), 6.0)  # 30 dB lower
    assert integrated_loudness(np.concatenate([speech, tail]), SR) == pytest.approx(
        integrated_loudness(speech, SR), abs=0.5
    )


# --- true_peak / fades -----------------------------------------------------------


def test_true_peak_is_at_least_the_sample_peak():
    """Oversampling can only find a peak at or above the sample peak."""
    wav = _sine(7300, 0.8)  # few samples per cycle: sample peaks undershoot
    assert true_peak(wav) >= float(np.max(np.abs(wav))) - 1e-6
    assert true_peak(np.array([], dtype=np.float32)) == 0.0


def test_fades_start_and_end_at_zero_and_leave_the_middle():
    """The first and last samples are silent; the centre is untouched."""
    wav = np.ones(SR, dtype=np.float32)
    out = apply_edge_fades(wav, SR)
    assert out[0] == 0.0 and out[-1] == 0.0
    assert np.array_equal(out[400:-400], wav[400:-400])
    assert wav[0] == 1.0  # the input is not modified


def test_fades_skip_audio_too_short_to_fade():
    """One or two samples are returned as they are."""
    wav = np.ones(2, dtype=np.float32)
    assert np.array_equal(apply_edge_fades(wav, SR), wav)


# --- polish_waveform -------------------------------------------------------------


@pytest.mark.parametrize("amp", [0.02, 0.05, 0.3])
def test_polish_hits_the_target_loudness(amp):
    """Quiet and loud inputs both land on the target (the sine is under the ceiling)."""
    out, report = polish_waveform(_sine(500, amp), SR, -18.0, -1.0)
    assert integrated_loudness(out, SR) == pytest.approx(-18.0, abs=0.1)
    assert report.output_lufs == pytest.approx(-18.0, abs=0.1)
    assert not report.peak_limited
    assert out.dtype == np.float32


def test_polish_never_exceeds_the_peak_ceiling():
    """A peaky signal stops at the ceiling and is flagged, never clipped."""
    wav = _sine(500, 0.02)
    wav[SR] = 0.5  # one loud click: low loudness, high peak
    out, report = polish_waveform(wav, SR, -18.0, -1.0)
    assert report.peak_limited
    assert true_peak(out) <= 10 ** (-1.0 / 20) + 1e-3
    assert report.output_lufs < -18.0


def test_polish_caps_the_boost():
    """A near-silent but audible input is not amplified past MAX_GAIN_DB."""
    out, report = polish_waveform(_sine(500, 0.003), SR, -18.0, -1.0)
    assert report.gain_db == pytest.approx(MAX_GAIN_DB)
    assert report.output_lufs < -18.0


def test_polish_removes_dc_offset():
    """A constant offset is gone from the output."""
    out, _ = polish_waveform(_sine(500, 0.1) + 0.2, SR, -18.0, -1.0)
    assert abs(float(out.mean())) < 1e-3


def test_polish_fades_the_edges():
    """The output starts and ends at zero even if the input did not."""
    out, _ = polish_waveform(_sine(500, 0.1) + 0.0, SR, -18.0, -1.0)
    assert out[0] == 0.0 and out[-1] == 0.0


def test_polish_leaves_silence_alone():
    """Silence has no level to match, so no gain is applied."""
    out, report = polish_waveform(np.zeros(SR, dtype=np.float32), SR, -18.0, -1.0)
    assert not out.any()
    assert report.input_lufs is None and report.gain_db == 0.0


@pytest.mark.parametrize(
    "bad",
    [np.array([], dtype=np.float32), np.array([0.1, np.nan], dtype=np.float32)],
)
def test_polish_rejects_empty_and_nonfinite(bad):
    """A vocoder fault is an error, not stored audio."""
    with pytest.raises(ValueError):
        polish_waveform(bad, SR, -18.0, -1.0)


def test_polish_rejects_non_mono():
    """A 2-D array is a caller bug."""
    with pytest.raises(ValueError):
        polish_waveform(np.zeros((2, SR), dtype=np.float32), SR, -18.0, -1.0)


def test_polish_one_sample():
    """A single sample does not crash (it has no level, so it passes through)."""
    out, _ = polish_waveform(np.array([0.5], dtype=np.float32), SR, -18.0, -1.0)
    assert out.shape == (1,)


# --- settings --------------------------------------------------------------------


def test_defaults_match_the_plan():
    """The plan names -18 LUFS and a -1 dBTP ceiling."""
    assert settings.OUTPUT_NORMALIZE_ENABLED is True
    assert settings.OUTPUT_TARGET_LUFS == -18.0
    assert settings.OUTPUT_PEAK_CEILING_DBFS == -1.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("OUTPUT_TARGET_LUFS", 0.0),
        ("OUTPUT_TARGET_LUFS", -70.0),
        ("OUTPUT_PEAK_CEILING_DBFS", 3.0),
        ("OUTPUT_PEAK_CEILING_DBFS", -30.0),
    ],
)
def test_out_of_range_settings_are_refused(field, value):
    """A target that cannot be reached safely fails at startup, not per request."""
    with pytest.raises(ValidationError):
        Settings(**{field: value})


# --- pipeline wiring -------------------------------------------------------------


@pytest.fixture
def out_user():
    """A scratch output user directory, removed afterwards."""
    user = "polish-test-user"
    yield user
    shutil.rmtree(os.path.join(settings.OUTPUT_DIR, user), ignore_errors=True)


def _read(path: str) -> np.ndarray:
    data, _ = sf.read(path, dtype="float32")
    return data


def test_finish_and_save_levels_the_file(out_user):
    """The stored WAV is at the target level, not the raw input level."""
    path, duration = tts_pipeline.finish_and_save(_sine(500, 0.02), SR, out_user)
    assert integrated_loudness(_read(path), SR) == pytest.approx(-18.0, abs=0.2)
    assert duration == pytest.approx(3.0, abs=0.01)


def test_finish_and_save_can_be_switched_off(out_user, monkeypatch):
    """With the flag off the raw waveform is stored (to 16-bit precision)."""
    monkeypatch.setattr(settings, "OUTPUT_NORMALIZE_ENABLED", False)
    wav = _sine(500, 0.02)
    path, _ = tts_pipeline.finish_and_save(wav, SR, out_user)
    assert np.max(np.abs(_read(path) - wav)) < 1e-4


def test_pipeline_output_is_leveled(out_user):
    """run_inference_pipeline (mock models) stores a leveled, finite WAV."""
    tts_pipeline.load_mock_models("cpu")
    path, duration = asyncio.run(
        tts_pipeline.run_inference_pipeline(
            "Hello there.", np.random.rand(256).astype(np.float32), out_user
        )
    )
    data = _read(path)
    assert duration > 0 and np.all(np.isfinite(data))
    assert np.max(np.abs(data)) <= 1.0
