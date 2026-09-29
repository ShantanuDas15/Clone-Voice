"""The metrics and degradations behind backend/evaluate_preprocessing.py.

The tool's conclusions are only as good as these functions, so they are pinned
on data where the right answer is known.
"""

import numpy as np
import pytest
import soundfile as sf

from backend import evaluate_preprocessing as ep


def _unit(vectors) -> np.ndarray:
    v = np.asarray(vectors, dtype=np.float64)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _speakers(n_speakers=4, per=5, noise=0.0, seed=0):
    """One well-separated direction per speaker, optionally blurred by noise."""
    rng = np.random.default_rng(seed)
    dim = 16
    centres = np.eye(dim)[:n_speakers]
    emb, labels = [], []
    for s in range(n_speakers):
        for _ in range(per):
            emb.append(centres[s] + noise * rng.standard_normal(dim))
            labels.append(f"s{s}")
    return _unit(emb), labels


# --- verification_scores -----------------------------------------------------


def test_pair_counts():
    emb, labels = _speakers(n_speakers=3, per=3)
    same, diff = ep.verification_scores(emb, labels)
    assert len(same) == 3 * (3 * 2 // 2)  # 3 speakers x C(3,2)
    assert len(diff) == (9 * 8 // 2) - len(same)


def test_identical_utterances_score_one_and_orthogonal_zero():
    emb, labels = _speakers(n_speakers=2, per=2)
    same, diff = ep.verification_scores(emb, labels)
    assert np.allclose(same, 1.0)
    assert np.allclose(diff, 0.0)


# --- equal_error_rate --------------------------------------------------------


def test_eer_is_zero_when_perfectly_separated():
    assert ep.equal_error_rate(np.array([0.9, 0.8, 0.95]), np.array([0.1, 0.2])) == 0.0


def test_eer_is_half_when_the_distributions_are_identical():
    scores = np.linspace(0, 1, 200)
    assert ep.equal_error_rate(scores, scores) == pytest.approx(0.5, abs=0.01)


def _brute_force_eer(same, diff):
    best_gap, eer = np.inf, 1.0
    for t in np.unique(np.concatenate([same, diff])):
        fr, fa = np.mean(same < t), np.mean(diff >= t)
        if abs(fr - fa) < best_gap:
            best_gap, eer = abs(fr - fa), (fr + fa) / 2
    return eer


@pytest.mark.parametrize("seed", range(5))
def test_fast_eer_matches_the_obvious_implementation(seed):
    rng = np.random.default_rng(seed)
    same = rng.normal(0.8, 0.1, 300)
    diff = rng.normal(0.5, 0.15, 900)
    assert ep.equal_error_rate(same, diff) == pytest.approx(
        _brute_force_eer(same, diff)
    )


# --- d_prime -----------------------------------------------------------------


def test_d_prime_grows_with_separation_and_is_zero_for_identical():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 1, 2000)
    assert ep.d_prime(base, base) == pytest.approx(0.0)
    assert ep.d_prime(base + 3, base) == pytest.approx(3.0, abs=0.01)
    assert ep.d_prime(base + 3, base) > ep.d_prime(base + 1, base) > 0


def test_d_prime_handles_zero_variance():
    assert ep.d_prime(np.ones(5), np.zeros(5)) == 0.0


# --- bootstrap_eer -----------------------------------------------------------


def test_bootstrap_interval_contains_the_point_estimate():
    emb, labels = _speakers(n_speakers=12, per=6, noise=0.9, seed=1)
    same, diff = ep.verification_scores(emb, labels)
    point = ep.equal_error_rate(same, diff)
    low, high = ep.bootstrap_eer(emb, labels, rounds=100)
    assert low <= point <= high
    assert 0 < point < 0.5  # a genuinely noisy case, not a trivial one


def test_bootstrap_does_not_count_a_repeated_speaker_as_two_speakers():
    """Regression: a speaker drawn twice used to give two identical copies
    labelled as different speakers, scoring 1.0 as false accepts and pushing
    the interval far above the truth. Perfectly separated data must stay at 0."""
    emb, labels = _speakers(n_speakers=6, per=4, noise=0.0)
    assert ep.bootstrap_eer(emb, labels, rounds=100) == (0.0, 0.0)


def test_bootstrap_is_reproducible():
    emb, labels = _speakers(n_speakers=8, per=5, noise=0.8, seed=2)
    assert ep.bootstrap_eer(emb, labels, rounds=30, seed=7) == ep.bootstrap_eer(
        emb, labels, rounds=30, seed=7
    )


# --- degradations ------------------------------------------------------------


def _tone(seconds=2.0, freq=440.0, amp=0.3):
    t = np.arange(int(seconds * ep.SAMPLE_RATE)) / ep.SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_gain_scales_and_clips_at_full_scale():
    y = _tone(amp=0.3)
    assert np.max(np.abs(ep.gain(y, 0.1))) == pytest.approx(0.03, abs=1e-3)
    assert np.max(np.abs(ep.gain(y, 8.0))) == 1.0


def test_add_noise_hits_the_requested_snr():
    y = _tone(amp=0.3)
    noisy = ep.add_noise(y, snr_db=15.0)
    noise = noisy - y
    measured = 10 * np.log10(np.mean(y**2) / np.mean(noise**2))
    assert measured == pytest.approx(15.0, abs=0.5)


def test_telephone_band_removes_energy_above_4khz_and_keeps_length():
    y = (_tone(freq=1000.0) + _tone(freq=6000.0)).astype(np.float32)
    out = ep.telephone_band(y)
    assert abs(len(out) - len(y)) <= 2
    spectrum = np.abs(np.fft.rfft(out))
    freqs = np.fft.rfftfreq(len(out), 1 / ep.SAMPLE_RATE)
    assert (
        spectrum[np.argmin(np.abs(freqs - 6000))]
        < 0.05 * spectrum[np.argmin(np.abs(freqs - 1000))]
    )


def test_pad_and_pauses_adds_exactly_the_silence_requested():
    y = _tone(seconds=2.0)
    out = ep.pad_and_pauses(y, edge_s=3.0, pause_s=1.5)
    assert len(out) == len(y) + int(6.0 * ep.SAMPLE_RATE) + int(1.5 * ep.SAMPLE_RATE)
    assert np.all(out[: 3 * ep.SAMPLE_RATE] == 0)


def test_every_degradation_returns_float32_audio_of_similar_scale():
    y = _tone()
    for name, apply in ep.DEGRADATIONS.items():
        out = apply(y)
        assert out.dtype == np.float32, name
        assert np.max(np.abs(out)) <= 1.0, name


# --- dataset loading ---------------------------------------------------------


def _write(path, seconds=1.0):
    sf.write(path, _tone(seconds), ep.SAMPLE_RATE)


def test_load_dataset_groups_by_speaker_and_skips_thin_ones(tmp_path):
    for speaker, files in {"a": 4, "b": 3, "c": 3, "thin": 2}.items():
        (tmp_path / speaker).mkdir()
        for i in range(files):
            _write(tmp_path / speaker / f"{i}.wav")
    (tmp_path / "a" / "notes.txt").write_text("not audio")

    paths, labels = ep.load_dataset(tmp_path)

    assert sorted(set(labels)) == ["a", "b", "c"]
    assert labels.count("a") == 4 and len(paths) == 10


def test_load_dataset_needs_three_speakers(tmp_path):
    for speaker in ("a", "b"):
        (tmp_path / speaker).mkdir()
        for i in range(3):
            _write(tmp_path / speaker / f"{i}.wav")
    with pytest.raises(SystemExit):
        ep.load_dataset(tmp_path)


# --- paired_difference -------------------------------------------------------


def test_paired_difference_reports_mean_interval_and_share_improved():
    baseline = np.array([0.80, 0.82, 0.78, 0.81, 0.79, 0.83])
    candidate = baseline + np.array([0.02, 0.03, -0.01, 0.02, 0.03, 0.02])
    result = ep.paired_difference(candidate, baseline)
    assert result["mean"] == pytest.approx(0.0183, abs=1e-3)
    assert result["ci95_low"] < result["mean"] < result["ci95_high"]
    assert result["improved"] == pytest.approx(5 / 6)
    assert result["n"] == 6


def test_paired_difference_of_identical_scores_is_zero_with_no_interval():
    same = [0.8, 0.81, 0.79]
    result = ep.paired_difference(same, same)
    assert result["mean"] == 0.0
    assert result["ci95_low"] == result["ci95_high"] == 0.0
    assert result["improved"] == 0.0
