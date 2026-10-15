"""The blind listening-test kit (SPEECH_QUALITY_PLAN.md S0.5)."""

import json

import numpy as np
import pytest
import soundfile as sf

from backend import listening_test as lt
from backend.services.audio_polish import integrated_loudness

SR = 16000


def _tone(amp=0.2, seconds=1.0, hz=180.0):
    t = np.arange(int(SR * seconds)) / SR
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _system(root, name, amp, items=("s1/0.wav", "s1/1.wav", "s2/0.wav")):
    for item in items:
        path = root / name / item
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), _tone(amp), SR)
    return root / name


# --- audio ---------------------------------------------------------------------------


def test_match_loudness_brings_quiet_and_loud_to_the_same_level():
    quiet = lt.match_loudness(_tone(0.02), SR)
    loud = lt.match_loudness(_tone(0.5), SR)
    assert integrated_loudness(quiet, SR) == pytest.approx(lt.TARGET_LUFS, abs=0.5)
    assert integrated_loudness(loud, SR) == pytest.approx(lt.TARGET_LUFS, abs=0.5)


def test_match_loudness_never_clips_a_peaky_signal():
    wave = np.zeros(SR, np.float32)
    wave[::4000] = 0.9
    wave += _tone(0.001)
    assert np.max(np.abs(lt.match_loudness(wave, SR))) <= lt.PEAK_LIMIT + 1e-6


@pytest.mark.parametrize("wave", [np.zeros(0, np.float32), np.zeros(SR, np.float32)])
def test_match_loudness_leaves_silence_alone(wave):
    assert not np.any(lt.match_loudness(wave, SR))


def test_degrade_is_repeatable_and_worse():
    wave = _tone(0.2) + _tone(0.2, hz=6000.0)
    a, b = lt.degrade(wave, SR, 3), lt.degrade(wave, SR, 3)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, lt.degrade(wave, SR, 4))
    # The 6 kHz tone is filtered out; only the (much weaker) noise is left there.
    bin_6k = int(6000 * len(wave) / SR)
    assert abs(np.fft.rfft(a)[bin_6k]) < 0.1 * abs(np.fft.rfft(wave)[bin_6k])


# --- planning ------------------------------------------------------------------------


def _clips(*names):
    return {n: {f"x/{i}.wav": None for i in range(4)} for n in names}


def test_plan_pairs_the_baseline_with_each_other_system():
    trials = lt.plan_trials(_clips("base", "p", "q"), seed=1)
    pairs = [t for t in trials if t["kind"] == "pair"]
    assert len(pairs) == 8
    assert all("base" in (t["a"], t["b"]) for t in pairs)
    assert {frozenset((t["a"], t["b"])) for t in pairs} == {
        frozenset(("base", "p")),
        frozenset(("base", "q")),
    }


def test_plan_is_deterministic_and_the_sides_are_mixed():
    a = lt.plan_trials(_clips("base", "p"), seed=5, anchors=2)
    assert a == lt.plan_trials(_clips("base", "p"), seed=5, anchors=2)
    assert a != lt.plan_trials(_clips("base", "p"), seed=6, anchors=2)
    first = {
        t["a"]
        for t in lt.plan_trials(_clips("base", "p"), seed=1)
        if t["kind"] == "pair"
    }
    assert first == {"base", "p"}


def test_plan_ids_are_neutral_and_unique():
    trials = lt.plan_trials(_clips("base", "p"), seed=1, anchors=2)
    ids = [t["id"] for t in trials]
    assert ids == sorted(set(ids)) or len(set(ids)) == len(ids)
    assert all(i.startswith("t") and i[1:].isdigit() for i in ids)


def test_plan_caps_pairs_and_anchors():
    trials = lt.plan_trials(_clips("base", "p"), seed=1, max_per_pair=2, anchors=9)
    assert sum(t["kind"] == "pair" for t in trials) == 2
    assert sum(t["kind"] == "anchor" for t in trials) == 4  # only 4 clips exist


def test_plan_refuses_one_system_or_no_shared_clip():
    with pytest.raises(ValueError):
        lt.plan_trials(_clips("only"), seed=1)
    with pytest.raises(ValueError):
        lt.plan_trials({"a": {"1.wav": None}, "b": {"2.wav": None}}, seed=1)


# --- build ---------------------------------------------------------------------------


def test_build_writes_audio_page_and_a_separate_key(tmp_path):
    base = _system(tmp_path, "base", 0.05)
    other = _system(tmp_path, "other", 0.4)
    out, key_path = tmp_path / "test", tmp_path / "key.json"
    key = lt.build({"base": base, "other": other}, out, key_path, anchors=2)
    assert len(key["trials"]) == 5
    assert len(list((out / "audio").glob("*.wav"))) == 10
    page = (out / "index.html").read_text()
    assert "t001" in page
    # Nothing that identifies a system reaches the listener's folder.
    for name in ("base", "other", "degraded", "sv2tts"):
        assert name not in page
    assert all(
        name not in p.name
        for p in (out / "audio").iterdir()
        for name in ("base", "other")
    )
    assert not key_path.is_relative_to(out)
    assert json.loads(key_path.read_text())["trials"] == key["trials"]


def test_built_clips_of_a_trial_have_the_same_loudness(tmp_path):
    base = _system(tmp_path, "base", 0.02)
    other = _system(tmp_path, "other", 0.5)
    out = tmp_path / "test"
    lt.build({"base": base, "other": other}, out, tmp_path / "k.json")
    a, rate = sf.read(str(out / "audio" / "t001_a.wav"), dtype="float32")
    b, _ = sf.read(str(out / "audio" / "t001_b.wav"), dtype="float32")
    assert integrated_loudness(a, rate) == pytest.approx(
        integrated_loudness(b, rate), abs=0.6
    )


def test_the_page_escapes_its_text():
    page = lt.render_page(["t001"], 'Better <b>"x"</b>?', "T<i>")
    assert "<b>" not in page and "T<i>" not in page


# --- analysis ------------------------------------------------------------------------


def test_wilson_and_binomial_known_values():
    assert lt.wilson(0, 0) == (0.0, 1.0)
    low, high = lt.wilson(8, 10)
    assert low == pytest.approx(0.490, abs=0.01) and high == pytest.approx(
        0.943, abs=0.01
    )
    assert lt.binomial_two_sided(5, 10) == 1.0
    assert lt.binomial_two_sided(10, 10) == pytest.approx(2 / 1024)
    assert lt.binomial_two_sided(0, 0) == 1.0


def _key():
    trials = [
        {"id": "t001", "kind": "pair", "a": "base", "b": "new", "item": "x"},
        {"id": "t002", "kind": "pair", "a": "new", "b": "base", "item": "y"},
        {"id": "t003", "kind": "anchor", "a": "base", "b": "degraded", "item": "x"},
        {"id": "t004", "kind": "anchor", "a": "degraded", "b": "base", "item": "y"},
    ]
    return {"seed": 1, "question": "q", "trials": trials}


def _respond(tmp_path, name, choices):
    path = tmp_path / f"{name}.json"
    answers = [{"trial": f"t00{i}", "choice": c} for i, c in enumerate(choices, 1)]
    path.write_text(json.dumps({"listener": name, "answers": answers}))
    return path


def test_analyze_counts_wins_by_system_not_by_side(tmp_path):
    # t001: b = new; t002: a = new -> both pick the new system.
    paths = [_respond(tmp_path, "ann", ["b", "a", "a", "b"])]
    report = lt.analyze(_key(), paths)
    (cmp,) = report["comparisons"]
    assert cmp["systems"] == ["base", "new"]
    assert cmp["wins"] == {"base": 0, "new": 2}
    assert cmp["share_second"] == 1.0


def test_analyze_leaves_out_a_listener_who_prefers_the_damaged_copy(tmp_path):
    good = _respond(tmp_path, "good", ["b", "a", "a", "b"])
    bad = _respond(tmp_path, "bad", ["a", "b", "b", "a"])  # damaged copy both times
    report = lt.analyze(_key(), [good, bad])
    assert report["excluded_for_anchors"] == {"bad": 0.0}
    assert (report["listeners"], report["kept"]) == (2, 1)
    assert report["comparisons"][0]["wins"] == {"base": 0, "new": 2}


def test_no_preference_is_counted_apart_and_not_as_a_win(tmp_path):
    report = lt.analyze(_key(), [_respond(tmp_path, "ann", ["none", "a", "a", "b"])])
    (cmp,) = report["comparisons"]
    assert cmp["no_preference"] == 1 and cmp["wins"] == {"base": 0, "new": 1}


def test_a_listener_with_fewer_than_two_anchors_is_kept(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(
        json.dumps({"listener": "p", "answers": [{"trial": "t001", "choice": "a"}]})
    )
    assert lt.analyze(_key(), [path])["kept"] == 1


def test_analyze_rejects_bad_files(tmp_path):
    bad_trial = tmp_path / "a.json"
    bad_trial.write_text(json.dumps({"answers": [{"trial": "t999", "choice": "a"}]}))
    with pytest.raises(ValueError, match="unknown trial"):
        lt.analyze(_key(), [bad_trial])
    bad_choice = tmp_path / "b.json"
    bad_choice.write_text(json.dumps({"answers": [{"trial": "t001", "choice": "c"}]}))
    with pytest.raises(ValueError, match="bad choice"):
        lt.analyze(_key(), [bad_choice])
    one = _respond(tmp_path, "same", ["a", "a", "a", "a"])
    other_dir = tmp_path / "d"
    other_dir.mkdir()
    twin = _respond(other_dir, "same", ["a", "a", "a", "a"])
    with pytest.raises(ValueError, match="twice"):
        lt.analyze(_key(), [one, twin])


# --- command line --------------------------------------------------------------------


def test_cli_build_then_analyze(tmp_path, capsys):
    base = _system(tmp_path, "base", 0.1)
    other = _system(tmp_path, "other", 0.1)
    out, key_path = tmp_path / "t", tmp_path / "key.json"
    argv = ["build", "--system", f"base={base}", "--system", f"other={other}"]
    assert (
        lt.main(argv + ["--out", str(out), "--key", str(key_path), "--anchors", "2"])
        == 0
    )
    key = json.loads(key_path.read_text())
    answers = [
        {"trial": t["id"], "choice": "a" if t["a"] == "other" else "b"}
        for t in key["trials"]
        if t["kind"] == "pair"
    ] + [
        {"trial": t["id"], "choice": "a" if t["b"] == "degraded" else "b"}
        for t in key["trials"]
        if t["kind"] == "anchor"
    ]
    resp = tmp_path / "r.json"
    resp.write_text(json.dumps({"listener": "r", "answers": answers}))
    assert lt.main(["analyze", "--key", str(key_path), "--responses", str(resp)]) == 0
    report = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert report["comparisons"][0]["share_second"] == 1.0


@pytest.mark.parametrize("value", ["noequals", "=dir", "name=", "degraded=d"])
def test_cli_rejects_bad_system_specs(value):
    with pytest.raises(SystemExit):
        lt._parse_systems([value])


def test_cli_refuses_a_key_inside_the_shared_folder(tmp_path):
    base = _system(tmp_path, "base", 0.1)
    other = _system(tmp_path, "other", 0.1)
    out = tmp_path / "t"
    with pytest.raises(SystemExit):
        lt.main(
            [
                "build",
                "--system",
                f"base={base}",
                "--system",
                f"other={other}",
                "--out",
                str(out),
                "--key",
                str(out / "key.json"),
            ]
        )
