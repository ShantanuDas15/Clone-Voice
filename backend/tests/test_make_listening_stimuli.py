"""Generating listening-test stimuli from pipeline variants (SPEECH_QUALITY_PLAN.md S0.6)."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from backend import make_listening_stimuli as ms
from backend.core.config import DEFAULT_TTS_PAUSE_SECONDS, settings


def _settings():
    return SimpleNamespace(
        TTS_BEST_OF_N=1,
        OUTPUT_LIMITER_MAX_REDUCTION_DB=6.0,
        OUTPUT_NORMALIZE_ENABLED=True,
        TTS_PAUSE_SECONDS={"statement": 0.4, "comma": 0.1},
        TTS_ENGINE="sv2tts",
    )


def test_the_shipped_variants_file_is_valid_against_the_real_settings():
    variants = ms.load_variants()
    assert next(iter(variants)) == "current" and variants["current"] == {}
    for overrides in variants.values():
        ms.check_overrides(settings, overrides)
    flat = variants["flat_pause"]["TTS_PAUSE_SECONDS"]
    assert set(flat) == set(DEFAULT_TTS_PAUSE_SECONDS)


@pytest.mark.parametrize(
    "overrides",
    [
        {"NOT_A_SETTING": 1},
        {"TTS_BEST_OF_N": "three"},
        {"OUTPUT_NORMALIZE_ENABLED": 1},
        {"TTS_PAUSE_SECONDS": {"sentence": 0.4}},
        {"TTS_PAUSE_SECONDS": 0.4},
        {"TTS_ENGINE": 3},
        {"__class__": 1},
    ],
)
def test_bad_overrides_are_refused(overrides):
    with pytest.raises(ValueError):
        ms.check_overrides(_settings(), overrides)


def test_overrides_apply_inside_the_block_and_are_restored_even_on_error():
    s = _settings()
    with pytest.raises(RuntimeError):
        with ms.applied(
            s, {"TTS_BEST_OF_N": 3, "TTS_PAUSE_SECONDS": {"statement": 0.9}}
        ):
            assert s.TTS_BEST_OF_N == 3
            assert s.TTS_PAUSE_SECONDS == {"statement": 0.9, "comma": 0.1}  # merged
            raise RuntimeError
    assert s.TTS_BEST_OF_N == 1
    assert s.TTS_PAUSE_SECONDS == {"statement": 0.4, "comma": 0.1}


def test_a_bad_override_changes_nothing():
    s = _settings()
    with pytest.raises(ValueError):
        with ms.applied(s, {"TTS_BEST_OF_N": 3, "NOPE": 1}):
            pass
    assert s.TTS_BEST_OF_N == 1


@pytest.mark.parametrize(
    "variants",
    [{"only": {}}, {"a": {}, "../b": {}}, {"a": {}, "degraded": {}}, {"a": {}, "b": 3}],
)
def test_load_variants_rejects_bad_files(tmp_path, variants):
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"variants": variants}))
    with pytest.raises(SystemExit):
        ms.load_variants(path)


def test_generate_writes_the_layout_with_paired_seeds_and_restores_settings(tmp_path):
    s = _settings()
    calls = []

    def fake(text, embedding, speaker, seed):
        calls.append((s.TTS_BEST_OF_N, text, speaker, seed))
        return np.full(1600, 0.1, np.float32), 16000

    variants = {"current": {}, "best": {"TTS_BEST_OF_N": 3}}
    speakers = {"spk1": np.zeros(256), "spk2": np.zeros(256)}
    made = ms.generate(s, variants, speakers, ["One.", "Two."], tmp_path, 7, fake)
    assert made == 8
    for variant in variants:
        for speaker in speakers:
            for i in (0, 1):
                data, rate = sf.read(str(tmp_path / variant / speaker / f"{i}.wav"))
                assert rate == 16000 and len(data) == 1600
    # The same speaker and text get the same seed in every variant; only the setting differs.
    by_variant = {}
    for best_of, text, speaker, seed in calls:
        by_variant.setdefault(best_of, []).append((text, speaker, seed))
    assert by_variant[1] == by_variant[3]
    assert s.TTS_BEST_OF_N == 1


def test_generate_checks_every_variant_before_synthesizing_anything(tmp_path):
    called = []
    with pytest.raises(ValueError):
        ms.generate(
            _settings(),
            {"current": {}, "bad": {"NOPE": 1}},
            {"s": np.zeros(256)},
            ["Hi."],
            tmp_path,
            1,
            lambda *a: called.append(a) or (np.zeros(10, np.float32), 16000),
        )
    assert not called and not list(tmp_path.iterdir())


def test_the_output_feeds_the_listening_test_builder(tmp_path):
    from backend import listening_test as lt

    def fake(text, embedding, speaker, seed):
        rng = np.random.default_rng(seed)
        return (0.1 * rng.standard_normal(16000)).astype(np.float32), 16000

    ms.generate(
        _settings(),
        {"a": {}, "b": {}},
        {"s": np.zeros(256)},
        ["x", "y"],
        tmp_path / "o",
        1,
        fake,
    )
    key = lt.build(
        {"a": tmp_path / "o" / "a", "b": tmp_path / "o" / "b"},
        tmp_path / "t",
        tmp_path / "key.json",
    )
    assert len(key["trials"]) == 2
