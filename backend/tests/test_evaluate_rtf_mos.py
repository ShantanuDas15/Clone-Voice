"""Real-time factor and predicted MOS in backend/evaluate_synthesis.py (SPEECH_QUALITY_PLAN.md S0.1e)."""

import numpy as np
import pytest
import soundfile as sf

from backend import evaluate_synthesis as es

SR = es.SAMPLE_RATE


@pytest.fixture(autouse=True)
def _clean_recorder():
    """Leave the module-level recorder as the next test finds it."""
    es.recorder.reset()
    es.recorder.predict_mos = None
    yield
    es.recorder.reset()
    es.recorder.predict_mos = None


def _audio(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SR), np.float32)


def test_rtf_is_compute_seconds_over_audio_seconds():
    es.recorder.record(_audio(2.0), 1.0)
    es.recorder.record(_audio(2.0), 3.0)
    assert es.recorder.summary()["rtf"] == pytest.approx(1.0)


def test_rtf_pools_time_so_a_long_clip_weighs_more():
    es.recorder.record(_audio(1.0), 1.0)  # rtf 1.0
    es.recorder.record(_audio(9.0), 9.0 * 0.2)  # rtf 0.2
    assert es.recorder.summary()["rtf"] == pytest.approx((1.0 + 1.8) / 10.0)


def test_nothing_recorded_gives_no_numbers():
    assert es.recorder.summary() == {"rtf": None, "mos": None}


def test_zero_length_audio_does_not_divide_by_zero():
    es.recorder.record(np.zeros(0, np.float32), 0.5)
    assert es.recorder.summary()["rtf"] is None


def test_reset_clears_the_previous_speaker():
    es.recorder.record(_audio(1.0), 2.0)
    es.recorder.reset()
    assert es.recorder.summary()["rtf"] is None


def test_mos_is_the_mean_of_the_predictor_over_clips():
    scores = iter([2.0, 4.0])
    es.recorder.predict_mos = lambda y: next(scores)
    es.recorder.record(_audio(1.0), 1.0)
    es.recorder.record(_audio(1.0), 1.0)
    assert es.recorder.summary()["mos"] == pytest.approx(3.0)


def test_mos_is_absent_without_a_predictor():
    es.recorder.record(_audio(1.0), 1.0)
    assert es.recorder.summary()["mos"] is None


def test_mos_skips_silent_or_empty_clips():
    called = []
    es.recorder.predict_mos = lambda y: called.append(1) or 3.0
    es.recorder.record(np.zeros(0, np.float32), 0.1)
    assert called == []
    assert es.recorder.summary()["mos"] is None


def test_synthesize_records_its_own_timing(tmp_path, monkeypatch):
    out = tmp_path / "out.wav"
    sf.write(out, _audio(0.5), SR)

    async def fake_pipeline(text, embedding, user_id):
        return str(out), 0.5

    monkeypatch.setattr(
        "backend.services.tts_pipeline.run_inference_pipeline", fake_pipeline
    )
    es._synthesize("Hello.", np.zeros(256, np.float32), "spk", 1)
    summary = es.recorder.summary()
    assert summary["rtf"] is not None and summary["rtf"] >= 0.0
    assert es.recorder.audio_seconds == pytest.approx(0.5)


# --- UTMOS without torchaudio -------------------------------------------------


def test_the_resample_stub_passes_16k_audio_through_and_refuses_other_rates(
    monkeypatch,
):
    import importlib.util
    import sys

    from backend import score_engine_outputs as sc

    monkeypatch.delitem(sys.modules, "torchaudio", raising=False)
    monkeypatch.delitem(sys.modules, "torchaudio.functional", raising=False)
    sc._install_resample_stub()
    assert importlib.util.find_spec("torchaudio") is not None  # torch.hub checks this
    wave = object()
    assert sys.modules["torchaudio"].functional.resample(wave, 16000, 16000) is wave
    with pytest.raises(ValueError):
        sys.modules["torchaudio"].functional.resample(wave, 22050, 16000)
