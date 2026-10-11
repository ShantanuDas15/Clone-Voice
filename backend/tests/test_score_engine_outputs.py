"""The engine benchmark scorer (SPEECH_QUALITY_PLAN.md S4.2b)."""

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from backend import score_engine_outputs as sc
from backend.schemas.synthesize import SynthesizeRequest

SR = 16000


def _tone(freq: float, seconds: float = 1.5) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class _SpectrumEncoder:
    """A stand-in speaker encoder: the first FFT bins, so the same pitch gives the same vector."""

    def embed_utterance(self, y: np.ndarray) -> np.ndarray:
        v = np.abs(np.fft.rfft(y[: SR // 2], 512))[:64].astype(np.float64)
        return v / (np.linalg.norm(v) or 1.0)


def _write(path: Path, y: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), y, SR)


@pytest.fixture
def corpus(tmp_path) -> Path:
    root = tmp_path / "corpus"
    for speaker, f in (("a", 150.0), ("b", 300.0)):
        _write(root / speaker / "0_ref_x.wav", _tone(f))
        _write(root / speaker / "1_y.wav", _tone(f))
        _write(root / speaker / "1_z.wav", _tone(f))
    (root / "groups.json").write_text(json.dumps({"a": "low", "b": "high"}))
    return root


@pytest.fixture
def texts():
    return sc.load_benchmark_texts()


# --- the shipped fixture -----------------------------------------------------


def test_the_benchmark_texts_are_ten_and_one_skips_wer(texts):
    assert len(texts) == 10
    assert [i for i, t in enumerate(texts) if t["skip_wer"]] == [7]


def test_every_benchmark_text_is_accepted_by_the_api(texts):
    for item in texts:
        SynthesizeRequest(
            text=item["text"], voice_profile_id="0" * 8 + "-0000-0000-0000-" + "0" * 12
        )


def test_an_empty_texts_file_is_refused(tmp_path):
    empty = tmp_path / "t.json"
    empty.write_text(json.dumps({"texts": []}))
    with pytest.raises(SystemExit):
        sc.load_benchmark_texts(empty)


# --- scoring one engine -----------------------------------------------------


def _score(tmp_path, corpus, texts, files, transcribe=None):
    engine = tmp_path / "out" / "eng"
    for speaker, i, freq in files:
        _write(engine / speaker / f"{i}.wav", _tone(freq))
    from backend import evaluate_synthesis as ev

    return sc.score_engine(
        engine,
        ev.load_dataset(corpus),
        ev.load_groups(corpus / "groups.json"),
        texts,
        _SpectrumEncoder(),
        transcribe,
        lambda text: text,
    )


def test_matching_pitch_scores_higher_than_a_wrong_voice(tmp_path, corpus, texts):
    rows = _score(tmp_path, corpus, texts, [("a", 0, 150.0), ("a", 1, 300.0)])
    same, other = rows
    assert same["secs"] > other["secs"] and same["secs"] > 0.99
    assert same["group"] == "low" and same["duration"] == pytest.approx(1.5)


def test_missing_outputs_are_skipped_not_errors(tmp_path, corpus, texts):
    rows = _score(tmp_path, corpus, texts, [("a", 0, 150.0), ("b", 3, 300.0)])
    assert [(r["speaker"], r["i"]) for r in rows] == [("a", 0), ("b", 3)]


def test_wer_is_scored_only_when_a_transcriber_is_given_and_the_text_allows(
    tmp_path, corpus, texts
):
    files = [("a", 0, 150.0), ("a", 7, 150.0)]
    without = _score(tmp_path, corpus, texts, files)
    assert all("wer" not in r for r in without)
    with_asr = _score(
        tmp_path, corpus, texts, files, transcribe=lambda y: "hello there"
    )
    assert with_asr[0]["wer"] == 0.0  # text 0 matches what the "ASR" heard
    assert "wer" not in with_asr[1]  # text 7 is flagged skip_wer


def test_a_speaker_with_no_group_is_labelled_all(tmp_path, corpus, texts):
    (corpus / "groups.json").write_text("{}")
    rows = _score(tmp_path, corpus, texts, [("a", 0, 150.0)])
    assert rows[0]["group"] == "all"


# --- summarizing ------------------------------------------------------------


def _row(speaker, i, group, secs, wer=None):
    r = {
        "speaker": speaker,
        "group": group,
        "i": i,
        "secs": secs,
        "f0_error_semitones": 1.0,
        "f0_range_ratio": 1.0,
    }
    if wer is not None:
        r["wer"] = wer
    return r


def test_summary_reports_means_group_gap_and_paired_difference():
    base = [_row("a", 0, "low", 0.8, 0.2), _row("b", 0, "high", 0.6, 0.4)]
    new = [_row("a", 0, "low", 0.9, 0.0), _row("b", 0, "high", 0.9, 0.0)]
    report = sc.summarize({"base": base, "new": new}, baseline="base")
    assert report["engines"]["base"]["secs"]["mean"] == pytest.approx(0.7)
    assert report["engines"]["base"]["group_gap"] == pytest.approx(0.2)
    assert report["engines"]["new"]["group_gap"] == pytest.approx(0.0)
    paired = report["paired_vs_baseline"]["new"]
    assert paired["secs_difference"]["mean"] == pytest.approx(0.2)
    assert paired["secs_better_count"] == 2
    assert paired["wer_difference"]["mean"] == pytest.approx(-0.3)
    assert "base" not in report["paired_vs_baseline"]


def test_wer_above_threshold_is_counted():
    rows = [_row("a", 0, "g", 0.8, 0.5), _row("a", 1, "g", 0.8, 0.1)]
    assert sc.summarize({"e": rows})["engines"]["e"]["wer_above_0.3"] == 1


def test_an_engine_with_no_wer_reports_nulls_not_nan():
    report = sc.summarize({"e": [_row("a", 0, "g", 0.8)]})
    wer = report["engines"]["e"]["wer"]
    assert wer == {"mean": None, "low": None, "high": None, "n": 0}
    json.dumps(report, allow_nan=False)  # a strict JSON writer accepts it


def test_pairing_ignores_outputs_the_baseline_lacks():
    base = [_row("a", 0, "g", 0.5)]
    new = [_row("a", 0, "g", 0.7), _row("a", 1, "g", 0.9)]
    paired = sc.summarize({"b": base, "n": new}, "b")["paired_vs_baseline"]["n"]
    assert paired["secs_difference"]["n"] == 1


# --- the command line -------------------------------------------------------


def test_main_scores_each_engine_and_writes_the_report(tmp_path, corpus, capsys):
    for speaker, f in (("a", 150.0), ("b", 300.0)):
        _write(tmp_path / "out" / "x" / speaker / "0.wav", _tone(f))
        _write(tmp_path / "out" / "y" / speaker / "0.wav", _tone(f * 1.5))
    report_path = tmp_path / "report.json"
    with patch("resemblyzer.VoiceEncoder", lambda device: _SpectrumEncoder()):
        code = sc.main(
            [
                "--corpus",
                str(corpus),
                "--outputs",
                str(tmp_path / "out"),
                "--engines",
                "x,y",
                "--baseline",
                "y",
                "--whisper-model",
                "none",
                "--out",
                str(report_path),
            ]
        )
    assert code == 0
    report = json.loads(report_path.read_text())
    assert set(report["engines"]) == {"x", "y"}
    assert (
        report["engines"]["x"]["secs"]["mean"] > report["engines"]["y"]["secs"]["mean"]
    )
    assert report["paired_vs_baseline"]["x"]["secs_better_count"] == 2
    assert "engines" in json.loads(capsys.readouterr().out)


def test_main_refuses_a_baseline_that_is_not_an_engine(tmp_path, corpus):
    with pytest.raises(SystemExit):
        sc.main(
            [
                "--corpus",
                str(corpus),
                "--outputs",
                str(tmp_path),
                "--engines",
                "x",
                "--baseline",
                "other",
            ]
        )


# --- the optional independent encoder and naturalness score ------------------


class _OtherEncoder:
    """A second, different encoder: the loudest of 8 coarse bands, so it disagrees with the first."""

    def __init__(self):
        self.calls = 0

    def embed_utterance(self, y: np.ndarray) -> np.ndarray:
        self.calls += 1
        v = np.abs(np.fft.rfft(y[: SR // 2], 512))[:8].astype(np.float64)
        return v / (np.linalg.norm(v) or 1.0)


def _score_with(tmp_path, corpus, texts, independent=None, predict_mos=None):
    engine = tmp_path / "out" / "eng"
    _write(engine / "a" / "0.wav", _tone(150.0))
    _write(engine / "a" / "1.wav", _tone(300.0))
    from backend import evaluate_synthesis as ev

    return sc.score_engine(
        engine,
        ev.load_dataset(corpus),
        ev.load_groups(corpus / "groups.json"),
        texts,
        _SpectrumEncoder(),
        None,
        lambda text: text,
        independent,
        predict_mos,
    )


def test_the_extra_columns_exist_only_when_asked_for(tmp_path, corpus, texts):
    plain = _score_with(tmp_path, corpus, texts)
    assert all("secs_independent" not in r and "mos" not in r for r in plain)
    rows = _score_with(
        tmp_path,
        corpus,
        texts,
        _OtherEncoder(),
        lambda y: 3.5 + float(np.max(np.abs(y))),
    )
    assert all(isinstance(r["secs_independent"], float) for r in rows)
    assert rows[0]["mos"] == pytest.approx(3.8, abs=0.01)


def test_the_independent_score_comes_from_the_independent_encoder(
    tmp_path, corpus, texts
):
    other = _OtherEncoder()
    rows = _score_with(tmp_path, corpus, texts, other)
    assert other.calls > 0
    # The matching-pitch output scores higher than the wrong-pitch one with this encoder as well.
    assert rows[0]["secs_independent"] > rows[1]["secs_independent"]


def _extra_row(speaker, i, group, secs, ind=None, mos=None):
    row = _row(speaker, i, group, secs)
    if ind is not None:
        row["secs_independent"] = ind
    if mos is not None:
        row["mos"] = mos
    return row


def test_summary_pairs_the_independent_similarity_and_the_mos():
    base = [
        _extra_row("a", 0, "g", 0.8, 0.5, 3.0),
        _extra_row("a", 1, "g", 0.8, 0.5, 3.2),
    ]
    new = [
        _extra_row("a", 0, "g", 0.9, 0.7, 4.0),
        _extra_row("a", 1, "g", 0.9, 0.4, 4.4),
    ]
    report = sc.summarize({"base": base, "new": new}, baseline="base")
    assert report["engines"]["new"]["mos"]["mean"] == pytest.approx(4.2)
    paired = report["paired_vs_baseline"]["new"]
    assert paired["mos_difference"]["mean"] == pytest.approx(1.1)
    assert paired["mos_better_count"] == 2
    assert paired["secs_independent_difference"]["mean"] == pytest.approx(0.05)
    assert paired["secs_independent_better_count"] == 1


def test_without_the_extras_the_summary_reports_nulls():
    report = sc.summarize({"e": [_row("a", 0, "g", 0.8)]})
    assert report["engines"]["e"]["mos"]["n"] == 0
    json.dumps(report, allow_nan=False)


def test_main_loads_the_extras_only_when_the_flags_ask(tmp_path, corpus, capsys):
    _write(tmp_path / "out" / "x" / "a" / "0.wav", _tone(150.0))
    calls = {"ecapa": 0, "utmos": 0}

    def fake_ecapa():
        calls["ecapa"] += 1
        return _OtherEncoder()

    def fake_utmos():
        calls["utmos"] += 1
        return lambda y: 4.0

    base_args = [
        "--corpus",
        str(corpus),
        "--outputs",
        str(tmp_path / "out"),
        "--engines",
        "x",
        "--whisper-model",
        "none",
    ]
    with patch(
        "resemblyzer.VoiceEncoder", lambda device: _SpectrumEncoder()
    ), patch.object(sc, "make_ecapa_encoder", fake_ecapa), patch.object(
        sc, "make_utmos_predictor", fake_utmos
    ):
        sc.main(base_args)
        assert calls == {"ecapa": 0, "utmos": 0}
        capsys.readouterr()
        sc.main(base_args + ["--independent-encoder", "ecapa", "--mos", "utmos"])
    assert calls == {"ecapa": 1, "utmos": 1}
    report = json.loads(capsys.readouterr().out)
    assert report["engines"]["x"]["mos"]["mean"] == 4.0
    assert report["engines"]["x"]["secs_independent"]["n"] == 1


def test_a_missing_speechbrain_gives_an_install_hint(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", None)
    with pytest.raises(SystemExit, match="speechbrain"):
        sc.make_ecapa_encoder()


def test_group_gaps_are_reported_for_both_encoders():
    rows = [
        _extra_row("a", 0, "low", 0.8, 0.6),
        _extra_row("b", 0, "high", 0.7, 0.3),
    ]
    engine = sc.summarize({"e": rows})["engines"]["e"]
    assert engine["group_gap"] == pytest.approx(0.1)
    assert engine["group_gap_independent"] == pytest.approx(0.3)
    assert engine["group_secs_independent"] == {"low": 0.6, "high": 0.3}


def test_a_group_gap_needs_the_independent_scores_to_exist():
    engine = sc.summarize({"e": [_row("a", 0, "g", 0.8)]})["engines"]["e"]
    assert (
        engine["group_gap_independent"] is None
        and engine["group_secs_independent"] == {}
    )


def test_the_written_report_keeps_every_output_but_stdout_stays_a_summary(
    tmp_path, corpus, capsys
):
    _write(tmp_path / "out" / "x" / "a" / "0.wav", _tone(150.0))
    path = tmp_path / "report.json"
    with patch("resemblyzer.VoiceEncoder", lambda device: _SpectrumEncoder()):
        sc.main(
            [
                "--corpus",
                str(corpus),
                "--outputs",
                str(tmp_path / "out"),
                "--engines",
                "x",
                "--whisper-model",
                "none",
                "--out",
                str(path),
            ]
        )
    assert "rows" not in json.loads(capsys.readouterr().out)
    saved = json.loads(path.read_text())
    assert len(saved["rows"]["x"]) == 1 and saved["engines"]["x"]["outputs"] == 1
