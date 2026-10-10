"""Score synthesized speech against the real speaker (SPEECH_QUALITY_PLAN.md Phase S0).

    python -m backend.evaluate_synthesis --data-dir <speakers/> [--groups groups.json]

``--data-dir`` holds one sub-directory per speaker with at least 3 audio files each; the
first file is the reference given to the cloner, the others are the held-out real speech
the clone is compared with. ``--groups`` maps a speaker name to a group label
(``adult_male``, ``adult_female``, ``child``, ``elderly``, ...) so results are reported per
group instead of averaged away (plan section 7.2).

Per clone it reports:

* ``secs``                    cosine between the clone's and the speaker's embeddings
* ``f0_error_semitones``      |median F0 of clone - median F0 of the real speech|
* ``f0_range_ratio``          clone F0 range / real F0 range (5th to 95th percentile)
* ``spectral_distance_db``    level-invariant long-term spectrum distance (timbre, brightness)
* ``punctuation``             for the same sentence ending in ``.``, ``?`` and ``!``: does the
                              ``?`` end higher, and does the ``!`` have more F0 range and energy

With ``--whisper-model`` (default ``small.en``; ``none`` skips it) it also synthesizes
multi-sentence stimuli and reports, per speaker:

* ``para_wer``                Whisper word error rate on plain multi-sentence paragraphs
* ``para_pause_count``        audible gaps (at least 0.2 s) inside the audio: pause structure
* ``para_pause_mean_s``       their mean length
* ``para_sec_per_word``       speaking time per word
* ``typed_wer``               word error rate on text with numbers, times, currency, symbols and
                              acronyms, where reference and transcript are both put through
                              ``clean_text`` so the comparison is of intended words

Whisper needs ``pip install faster-whisper`` (evaluation only, not a runtime dependency).

Not here yet (plan S0.1, S0.3): an encoder independent of the one that conditions the model,
predicted MOS and the emotion classifier. ``secs`` below is therefore
judged by the *same* resemblyzer encoder that conditions the synthesizer, which flatters the
model; read it as a relative number, never as an absolute one.

The metric functions are pure and unit-tested; the dataset is never committed.
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import librosa
import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg")
F0_HOP = 160  # 10 ms at 16 kHz
# Children reach 400 Hz or more, so the ceiling is well above an adult's.
F0_FMIN_HZ = 60.0
F0_FMAX_HZ = 1000.0
# A pitch statistic over fewer voiced frames than this is noise, not a measurement.
MIN_VOICED_FRAMES = 5
SILENCE_RMS = 1e-5
# The plan's gate (section 4): every group within this SECS gap of the best group.
GROUP_GAP_LIMIT = 0.05

# The expressive sentence set (plan S0.2). Each stem is spoken ending in ".", "?" and "!".
DEFAULT_SENTENCES = Path(__file__).parent / "eval_data" / "expressive_sentences.json"
EMOTIONS = ("neutral", "happy", "sad", "angry")
# A gap this long inside the audio is a pause a listener hears.
PAUSE_MIN_SECONDS = 0.2
PAUSE_TOP_DB = 35.0
Transcriber = Callable[[np.ndarray], str]

# --- Metrics (pure) ----------------------------------------------------------


def secs(a: np.ndarray, b: np.ndarray) -> float:
    """Speaker-embedding cosine similarity of two vectors (1.0 for the same direction)."""
    x = np.asarray(a, dtype=np.float64).ravel()
    y = np.asarray(b, dtype=np.float64).ravel()
    nx, ny = np.linalg.norm(x), np.linalg.norm(y)
    if x.shape != y.shape or nx == 0.0 or ny == 0.0:
        raise ValueError("embeddings must be non-zero and the same length")
    return float(np.dot(x, y) / (nx * ny))


def semitones(hz: np.ndarray, reference_hz: float = 100.0) -> np.ndarray:
    """Convert Hz to semitones above ``reference_hz`` (equal steps for equal musical intervals)."""
    return 12.0 * np.log2(np.asarray(hz, dtype=np.float64) / reference_hz)


def f0_track(y: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Per-frame fundamental frequency in Hz, ``NaN`` where the frame is unvoiced."""
    y = np.asarray(y, dtype=np.float32)
    if (
        len(y) < 2048
        or float(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) < SILENCE_RMS
    ):
        return np.full(max(len(y) // F0_HOP, 1), np.nan)
    f0, _, _ = librosa.pyin(
        y,
        fmin=F0_FMIN_HZ,
        fmax=F0_FMAX_HZ,
        sr=sr,
        frame_length=1024,
        hop_length=F0_HOP,
    )
    return np.asarray(f0, dtype=np.float64)


def _voiced(f0: np.ndarray) -> np.ndarray:
    """The voiced (finite, positive) values of an F0 track."""
    f0 = np.asarray(f0, dtype=np.float64)
    return f0[np.isfinite(f0) & (f0 > 0)]


def f0_error_semitones(real_f0: np.ndarray, clone_f0: np.ndarray) -> Optional[float]:
    """Absolute difference of the median pitch, in semitones; ``None`` if unmeasurable."""
    real, clone = _voiced(real_f0), _voiced(clone_f0)
    if len(real) < MIN_VOICED_FRAMES or len(clone) < MIN_VOICED_FRAMES:
        return None
    return float(abs(semitones(np.median(clone)) - semitones(np.median(real))))


def _f0_range(f0: np.ndarray) -> Optional[float]:
    """5th to 95th percentile pitch range in semitones; ``None`` if too few voiced frames."""
    voiced = _voiced(f0)
    if len(voiced) < MIN_VOICED_FRAMES:
        return None
    low, high = np.percentile(semitones(voiced), [5, 95])
    return float(high - low)


def f0_range_ratio(real_f0: np.ndarray, clone_f0: np.ndarray) -> Optional[float]:
    """Clone pitch range divided by the real pitch range; ``None`` if unmeasurable."""
    real, clone = _f0_range(real_f0), _f0_range(clone_f0)
    if real is None or clone is None or real < 1e-6:
        return None
    return clone / real


def rms_dbfs(y: np.ndarray) -> float:
    """RMS level in dBFS, floored at -120 for silence."""
    y = np.asarray(y, dtype=np.float64)
    rms = float(np.sqrt(np.mean(np.square(y)))) if len(y) else 0.0
    return -120.0 if rms <= 0.0 else max(20.0 * np.log10(rms), -120.0)


def long_term_spectrum_distance(
    real: np.ndarray, clone: np.ndarray, sr: int = SAMPLE_RATE
) -> Optional[float]:
    """RMS gap in dB between the two long-term mel spectra, ignoring overall level.

    Captures timbre and brightness (a child's or a deep voice's spectral tilt) without
    being fooled by one clip simply being louder. ``None`` if either signal is silent.
    """
    spectra = []
    for y in (real, clone):
        y = np.asarray(y, dtype=np.float32)
        if (
            len(y) < 1024
            or float(np.sqrt(np.mean(np.square(y, dtype=np.float64)))) < SILENCE_RMS
        ):
            return None
        mel = librosa.feature.melspectrogram(
            y=y, sr=sr, n_fft=1024, hop_length=F0_HOP, n_mels=40
        )
        db = librosa.power_to_db(mel.mean(axis=1), ref=1.0, amin=1e-10, top_db=None)
        spectra.append(db - db.mean())
    return float(np.sqrt(np.mean(np.square(spectra[0] - spectra[1]))))


def final_f0_slope(f0: np.ndarray, window_s: float = 0.3) -> Optional[float]:
    """Pitch slope, in semitones per second, over the last ``window_s`` of voiced speech.

    The window ends at the last voiced frame, so trailing silence does not hide a final
    rise. Positive means the voice ends rising (a question); ``None`` if too few voiced frames.
    """
    f0 = np.asarray(f0, dtype=np.float64)
    voiced_idx = np.flatnonzero(np.isfinite(f0) & (f0 > 0))
    if len(voiced_idx) == 0:
        return None
    hop_s = F0_HOP / SAMPLE_RATE
    end = int(voiced_idx[-1])
    start = max(0, end - int(round(window_s / hop_s)) + 1)
    idx = voiced_idx[voiced_idx >= start]
    if len(idx) < 4:
        return None
    slope, _ = np.polyfit(idx * hop_s, semitones(f0[idx]), 1)
    return float(slope)


def punctuation_contrast(
    base: np.ndarray, variant: np.ndarray, terminal: str, sr: int = SAMPLE_RATE
) -> Dict[str, Optional[float]]:
    """Compare one sentence's ``?`` or ``!`` rendering with its ``.`` rendering.

    ``terminal="?"``: ``slope_delta`` is the change in final pitch slope (semitones/s);
    ``passed`` when the question ends higher than the statement.
    ``terminal="!"``: ``range_delta`` (semitones) and ``energy_delta`` (dB); ``passed``
    when *both* are higher than the statement. ``passed`` is ``None`` when unmeasurable.
    No minimum size is imposed: the deltas are reported so S0.4 can set thresholds from data.
    """
    if terminal not in ("?", "!"):
        raise ValueError("terminal must be '?' or '!'")
    base_f0, variant_f0 = f0_track(base, sr), f0_track(variant, sr)
    if terminal == "?":
        b, v = final_f0_slope(base_f0), final_f0_slope(variant_f0)
        if b is None or v is None:
            return {"slope_delta": None, "passed": None}
        return {"slope_delta": v - b, "passed": float(v > b)}
    b_range, v_range = _f0_range(base_f0), _f0_range(variant_f0)
    energy_delta = rms_dbfs(variant) - rms_dbfs(base)
    if b_range is None or v_range is None:
        return {"range_delta": None, "energy_delta": energy_delta, "passed": None}
    range_delta = v_range - b_range
    return {
        "range_delta": range_delta,
        "energy_delta": energy_delta,
        "passed": float(range_delta > 0 and energy_delta > 0),
    }


_NON_WORD = re.compile(r"[^a-z0-9' ]+")


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation (keeping apostrophes) and collapse whitespace."""
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def _edit_distance(a: Sequence, b: Sequence) -> int:
    """Levenshtein distance between two sequences."""
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, 1):
        current = [i]
        for j, item_b in enumerate(b, 1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (item_a != item_b),
                )
            )
        previous = current
    return previous[-1]


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word-level edit distance over the reference length (case and punctuation ignored)."""
    ref = _normalize(reference).split()
    if not ref:
        raise ValueError("reference text has no words")
    return _edit_distance(ref, _normalize(hypothesis).split()) / len(ref)


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Character-level edit distance over the reference length (case and punctuation ignored)."""
    ref = _normalize(reference)
    if not ref:
        raise ValueError("reference text has no characters")
    return _edit_distance(ref, _normalize(hypothesis)) / len(ref)


def pause_profile(
    y: np.ndarray,
    sr: int = SAMPLE_RATE,
    min_gap_s: float = PAUSE_MIN_SECONDS,
    top_db: float = PAUSE_TOP_DB,
) -> List[float]:
    """Lengths in seconds, in time order, of the silent gaps *inside* the audio.

    Frames of 20 ms (10 ms hop) whose RMS is more than ``top_db`` below the loudest frame are
    silent; a run of silent frames between two voiced ones, at least ``min_gap_s`` long, is a
    pause. Leading and trailing silence are not pauses. The window is short so a gap is read
    within about 20 ms of its true length.
    """
    y = np.asarray(y, dtype=np.float32)
    if len(y) < 1024 or float(np.max(np.abs(y))) < SILENCE_RMS:
        return []
    rms = librosa.feature.rms(y=y, frame_length=320, hop_length=F0_HOP, center=True)[0]
    level_db = 20.0 * np.log10(np.maximum(rms, 1e-10) / max(float(rms.max()), 1e-10))
    silent = level_db < -top_db
    voiced_idx = np.flatnonzero(~silent)
    if len(voiced_idx) < 2:
        return []
    hop_s = F0_HOP / sr
    gaps: List[float] = []
    run = 0
    for frame_is_silent in silent[voiced_idx[0] : voiced_idx[-1] + 1]:
        if frame_is_silent:
            run += 1
        else:
            if run * hop_s >= min_gap_s:
                gaps.append(run * hop_s)
            run = 0
    return gaps


def bootstrap_ci(
    values: Sequence[float], n_boot: int = 2000, seed: int = 0, alpha: float = 0.05
) -> Tuple[float, float, float]:
    """Mean and a percentile bootstrap (1 - alpha) interval; (nan, nan, nan) when empty."""
    x = np.asarray(values, dtype=np.float64)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    low, high = np.percentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(x.mean()), float(low), float(high)


def group_report(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    gap_limit: float = GROUP_GAP_LIMIT,
) -> Dict[str, object]:
    """Mean and interval of ``metric`` per ``group``, plus the best-to-worst gap.

    A model that is good on average but poor for one kind of voice must fail the plan's
    gate, so the gap between the best and worst group is reported next to the means.
    """
    by_group: Dict[str, List[float]] = {}
    for row in rows:
        value = row.get(metric)
        if value is not None:
            by_group.setdefault(str(row.get("group", "ungrouped")), []).append(
                float(value)
            )
    groups = {}
    for name, values in sorted(by_group.items()):
        mean, low, high = bootstrap_ci(values)
        groups[name] = {"n": len(values), "mean": mean, "ci_low": low, "ci_high": high}
    means = [g["mean"] for g in groups.values()]
    gap = float(max(means) - min(means)) if means else None
    return {
        "groups": groups,
        "best_to_worst_gap": gap,
        "within_gap_limit": None if gap is None else bool(gap <= gap_limit),
    }


# --- Study (needs real speech and the model weights) -------------------------


def load_dataset(data_dir: Path) -> Dict[str, List[str]]:
    """Return ``{speaker: sorted audio paths}`` for speakers with at least 3 files."""
    speakers: Dict[str, List[str]] = {}
    for speaker_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        files = sorted(
            str(f) for f in speaker_dir.iterdir() if f.suffix.lower() in AUDIO_SUFFIXES
        )
        if len(files) >= 3:
            speakers[speaker_dir.name] = files
    if not speakers:
        raise SystemExit("need at least one speaker directory with 3 or more files")
    return speakers


def load_sentences(path: Path = DEFAULT_SENTENCES) -> List[Dict[str, str]]:
    """Read the expressive sentence set: ``id``, ``stem`` and one sentence per emotion."""
    data = json.loads(path.read_text(encoding="utf-8"))
    sentences = data.get("sentences") if isinstance(data, dict) else None
    needed = {"id", "stem", *EMOTIONS}
    if not sentences or any(needed - set(item) for item in sentences):
        raise SystemExit(f"{path} must list sentences with keys {sorted(needed)}")
    return sentences


def select_speakers(
    dataset: Mapping[str, Sequence[str]], groups: Mapping[str, str], count: int
) -> List[str]:
    """Choose ``count`` speakers, alternating between groups so a small run stays balanced.

    Within a group speakers are taken in sorted order; with a single group (or none given)
    this is just the first ``count`` in sorted order.
    """
    by_group: Dict[str, List[str]] = {}
    for speaker in sorted(dataset):
        by_group.setdefault(groups.get(speaker, "ungrouped"), []).append(speaker)
    queues = [by_group[g] for g in sorted(by_group)]
    chosen: List[str] = []
    while len(chosen) < count and any(queues):
        for queue in queues:
            if queue and len(chosen) < count:
                chosen.append(queue.pop(0))
    return chosen


def load_stimuli(path: Path, key: str) -> List[Dict[str, str]]:
    """Read the ``paragraphs`` or ``typed`` stimulus list (``id`` and ``text``) from the fixture."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get(key) if isinstance(data, dict) else None
    if not items or any({"id", "text"} - set(item) for item in items):
        raise SystemExit(f"{path} must list {key!r} items with keys 'id' and 'text'")
    return items


def make_whisper_transcriber(model_name: str = "small.en") -> Transcriber:
    """Return a function that transcribes 16 kHz mono audio with faster-whisper (CPU, int8)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit(
            "faster-whisper is required for word error rate: pip install faster-whisper "
            "(evaluation only), or pass --whisper-model none"
        )
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def transcribe(audio: np.ndarray) -> str:
        segments, _ = model.transcribe(
            np.asarray(audio, dtype=np.float32),
            language="en",
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    return transcribe


def load_groups(path: Optional[Path]) -> Dict[str, str]:
    """Read a ``{speaker: group}`` JSON map; an empty map when no file is given."""
    if path is None:
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("--groups must be a JSON object of speaker to group")
    return {str(k): str(v) for k, v in data.items()}


def _synthesize(
    text: str, embedding: np.ndarray, speaker: str, seed: int
) -> np.ndarray:
    """Run the production pipeline for ``text``; returns the waveform and removes the file."""
    import asyncio

    import soundfile as sf
    import torch

    from backend.services.tts_pipeline import run_inference_pipeline

    torch.manual_seed(seed)
    out_path, _ = asyncio.run(
        run_inference_pipeline(text, embedding, f"study-{speaker}")
    )
    try:
        wav, _ = sf.read(out_path, dtype="float32")
    finally:
        os.remove(out_path)
    return np.asarray(wav, dtype=np.float32)


def reference_embedding(encoder, reference: str) -> np.ndarray:
    """Embed the reference clip the way an upload does (production preprocessing)."""
    from backend.services.audio_processing import preprocess_audio

    return encoder.embed_utterance(np.asarray(preprocess_audio(reference), np.float32))


def evaluate_speaker(
    encoder,
    speaker: str,
    files: Sequence[str],
    group: str,
    index: int,
    seed: int,
    stems: Sequence[str],
) -> Dict[str, object]:
    """Clone one speaker from their first clip and score it against their other clips."""
    reference, held_out = files[0], files[1:]
    embedding = reference_embedding(encoder, reference)
    real = [librosa.load(p, sr=SAMPLE_RATE)[0] for p in held_out]
    target = np.mean(
        [encoder.embed_utterance(np.asarray(y, np.float32)) for y in real], axis=0
    )
    real_f0 = np.concatenate([f0_track(y) for y in real])
    real_audio = np.concatenate(real)

    row: Dict[str, object] = {"speaker": speaker, "group": group}
    base_seed = seed + 1000 * index
    clone = _synthesize(stems[0] + ".", embedding, speaker, base_seed)
    row["secs"] = secs(encoder.embed_utterance(clone), target)
    clone_f0 = f0_track(clone)
    row["f0_error_semitones"] = f0_error_semitones(real_f0, clone_f0)
    row["f0_range_ratio"] = f0_range_ratio(real_f0, clone_f0)
    row["spectral_distance_db"] = long_term_spectrum_distance(real_audio, clone)

    # The three renderings of one sentence share a seed, so only the punctuation differs.
    contrast: Dict[str, List[float]] = {"?": [], "!": []}
    for k, sentence in enumerate(stems):
        seed_k = base_seed + 1 + k
        base = _synthesize(sentence + ".", embedding, speaker, seed_k)
        for terminal in ("?", "!"):
            variant = _synthesize(sentence + terminal, embedding, speaker, seed_k)
            passed = punctuation_contrast(base, variant, terminal)["passed"]
            if passed is not None:
                contrast[terminal].append(passed)
    row["question_rise_rate"] = float(np.mean(contrast["?"])) if contrast["?"] else None
    row["exclamation_lift_rate"] = (
        float(np.mean(contrast["!"])) if contrast["!"] else None
    )
    return row


def _mean(values: Sequence[float]) -> Optional[float]:
    """Mean of ``values``, or ``None`` when there are none."""
    return float(np.mean(values)) if values else None


def evaluate_stimuli(
    embedding: np.ndarray,
    speaker: str,
    seed: int,
    paragraphs: Sequence[Mapping[str, str]],
    typed: Sequence[Mapping[str, str]],
    transcribe: Optional[Transcriber],
) -> Dict[str, Optional[float]]:
    """Synthesize the multi-sentence and typed stimuli for one speaker and score them.

    Paragraph word error rate compares the transcript with the text itself. Typed text is
    scored on intended words: both the text and the transcript go through ``clean_text``,
    so ``10:30 PM`` and a transcript of ``10:30 p.m.`` both become ``ten thirty pee em``.
    Pause metrics need no transcriber.
    """
    from backend.services.text_normalization import clean_text

    wers: List[float] = []
    sec_per_word: List[float] = []
    pause_counts: List[float] = []
    pause_lengths: List[float] = []
    for k, item in enumerate(paragraphs):
        audio = _synthesize(item["text"], embedding, speaker, seed + 500 + k)
        sec_per_word.append(len(audio) / SAMPLE_RATE / len(item["text"].split()))
        gaps = pause_profile(audio)
        pause_counts.append(float(len(gaps)))
        pause_lengths.extend(gaps)
        if transcribe is not None:
            wers.append(word_error_rate(item["text"], transcribe(audio)))
    typed_wers: List[float] = []
    if transcribe is not None:
        for k, item in enumerate(typed):
            audio = _synthesize(item["text"], embedding, speaker, seed + 700 + k)
            typed_wers.append(
                word_error_rate(clean_text(item["text"]), clean_text(transcribe(audio)))
            )
    return {
        "para_wer": _mean(wers),
        "para_sec_per_word": _mean(sec_per_word),
        "para_pause_count": _mean(pause_counts),
        "para_pause_mean_s": _mean(pause_lengths),
        "typed_wer": _mean(typed_wers),
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Run the study and print a summary; write the full results as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--groups", type=Path, default=None)
    parser.add_argument("--speakers", type=int, default=20, help="speakers to clone")
    parser.add_argument(
        "--stems", type=int, default=5, help="sentence stems for the punctuation test"
    )
    parser.add_argument("--sentences", type=Path, default=DEFAULT_SENTENCES)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument(
        "--paragraphs", type=int, default=4, help="paragraph stimuli per speaker"
    )
    parser.add_argument(
        "--typed", type=int, default=4, help="typed-text stimuli per speaker"
    )
    parser.add_argument(
        "--whisper-model",
        default="small.en",
        help="faster-whisper model for word error rate, or 'none' to skip it",
    )
    parser.add_argument(
        "--skip-single",
        action="store_true",
        help="skip the single-sentence study and run only the multi-sentence stimuli",
    )
    parser.add_argument("--out", type=Path, default=Path("synthesis_study.json"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dataset = load_dataset(args.data_dir)
    groups = load_groups(args.groups)
    stems = [item["stem"] for item in load_sentences(args.sentences)][: args.stems]
    if not stems:
        raise SystemExit("--stems must be at least 1")

    from resemblyzer import VoiceEncoder

    from backend.services.tts_pipeline import load_models

    load_models("cpu")
    encoder = VoiceEncoder("cpu")

    paragraphs = load_stimuli(args.sentences, "paragraphs")[: args.paragraphs]
    typed = load_stimuli(args.sentences, "typed")[: args.typed]
    transcribe = (
        None
        if args.whisper_model.lower() == "none"
        else make_whisper_transcriber(args.whisper_model)
    )
    chosen = select_speakers(dataset, groups, args.speakers)

    rows = []
    for n, speaker in enumerate(chosen):
        files, group = dataset[speaker], groups.get(speaker, "ungrouped")
        if args.skip_single:
            row: Dict[str, object] = {"speaker": speaker, "group": group}
            embedding = reference_embedding(encoder, files[0])
        else:
            row = evaluate_speaker(encoder, speaker, files, group, n, args.seed, stems)
            embedding = reference_embedding(encoder, files[0])
        row.update(
            evaluate_stimuli(
                embedding, speaker, args.seed + 1000 * n, paragraphs, typed, transcribe
            )
        )
        rows.append(row)
        logger.info("scored speaker %d/%d (%s)", n + 1, len(chosen), speaker)

    metrics = (
        "secs",
        "f0_error_semitones",
        "f0_range_ratio",
        "spectral_distance_db",
        "question_rise_rate",
        "exclamation_lift_rate",
        "para_wer",
        "para_sec_per_word",
        "para_pause_count",
        "para_pause_mean_s",
        "typed_wer",
    )
    report = {
        "judge": "resemblyzer (same encoder as the model: not independent)",
        "asr": None if transcribe is None else f"faster-whisper {args.whisper_model}",
        "speakers": len(rows),
        "rows": rows,
        "per_group": {metric: group_report(rows, metric) for metric in metrics},
    }
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["per_group"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
