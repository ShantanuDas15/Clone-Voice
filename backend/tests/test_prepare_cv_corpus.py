"""The Common Voice corpus builder (SPEECH_QUALITY_PLAN.md S0.2b), on synthetic clips only."""

import json

import numpy as np
import pytest
import soundfile as sf

from backend import prepare_cv_corpus as cv
from backend.tests.test_evaluate_synthesis import tone

SR = cv.SAMPLE_RATE

# --- age groups and pseudonyms -----------------------------------------------


@pytest.mark.parametrize(
    "age,expected",
    [
        ("sixties", "elderly"),
        ("Seventies", "elderly"),
        (" eighties ", "elderly"),
        ("twenties", "cv_adult_control"),
        ("fourties", "cv_adult_control"),
        ("forties", "cv_adult_control"),
        ("teens", None),
        ("fifties", None),
        ("", None),
        (None, None),
    ],
)
def test_age_bands_map_to_study_groups(age, expected):
    assert cv.age_group(age) == expected


def test_speaker_hash_is_stable_short_and_hides_the_id():
    first = cv.speaker_hash("abc123")
    assert first == cv.speaker_hash("abc123")
    assert first != cv.speaker_hash("abc124")
    assert len(first) == 12 and "abc123" not in first


# --- planning one speaker ----------------------------------------------------


def _clips(*seconds):
    return [(f"c{i:02d}.mp3", s) for i, s in enumerate(seconds)]


def test_plan_pools_clips_until_ten_seconds_then_takes_five_held_out():
    ref, held = cv.plan_speaker(_clips(4, 4, 4, 5, 5, 5, 5, 5))
    assert ref == ["c00.mp3", "c01.mp3", "c02.mp3"]
    assert held == ["c03.mp3", "c04.mp3", "c05.mp3", "c06.mp3", "c07.mp3"]


def test_plan_reference_may_be_a_single_long_clip():
    ref, held = cv.plan_speaker(_clips(12, 4, 4, 4, 4, 4))
    assert ref == ["c00.mp3"] and len(held) == 5


def test_plan_counts_the_join_silence():
    # 5 + 0.25 + 4.8 = 10.05 s reaches the minimum with two clips
    ref, _ = cv.plan_speaker(_clips(5, 4.8, 4, 4, 4, 4, 4))
    assert ref == ["c00.mp3", "c01.mp3"]


def test_plan_rejects_a_speaker_with_too_little_audio():
    assert cv.plan_speaker(_clips(2, 2, 2, 2)) is None


def test_plan_rejects_a_reference_that_would_pass_thirty_seconds():
    assert cv.plan_speaker(_clips(35, 4, 4, 4, 4, 4)) is None
    assert cv.plan_speaker(_clips(9.5, 9.5, 9.5, 9.5, 4, 4, 4, 4, 4)) is not None


def test_plan_needs_five_held_out_clips_of_three_seconds_or_more():
    assert cv.plan_speaker(_clips(11, 4, 4, 4, 4)) is None
    assert cv.plan_speaker(_clips(11, 4, 4, 4, 2.5, 2.5, 4)) is None
    assert cv.plan_speaker(_clips(11, 4, 4, 21, 4, 4, 4)) is not None


def test_plan_never_uses_a_clip_twice():
    ref, held = cv.plan_speaker(_clips(4, 4, 4, 4, 4, 4, 4, 4))
    assert not set(ref) & set(held)


# --- the whole builder -------------------------------------------------------


def _make_cv(tmp_path, speakers):
    """Write a fake Common Voice folder; ``speakers`` maps client_id -> (age, [clip seconds])."""
    cv_dir = tmp_path / "cv"
    (cv_dir / "clips").mkdir(parents=True)
    rows = ["client_id\tpath\tsentence\tage\tgender"]
    for client_id, (age, durations) in speakers.items():
        for i, seconds in enumerate(durations):
            name = f"{client_id}_{i:02d}.wav"
            sf.write(
                cv_dir / "clips" / name,
                tone(150.0 + 7 * i, 170.0, seconds=seconds, amp=0.3),
                SR,
                subtype="PCM_16",
            )
            rows.append(f"{client_id}\t{name}\tsome private text\t{age}\tmale")
    (cv_dir / "validated.tsv").write_text("\n".join(rows) + "\n")
    return cv_dir


FULL = [4.0] * 9


def test_builder_writes_both_groups_hashed_with_the_expected_layout(tmp_path):
    cv_dir = _make_cv(
        tmp_path,
        {
            "old1": ("seventies", FULL),
            "old2": ("sixties", FULL),
            "young1": ("twenties", FULL),
            "young2": ("fourties", FULL),
            "teen": ("teens", FULL),
            "noage": ("", FULL),
        },
    )
    out = tmp_path / "out"

    manifest = cv.write_corpus(cv_dir, out, per_group=2)

    groups = json.loads((out / "groups.json").read_text())
    assert sorted(groups.values()) == ["cv_adult_control"] * 2 + ["elderly"] * 2
    assert set(groups) == {
        cv.speaker_hash(c) for c in ("old1", "old2", "young1", "young2")
    }
    speaker = next(iter(groups))
    files = sorted(p.name for p in (out / speaker).iterdir())
    assert files == ["0_ref.wav"] + [f"1_{i}.wav" for i in range(1, 6)]
    reference, rate = sf.read(out / speaker / "0_ref.wav")
    assert rate == SR and 10.0 <= len(reference) / SR <= 30.0
    held, _ = sf.read(out / speaker / "1_1.wav")
    assert 3.0 <= len(held) / SR <= 20.0
    assert manifest["source"].startswith("Mozilla Common Voice")


def test_builder_leaks_no_client_id_or_sentence_text(tmp_path):
    cv_dir = _make_cv(
        tmp_path, {"old1": ("sixties", FULL), "young1": ("twenties", FULL)}
    )
    out = tmp_path / "out"
    cv.write_corpus(cv_dir, out, per_group=1)

    written = "".join(p.read_text() for p in out.rglob("*.json")) + " ".join(
        str(p) for p in out.rglob("*")
    )
    assert "old1" not in written and "young1" not in written
    assert "some private text" not in written


def test_builder_resamples_to_16_khz(tmp_path):
    cv_dir = _make_cv(tmp_path, {"old1": ("sixties", FULL)})
    for path in (cv_dir / "clips").glob("*.wav"):
        samples, _ = sf.read(path)
        sf.write(
            path, np.repeat(samples, 3), 48000, subtype="PCM_16"
        )  # same length, 48 kHz
    out = tmp_path / "out"

    cv.write_corpus(cv_dir, out, per_group=1)

    speaker = cv.speaker_hash("old1")
    reference, rate = sf.read(out / speaker / "0_ref.wav")
    assert rate == SR and 10.0 <= len(reference) / SR <= 30.0


def test_builder_skips_unqualified_speakers_and_warns_when_short(tmp_path, caplog):
    cv_dir = _make_cv(
        tmp_path,
        {
            "old1": ("sixties", FULL),
            "oldshort": ("sixties", [4.0, 4.0]),
            "young1": ("twenties", FULL),
        },
    )
    out = tmp_path / "out"

    with caplog.at_level("WARNING"):
        cv.write_corpus(cv_dir, out, per_group=2)

    groups = json.loads((out / "groups.json").read_text())
    assert cv.speaker_hash("oldshort") not in groups
    assert "group elderly: only 1 of 2" in caplog.text


def test_builder_is_deterministic(tmp_path):
    speakers = {f"old{i}": ("seventies", FULL) for i in range(6)}
    speakers.update({f"young{i}": ("thirties", FULL) for i in range(6)})
    cv_dir = _make_cv(tmp_path, speakers)

    cv.write_corpus(cv_dir, tmp_path / "a", per_group=3)
    cv.write_corpus(cv_dir, tmp_path / "b", per_group=3)

    assert (tmp_path / "a" / "groups.json").read_text() == (
        tmp_path / "b" / "groups.json"
    ).read_text()


def test_main_rejects_a_missing_dataset_and_a_bad_count(tmp_path):
    with pytest.raises(SystemExit, match="no validated.tsv"):
        cv.main(["--cv-dir", str(tmp_path), "--out", str(tmp_path / "o")])
    cv_dir = _make_cv(tmp_path, {"old1": ("sixties", FULL)})
    with pytest.raises(SystemExit, match="per-group"):
        cv.main(
            ["--cv-dir", str(cv_dir), "--out", str(tmp_path / "o"), "--per-group", "0"]
        )


def test_main_prints_a_summary(tmp_path, capsys):
    cv_dir = _make_cv(
        tmp_path, {"old1": ("sixties", FULL), "young1": ("twenties", FULL)}
    )

    assert (
        cv.main(
            ["--cv-dir", str(cv_dir), "--out", str(tmp_path / "o"), "--per-group", "1"]
        )
        == 0
    )

    summary = json.loads(capsys.readouterr().out)
    assert summary["per_group"] == {"cv_adult_control": 1, "elderly": 1}


@pytest.mark.skipif(
    "MP3" not in sf.available_formats(), reason="libsndfile has no mp3 support"
)
def test_builder_reads_real_mp3_clips_and_the_study_loader_accepts_the_output(tmp_path):
    from backend import evaluate_synthesis as es

    cv_dir = tmp_path / "cv"
    (cv_dir / "clips").mkdir(parents=True)
    rows = ["client_id\tpath\tsentence\tage"]
    for i in range(9):
        name = f"o1_{i}.mp3"
        sf.write(
            cv_dir / "clips" / name,
            tone(140.0 + 10 * i, seconds=4.2),
            SR,
            format="MP3",
        )
        rows.append(f"o1\t{name}\tx\tseventies")
    (cv_dir / "validated.tsv").write_text("\n".join(rows) + "\n")
    out = tmp_path / "out"

    cv.write_corpus(cv_dir, out, per_group=1)

    data = es.load_dataset(out)
    groups = es.load_groups(out / "groups.json")
    assert [len(files) for files in data.values()] == [6]
    assert set(groups.values()) == {"elderly"}


def test_a_release_split_into_train_dev_test_is_read_together(tmp_path):
    cv_dir = _make_cv(
        tmp_path, {"old1": ("sixties", FULL), "adult1": ("thirties", FULL)}
    )
    lines = (cv_dir / "validated.tsv").read_text().splitlines()
    header, rows = lines[0], lines[1:]
    (cv_dir / "validated.tsv").unlink()
    for name, chunk in (("train", rows[:9]), ("dev", rows[9:]), ("test", [])):
        (cv_dir / f"{name}.tsv").write_text("\n".join([header, *chunk]) + "\n")

    assert [p.name for p in cv.tsv_files(cv_dir)] == [
        "train.tsv",
        "dev.tsv",
        "test.tsv",
    ]
    by_group = cv.read_speakers(cv.tsv_files(cv_dir))
    assert (
        set(by_group["elderly"]) == {"old1"} and len(by_group["elderly"]["old1"]) == 9
    )
    assert set(by_group["cv_adult_control"]) == {"adult1"}


def test_a_quote_mark_in_a_sentence_does_not_swallow_the_next_rows(tmp_path):
    tsv = tmp_path / "validated.tsv"
    tsv.write_text(
        "client_id\tpath\tsentence\tage\tgender\n"
        'a\ta1.mp3\t"He said hello\tsixties\tmale\n'
        "b\tb1.mp3\tplain\ttwenties\tmale\n"
    )
    by_group = cv.read_speakers(tsv)
    assert set(by_group["elderly"]) == {"a"}
    assert set(by_group["cv_adult_control"]) == {"b"}
