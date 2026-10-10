"""Recording-quality measures on signals whose answers are known (SPEECH_QUALITY_PLAN.md S2.2)."""

import numpy as np
import pytest

from backend.services import audio_quality as aq

SR = aq.SAMPLE_RATE


def speechlike(seconds=6.0, amp=0.3, seed=0):
    """Bursts of a voiced tone separated by silence, like phrases with pauses."""
    n = int(SR * seconds)
    t = np.arange(n) / SR
    carrier = sum(
        np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((180, 360, 540, 720))
    )
    envelope = (np.sin(2 * np.pi * 1.5 * t) > -0.2).astype(np.float64)  # on/off phrases
    y = carrier * envelope
    return (amp * y / np.max(np.abs(y))).astype(np.float32)


def with_noise(y, snr_db, seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(y))
    scale = (
        np.sqrt(np.mean(y.astype(np.float64) ** 2) / 10 ** (snr_db / 10)) / noise.std()
    )
    return (y + scale * noise).astype(np.float32)


# --- SNR ---------------------------------------------------------------------


def test_clean_digital_silence_between_phrases_gives_the_cap():
    assert aq.estimate_snr_db(speechlike()) == aq.SNR_CAP_DB


def test_snr_falls_as_noise_rises_and_is_in_the_right_region():
    clean = speechlike()
    values = [aq.estimate_snr_db(with_noise(clean, snr)) for snr in (30, 20, 10, 5)]
    assert values == sorted(values, reverse=True)
    # frame-based estimate against whole-signal nominal SNR: within a few dB, and above it
    # because the speech frames are louder than the clip average
    for nominal, measured in zip((30, 20, 10, 5), values):
        assert nominal - 2 <= measured <= nominal + 8


def test_snr_of_silence_and_tiny_input_is_defined():
    assert aq.estimate_snr_db(np.zeros(SR, np.float32)) == 0.0
    assert aq.estimate_snr_db(np.zeros(100, np.float32)) == aq.SNR_CAP_DB
    assert aq.estimate_snr_db(np.zeros(0, np.float32)) == aq.SNR_CAP_DB


# --- clipping ----------------------------------------------------------------


def test_clipping_ratio_zero_for_clean_audio_and_positive_when_flattened():
    y = speechlike(amp=0.5)
    assert aq.clipping_ratio(y) == 0.0
    flattened = np.clip(y * 4, -1.0, 1.0)
    assert aq.clipping_ratio(flattened) > 0.01


def test_a_single_full_scale_peak_is_not_clipping():
    y = np.zeros(1000, np.float32)
    y[500] = 1.0
    assert aq.clipping_ratio(y) == 0.0


def test_a_run_of_full_scale_samples_is_counted_in_full():
    y = np.zeros(1000, np.float32)
    y[100:110] = 1.0  # ten samples stuck at the limit
    assert aq.clipping_ratio(y) == pytest.approx(10 / 1000)
    y[300:302] = -1.0  # a negative run of two
    assert aq.clipping_ratio(y) == pytest.approx(12 / 1000)


@pytest.mark.parametrize("y", [np.zeros(0), np.ones(1)])
def test_clipping_ratio_of_empty_or_one_sample_is_zero(y):
    assert aq.clipping_ratio(y) == 0.0


# --- band limit ---------------------------------------------------------------


def test_white_noise_has_energy_in_the_high_band():
    rng = np.random.default_rng(1)
    y = rng.standard_normal(SR * 2).astype(np.float32) * 0.1
    assert aq.high_band_db(y) > -5.0


def test_a_low_pass_signal_has_almost_no_high_band_energy():
    t = np.arange(SR * 2) / SR
    y = (0.3 * np.sin(2 * np.pi * 800 * t) + 0.1 * np.sin(2 * np.pi * 2400 * t)).astype(
        np.float32
    )
    # a pure tone leaks a little through the analysis window; real phone-band audio is far lower
    assert aq.high_band_db(y) < -45.0


def test_high_band_is_level_independent():
    rng = np.random.default_rng(2)
    y = rng.standard_normal(SR * 2).astype(np.float32) * 0.1
    assert aq.high_band_db(y * 0.01) == pytest.approx(aq.high_band_db(y), abs=0.01)


@pytest.mark.parametrize("y", [np.zeros(SR, np.float32), np.zeros(10, np.float32)])
def test_high_band_of_silence_or_tiny_input_is_the_floor(y):
    assert aq.high_band_db(y) == -120.0


# --- level ---------------------------------------------------------------------


def test_level_matches_a_known_amplitude_and_floors_silence():
    y = np.full(SR, 0.1, np.float32)
    assert aq.level_dbfs(y) == pytest.approx(-20.0, abs=0.5)
    assert aq.level_dbfs(y * 0.1) == pytest.approx(-40.0, abs=0.5)
    assert aq.level_dbfs(np.zeros(SR, np.float32)) == -120.0
    assert aq.level_dbfs(np.zeros(0, np.float32)) == -120.0


# --- measure_quality ----------------------------------------------------------


def test_measure_quality_reports_every_field_for_a_clean_clip():
    m = aq.measure_quality(speechlike(seconds=6.0))
    assert m.duration_seconds == pytest.approx(6.0)
    assert 3.0 < m.voiced_seconds <= 6.0
    assert m.snr_db == aq.SNR_CAP_DB
    assert m.clipping_ratio == 0.0
    assert m.level_dbfs < -10.0


def test_measure_quality_of_empty_audio_is_all_floor_values():
    m = aq.measure_quality(np.zeros(0, np.float32))
    assert (m.duration_seconds, m.voiced_seconds, m.snr_db, m.clipping_ratio) == (
        0,
        0,
        0,
        0,
    )
    assert m.high_band_db == -120.0
    assert m.level_dbfs == -120.0


def test_measure_quality_is_deterministic_and_does_not_modify_its_input():
    y = with_noise(speechlike(), 15)
    before = y.copy()
    assert aq.measure_quality(y) == aq.measure_quality(y)
    assert np.array_equal(y, before)


# --- hints and rating ---------------------------------------------------------


def broadband(seconds=12.0, amp=0.3):
    """Phrase-like bursts of a voice with harmonics up to 7 kHz, so it is not band-limited."""
    n = int(SR * seconds)
    t = np.arange(n) / SR
    carrier = sum(np.sin(2 * np.pi * 180 * k * t) / k for k in range(1, 39))
    envelope = (np.sin(2 * np.pi * 1.5 * t) > -0.2).astype(np.float64)
    y = carrier * envelope
    return (amp * y / np.max(np.abs(y))).astype(np.float32)


def codes(report):
    return [h.code for h in report.hints]


def test_a_clean_full_band_clip_of_enough_speech_has_no_hints():
    report = aq.assess_quality(broadband())
    assert report.hints == ()
    assert report.rating == "good"
    assert report.measures.high_band_db > aq.BAND_LIMITED_DB


def test_noise_warns_then_becomes_poor_as_it_worsens():
    clean = broadband()
    assert "noisy" in codes(aq.assess_quality(with_noise(clean, 20)))
    poor = aq.assess_quality(with_noise(clean, 6))
    assert "very_noisy" in codes(poor) and "noisy" not in codes(poor)
    assert poor.rating == "poor"


def test_clipping_warns_then_becomes_poor_as_it_worsens():
    base = broadband()
    assert "distorted" in codes(aq.assess_quality(np.clip(base * 4, -1, 1)))
    heavy = aq.assess_quality(np.clip(base * 40, -1, 1))
    assert "very_distorted" in codes(heavy) and heavy.rating == "poor"


def test_a_band_limited_clip_is_flagged_by_its_spectrum_or_its_source_rate():
    t = np.arange(SR * 12) / SR
    low = (
        0.3 * np.sin(2 * np.pi * 300 * t) * (np.sin(2 * np.pi * 1.5 * t) > -0.2)
    ).astype(np.float32)
    assert "band_limited" in codes(aq.assess_quality(low))
    # a full-band copy of an 8 kHz original is still a phone-quality recording
    assert "band_limited" in codes(
        aq.assess_quality(broadband(), source_sample_rate=8000)
    )
    assert "band_limited" not in codes(
        aq.assess_quality(broadband(), source_sample_rate=44100)
    )


def test_short_speech_is_advised_to_be_longer():
    report = aq.assess_quality(broadband(seconds=4.0))
    assert "short" in codes(report)
    assert report.rating == "fair"  # advice only: never worse than fair on its own


def test_volume_never_produces_a_hint():
    """The upload path levels quiet audio and the study found no effect."""
    quiet = broadband() * 0.03
    assert aq.assess_quality(quiet).hints == ()
    assert aq.assess_quality(broadband() * 3.0).hints == ()  # loud but not clipped


def test_the_thresholds_sit_where_the_calibration_put_them():
    """A change here must come with a new study (SPEECH_QUALITY_STUDY.md), not by accident."""
    assert (aq.SNR_WARN_DB, aq.SNR_POOR_DB) == (25.0, 15.0)
    assert (aq.CLIP_WARN_RATIO, aq.CLIP_POOR_RATIO) == (0.001, 0.02)
    assert aq.BAND_LIMITED_DB == -45.0
    assert aq.SHORT_VOICED_SECONDS == 10.0


def test_every_hint_has_a_code_a_known_severity_and_a_message():
    report = aq.assess_quality(with_noise(np.clip(broadband(4.0) * 40, -1, 1), 6))
    assert len(report.hints) >= 3
    for hint in report.hints:
        assert hint.code and hint.message and hint.severity in {"warning", "poor"}


def test_assess_file_reads_the_source_rate_and_decodes_at_16k(tmp_path):
    import soundfile as sf

    path = tmp_path / "phone.wav"
    sf.write(path, broadband(seconds=12.0)[::2][: 8000 * 12], 8000, subtype="PCM_16")
    report = aq.assess_file(str(path))
    assert "band_limited" in codes(
        report
    )  # because the file itself was recorded at 8 kHz
    assert report.measures.duration_seconds == pytest.approx(12.0, abs=0.1)


def test_assess_file_raises_on_an_unreadable_file(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(Exception):
        aq.assess_file(str(bad))
