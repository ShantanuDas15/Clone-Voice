"""The metrics behind backend/evaluate_synthesis.py, pinned on signals with known answers.

The study's conclusions are only as good as these functions, so every one is checked on
synthetic tones whose pitch, glide and level are known, plus the empty/silent/too-short
boundaries.
"""

import json

import numpy as np
import pytest
import soundfile as sf

from backend import evaluate_synthesis as es

SR = es.SAMPLE_RATE


def tone(
    f_start: float, f_end: float | None = None, seconds: float = 1.0, amp=0.3, tilt=1.0
):
    """A harmonic tone gliding linearly from ``f_start`` to ``f_end`` Hz.

    ``tilt`` < 1 weakens the upper harmonics (a duller timbre), > 1 strengthens them.
    """
    f_end = f_start if f_end is None else f_end
    n = int(SR * seconds)
    freq = np.linspace(f_start, f_end, n)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    y = sum((tilt**k) * np.sin((k + 1) * phase) / (k + 1) for k in range(4))
    return (amp * y / np.max(np.abs(y))).astype(np.float32)


# --- secs --------------------------------------------------------------------


def test_secs_identical_orthogonal_opposite():
    v = np.array([1.0, 2.0, 3.0])
    assert es.secs(v, v * 5) == pytest.approx(1.0)
    assert es.secs([1, 0], [0, 1]) == pytest.approx(0.0)
    assert es.secs(v, -v) == pytest.approx(-1.0)


@pytest.mark.parametrize("a,b", [([0, 0], [1, 0]), ([1, 0], [1, 0, 0])])
def test_secs_rejects_zero_or_mismatched_vectors(a, b):
    with pytest.raises(ValueError):
        es.secs(a, b)


# --- pitch -------------------------------------------------------------------


def test_semitones_octave_is_twelve():
    assert es.semitones(np.array([200.0]))[0] == pytest.approx(12.0)
    assert es.semitones(np.array([100.0]))[0] == pytest.approx(0.0)


def test_f0_track_recovers_a_known_pitch():
    voiced = es._voiced(es.f0_track(tone(220.0)))
    assert len(voiced) > 50
    assert np.median(voiced) == pytest.approx(220.0, rel=0.02)


def test_f0_track_covers_a_childs_pitch():
    voiced = es._voiced(es.f0_track(tone(380.0)))
    assert np.median(voiced) == pytest.approx(380.0, rel=0.02)


@pytest.mark.parametrize(
    "y", [np.zeros(SR, np.float32), np.zeros(0, np.float32), np.ones(1, np.float32)]
)
def test_f0_track_is_all_nan_for_silence_empty_or_one_sample(y):
    assert len(es._voiced(es.f0_track(y))) == 0


def test_f0_error_is_zero_for_same_pitch_and_twelve_for_an_octave():
    real = es.f0_track(tone(150.0))
    assert es.f0_error_semitones(real, es.f0_track(tone(150.0))) == pytest.approx(
        0, abs=0.3
    )
    assert es.f0_error_semitones(real, es.f0_track(tone(300.0))) == pytest.approx(
        12, abs=0.4
    )


def test_f0_error_is_none_when_unmeasurable():
    assert (
        es.f0_error_semitones(es.f0_track(tone(150.0)), es.f0_track(np.zeros(SR)))
        is None
    )


def test_f0_range_ratio_tracks_how_wide_the_pitch_moves():
    wide = es.f0_track(tone(150.0, 300.0, 2.0))  # one octave
    narrow = es.f0_track(tone(150.0, 225.0, 2.0))  # about 7 semitones
    assert es.f0_range_ratio(wide, wide) == pytest.approx(1.0)
    assert es.f0_range_ratio(wide, narrow) == pytest.approx(7.0 / 12.0, abs=0.1)


def test_f0_range_ratio_is_none_without_a_real_range_or_voicing():
    silent = es.f0_track(np.zeros(SR))
    assert es.f0_range_ratio(silent, es.f0_track(tone(150.0))) is None
    assert es.f0_range_ratio(es.f0_track(tone(150.0)), silent) is None


# --- level and spectrum ------------------------------------------------------


def test_rms_dbfs_known_levels_and_silence():
    assert es.rms_dbfs(np.ones(100) * 0.1) == pytest.approx(-20.0)
    assert es.rms_dbfs(np.zeros(100)) == -120.0
    assert es.rms_dbfs(np.zeros(0)) == -120.0


def test_spectrum_distance_is_level_invariant_but_sees_timbre():
    base = tone(200.0)
    assert es.long_term_spectrum_distance(base, base) == pytest.approx(0.0, abs=1e-6)
    assert es.long_term_spectrum_distance(base, base * 0.25) == pytest.approx(
        0.0, abs=0.05
    )
    dull, bright = tone(200.0, tilt=0.3), tone(200.0, tilt=1.5)
    assert es.long_term_spectrum_distance(dull, bright) > 1.0


@pytest.mark.parametrize("silent", [np.zeros(SR, np.float32), np.zeros(10, np.float32)])
def test_spectrum_distance_is_none_for_silent_or_too_short_audio(silent):
    assert es.long_term_spectrum_distance(tone(200.0), silent) is None
    assert es.long_term_spectrum_distance(silent, tone(200.0)) is None


# --- final pitch slope and punctuation contrast -----------------------------


def test_final_slope_sign_follows_the_ending():
    rising = es.final_f0_slope(es.f0_track(tone(150.0, 250.0)))
    falling = es.final_f0_slope(es.f0_track(tone(250.0, 150.0)))
    flat = es.final_f0_slope(es.f0_track(tone(200.0)))
    assert rising > 5.0
    assert falling < -5.0
    assert abs(flat) < 2.0


def test_final_slope_ignores_trailing_silence():
    y = np.concatenate([tone(150.0, 250.0), np.zeros(SR, np.float32)])
    assert es.final_f0_slope(es.f0_track(y)) > 5.0


def test_final_slope_is_none_with_too_little_voicing():
    assert es.final_f0_slope(np.full(50, np.nan)) is None
    assert es.final_f0_slope(es.f0_track(np.zeros(SR))) is None


def test_question_contrast_passes_only_when_the_ending_rises():
    base = tone(200.0)
    rising = es.punctuation_contrast(
        base, np.concatenate([tone(200.0, seconds=0.7), tone(200.0, 300.0, 0.3)]), "?"
    )
    falling = es.punctuation_contrast(base, tone(200.0, 140.0), "?")
    assert rising["passed"] == 1.0 and rising["slope_delta"] > 0
    assert falling["passed"] == 0.0 and falling["slope_delta"] < 0


def test_exclamation_contrast_needs_both_wider_pitch_and_more_energy():
    base = tone(200.0, 220.0, 2.0, amp=0.1)
    lively = tone(150.0, 330.0, 2.0, amp=0.4)
    quiet_wide = tone(150.0, 330.0, 2.0, amp=0.02)
    assert es.punctuation_contrast(base, lively, "!")["passed"] == 1.0
    assert es.punctuation_contrast(base, quiet_wide, "!")["passed"] == 0.0


def test_contrast_is_unmeasurable_for_silence_and_rejects_other_terminals():
    silent = np.zeros(SR, np.float32)
    assert es.punctuation_contrast(tone(200.0), silent, "?")["passed"] is None
    assert es.punctuation_contrast(tone(200.0), silent, "!")["passed"] is None
    with pytest.raises(ValueError):
        es.punctuation_contrast(tone(200.0), tone(200.0), ".")


# --- error rates -------------------------------------------------------------


def test_word_error_rate_cases():
    assert es.word_error_rate("the cat sat down", "The cat, sat down!") == 0.0
    assert es.word_error_rate("the cat sat down", "the dog sat down") == pytest.approx(
        0.25
    )
    assert es.word_error_rate("the cat sat down", "the cat sat") == pytest.approx(0.25)
    assert es.word_error_rate("the cat", "") == 1.0
    assert es.word_error_rate("one", "one two three") == pytest.approx(2.0)


def test_error_rates_reject_an_empty_reference():
    with pytest.raises(ValueError):
        es.word_error_rate("  ...  ", "x")
    with pytest.raises(ValueError):
        es.char_error_rate("", "x")


def test_char_error_rate():
    assert es.char_error_rate("cat", "cut") == pytest.approx(1 / 3)
    assert es.char_error_rate("Hello, world", "hello world") == 0.0


# --- statistics --------------------------------------------------------------


def test_bootstrap_ci_constant_empty_and_seeded():
    assert es.bootstrap_ci([0.5] * 10) == pytest.approx((0.5, 0.5, 0.5))
    assert all(np.isnan(v) for v in es.bootstrap_ci([]))
    values = [0.1, 0.4, 0.5, 0.9, 0.7]
    mean, low, high = es.bootstrap_ci(values, seed=3)
    assert low <= mean <= high
    assert es.bootstrap_ci(values, seed=3) == (mean, low, high)


def test_group_report_gap_and_gate():
    rows = [
        {"group": "adult", "secs": 0.85},
        {"group": "adult", "secs": 0.87},
        {"group": "child", "secs": 0.70},
        {"group": "child", "secs": None},  # unmeasurable rows are skipped, not counted
    ]
    report = es.group_report(rows, "secs")
    assert report["groups"]["child"]["n"] == 1
    assert report["groups"]["adult"]["mean"] == pytest.approx(0.86)
    assert report["best_to_worst_gap"] == pytest.approx(0.16)
    assert report["within_gap_limit"] is False
    assert es.group_report(rows, "secs", gap_limit=0.2)["within_gap_limit"] is True


def test_group_report_defaults_the_group_and_handles_no_data():
    assert "ungrouped" in es.group_report([{"secs": 0.8}], "secs")["groups"]
    empty = es.group_report([], "secs")
    assert empty["best_to_worst_gap"] is None and empty["within_gap_limit"] is None


# --- dataset loading ---------------------------------------------------------


def _speaker(root, name, files):
    d = root / name
    d.mkdir()
    for i in range(files):
        sf.write(d / f"{i}.wav", tone(200.0, seconds=0.2), SR)
    return d


def test_load_dataset_skips_speakers_with_fewer_than_three_files(tmp_path):
    _speaker(tmp_path, "a", 3)
    _speaker(tmp_path, "b", 2)
    (tmp_path / "notes.txt").write_text("not a speaker")
    assert list(es.load_dataset(tmp_path)) == ["a"]


def test_load_dataset_refuses_an_empty_directory(tmp_path):
    _speaker(tmp_path, "a", 1)
    with pytest.raises(SystemExit):
        es.load_dataset(tmp_path)


def test_load_groups(tmp_path):
    assert es.load_groups(None) == {}
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"a": "child"}))
    assert es.load_groups(f) == {"a": "child"}
    f.write_text("[1, 2]")
    with pytest.raises(SystemExit):
        es.load_groups(f)


# --- orchestration with the model and encoder replaced -----------------------


class _FakeEncoder:
    """Embeds audio as its mean-absolute level, so identical audio gives identical vectors."""

    def embed_utterance(self, y):
        level = float(np.mean(np.abs(y))) + 1e-3
        return np.array([1.0, level, 0.5])


def test_evaluate_speaker_reports_every_metric_and_leaves_no_files(
    tmp_path, monkeypatch
):
    speaker_dir = tmp_path / "spk"
    speaker_dir.mkdir()
    files = []
    for i in range(3):
        path = speaker_dir / f"{i}.wav"
        sf.write(path, tone(180.0 + 5 * i, 190.0, seconds=4.0, amp=0.3), SR)
        files.append(str(path))

    def fake_synth(text, embedding, speaker, seed):
        if text.endswith("?"):
            return np.concatenate([tone(180.0, seconds=0.7), tone(180.0, 300.0, 0.3)])
        if text.endswith("!"):
            return tone(150.0, 330.0, 1.0, amp=0.5)
        return tone(180.0, 185.0, 1.0, amp=0.1)

    monkeypatch.setattr(es, "_synthesize", fake_synth)
    row = es.evaluate_speaker(
        _FakeEncoder(), "spk", files, "child", 0, 1234, ["It is late", "We go now"]
    )

    assert row["speaker"] == "spk" and row["group"] == "child"
    assert -1.0 <= row["secs"] <= 1.0
    assert row["f0_error_semitones"] is not None and row["f0_error_semitones"] < 3.0
    assert row["f0_range_ratio"] is not None
    assert row["spectral_distance_db"] is not None
    assert row["question_rise_rate"] == 1.0
    assert row["exclamation_lift_rate"] == 1.0
    assert sorted(p.name for p in speaker_dir.iterdir()) == ["0.wav", "1.wav", "2.wav"]


def test_synthesize_removes_its_output_file(tmp_path, monkeypatch):
    out = tmp_path / "out.wav"
    sf.write(out, tone(200.0, seconds=0.2), SR)

    async def fake_pipeline(text, embedding, user_id):
        return str(out), 0.2

    monkeypatch.setattr(
        "backend.services.tts_pipeline.run_inference_pipeline", fake_pipeline
    )
    wav = es._synthesize("Hello.", np.zeros(256, np.float32), "spk", 1)
    assert len(wav) == int(0.2 * SR)
    assert not out.exists()


# --- pause profile -----------------------------------------------------------


def _gap(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), np.float32)


def test_pause_profile_finds_gaps_between_speech_with_their_lengths():
    y = np.concatenate([tone(200.0, seconds=0.6), _gap(0.5), tone(200.0, seconds=0.6)])
    gaps = es.pause_profile(y)
    assert len(gaps) == 1
    assert gaps[0] == pytest.approx(0.5, abs=0.05)


def test_pause_profile_orders_gaps_in_time_and_counts_each():
    y = np.concatenate(
        [tone(200.0, seconds=0.5), _gap(0.3), tone(200.0, seconds=0.5), _gap(0.6)]
        + [tone(200.0, seconds=0.5)]
    )
    gaps = es.pause_profile(y)
    assert len(gaps) == 2
    assert gaps[0] == pytest.approx(0.3, abs=0.05)
    assert gaps[1] == pytest.approx(0.6, abs=0.05)


def test_pause_profile_ignores_short_gaps_and_leading_trailing_silence():
    y = np.concatenate(
        [
            _gap(1.0),
            tone(200.0, seconds=0.5),
            _gap(0.1),
            tone(200.0, seconds=0.5),
            _gap(1.0),
        ]
    )
    assert es.pause_profile(y) == []
    assert es.pause_profile(y, min_gap_s=0.05) != []


@pytest.mark.parametrize(
    "y", [np.zeros(SR, np.float32), np.zeros(0, np.float32), np.ones(10, np.float32)]
)
def test_pause_profile_of_silence_empty_or_tiny_audio_is_empty(y):
    assert es.pause_profile(y) == []


# --- balanced speaker choice -------------------------------------------------


def test_select_speakers_alternates_groups_and_is_deterministic():
    dataset = {s: [] for s in ["a", "b", "c", "d", "e", "f"]}
    groups = {"a": "low", "b": "low", "c": "low", "d": "high", "e": "high", "f": "high"}
    chosen = es.select_speakers(dataset, groups, 4)
    assert chosen == ["d", "a", "e", "b"]  # high, low, high, low (groups sorted)
    assert es.select_speakers(dataset, groups, 4) == chosen


def test_select_speakers_without_groups_is_the_first_sorted_and_caps_at_available():
    dataset = {s: [] for s in ["c", "a", "b"]}
    assert es.select_speakers(dataset, {}, 2) == ["a", "b"]
    assert es.select_speakers(dataset, {}, 10) == ["a", "b", "c"]
    assert es.select_speakers({}, {}, 3) == []


def test_select_speakers_with_an_unbalanced_group_uses_what_exists():
    dataset = {s: [] for s in ["a", "b", "c"]}
    groups = {"a": "low", "b": "high", "c": "high"}
    assert es.select_speakers(dataset, groups, 3) == ["b", "a", "c"]


# --- stimuli, transcriber and orchestration ---------------------------------


def test_load_stimuli_reads_the_fixture_and_rejects_bad_files(tmp_path):
    paragraphs = es.load_stimuli(es.DEFAULT_SENTENCES, "paragraphs")
    typed = es.load_stimuli(es.DEFAULT_SENTENCES, "typed")
    assert len(paragraphs) >= 4 and len(typed) >= 4
    bad = tmp_path / "s.json"
    bad.write_text(json.dumps({"paragraphs": [{"id": "x"}]}))
    with pytest.raises(SystemExit):
        es.load_stimuli(bad, "paragraphs")
    with pytest.raises(SystemExit):
        es.load_stimuli(bad, "typed")


def test_whisper_transcriber_explains_a_missing_dependency(monkeypatch):
    import sys

    monkeypatch.setitem(
        sys.modules, "faster_whisper", None
    )  # import raises ImportError
    with pytest.raises(SystemExit, match="faster-whisper"):
        es.make_whisper_transcriber()


def _fake_synth_with_pause(text, embedding, speaker, seed):
    """Two voiced bursts with a 0.5 s gap, however long the text is."""
    return np.concatenate(
        [
            tone(200.0, seconds=0.6),
            np.zeros(int(SR * 0.5), np.float32),
            tone(200.0, seconds=0.6),
        ]
    )


def test_evaluate_stimuli_scores_wer_pauses_and_speaking_rate(monkeypatch):
    monkeypatch.setattr(es, "_synthesize", _fake_synth_with_pause)
    heard = iter(["the cat sat", "at 10:30 p.m."])  # paragraph first, then typed

    row = es.evaluate_stimuli(
        np.zeros(256),
        "spk",
        1,
        [{"id": "p0", "text": "The cat sat."}],
        [{"id": "t0", "text": "At 10:30 PM"}],
        lambda audio: next(heard),
    )
    assert row["para_wer"] == 0.0  # punctuation and case are ignored
    assert row["typed_wer"] == 0.0  # both sides become "at ten thirty pee em"
    assert row["para_pause_count"] == 1.0
    assert row["para_pause_mean_s"] == pytest.approx(0.5, abs=0.05)
    assert row["para_sec_per_word"] == pytest.approx(1.7 / 3, abs=0.02)


def test_evaluate_stimuli_without_a_transcriber_still_reports_pauses(monkeypatch):
    monkeypatch.setattr(es, "_synthesize", _fake_synth_with_pause)
    row = es.evaluate_stimuli(
        np.zeros(256),
        "spk",
        1,
        [{"id": "p", "text": "One. Two."}],
        [{"id": "t", "text": "x"}],
        None,
    )
    assert row["para_wer"] is None and row["typed_wer"] is None
    assert row["para_pause_count"] == 1.0


def test_evaluate_stimuli_scores_a_wrong_transcript(monkeypatch):
    monkeypatch.setattr(es, "_synthesize", _fake_synth_with_pause)
    row = es.evaluate_stimuli(
        np.zeros(256),
        "spk",
        1,
        [{"id": "p", "text": "the cat sat down"}],
        [],
        lambda audio: "the dog sat down",
    )
    assert row["para_wer"] == pytest.approx(0.25)
    assert row["typed_wer"] is None  # no typed stimuli given


# --- enrolment comparison ----------------------------------------------------


def _speaker_files(tmp_path, n_files=6):
    files = []
    for i in range(n_files):
        path = tmp_path / f"{i}.wav"
        sf.write(path, tone(180.0 + 3 * i, 190.0, seconds=4.0, amp=0.3), SR)
        files.append(str(path))
    return files


class _LevelEncoder:
    """Embeds audio as [1, mean level, i-th feature], so different clips differ slightly."""

    def embed_utterance(self, y):
        y = np.asarray(y)
        return np.array(
            [1.0, float(np.mean(np.abs(y))) + 1e-3, float(np.std(y)) + 1e-3]
        )


def test_evaluate_enrollment_compares_single_and_multi_with_a_paired_seed(
    tmp_path, monkeypatch
):
    seeds = []

    def fake_synth(text, embedding, speaker, seed):
        seeds.append(seed)
        return tone(180.0, 185.0, 1.0, amp=0.1)

    monkeypatch.setattr(es, "_synthesize", fake_synth)
    row = es.evaluate_enrollment(
        _LevelEncoder(),
        "spk",
        _speaker_files(tmp_path),
        "grp",
        2,
        1234,
        3,
        ["One", "Two"],
    )
    assert row["speaker"] == "spk" and row["group"] == "grp"
    for key in ("emb_secs_single", "emb_secs_multi", "secs_single", "secs_multi"):
        assert -1.0 <= row[key] <= 1.0
    assert row["f0_error_single"] is not None and row["spectral_multi"] is not None
    # both profiles are synthesized with the same seeds: the comparison is paired
    assert seeds[: len(seeds) // 2] == seeds[len(seeds) // 2 :]
    assert len(seeds) == 4  # 2 sentences x {single, multi}


def test_evaluate_enrollment_with_one_clip_makes_the_profiles_identical(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        es,
        "_synthesize",
        lambda text, embedding, speaker, seed: tone(180.0, 185.0, 1.0, amp=0.1),
    )
    row = es.evaluate_enrollment(
        _LevelEncoder(), "spk", _speaker_files(tmp_path), "g", 0, 1, 1, ["One"]
    )
    assert row["secs_single"] == pytest.approx(row["secs_multi"])
    assert row["emb_secs_single"] == pytest.approx(row["emb_secs_multi"], abs=1e-6)


def test_evaluate_enrollment_needs_three_clips_left_for_scoring(tmp_path):
    files = _speaker_files(tmp_path, n_files=5)  # reference + 4 held out
    with pytest.raises(ValueError):
        es.evaluate_enrollment(_LevelEncoder(), "spk", files, "g", 0, 1, 3, ["One"])
    with pytest.raises(ValueError):
        es.evaluate_enrollment(_LevelEncoder(), "spk", files, "g", 0, 1, 0, ["One"])
