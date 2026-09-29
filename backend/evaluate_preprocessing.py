"""Compare upload preprocessing pipelines on real speech (HARDENING_PLAN.md Pass 1 §4.10).

    python -m backend.evaluate_preprocessing --data-dir <speakers/> [--clone N]

``--data-dir`` holds one sub-directory per speaker, each with that speaker's
audio files (at least 3 each; 20 speakers x 8 utterances is a good size).

The upload path (``audio_processing.preprocess_audio``) trims with librosa and
peak-normalises to full scale, then feeds the encoder directly. The encoder's
reference preprocessing (resemblyzer's ``preprocess_wav``) instead normalises to
-30 dBFS and removes long pauses with a voice-activity detector. This tool
measures whether that difference matters, for five pipelines:

* ``current``        what uploads use today
* ``resemblyzer``    resemblyzer's own ``preprocess_wav``
* ``current+vad``    ``current`` then resemblyzer's long-pause trimming
* ``trim+level``     librosa trim, then -30 dBFS in both directions (no peak norm)
* ``trim+level+vad`` the above, then long-pause trimming

and three questions: do embeddings still separate speakers (equal error rate,
d-prime, with a bootstrap over speakers); do they stay stable under bad
recordings (gain, clipping, noise, telephone band, long pauses); and, with
``--clone``, is the *cloned voice* closer to the real speaker.

The metric functions are pure and unit-tested; the dataset is never committed.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
AUDIO_SUFFIXES = (".wav", ".flac", ".mp3", ".ogg")

# --- Metrics (pure) ----------------------------------------------------------


def verification_scores(
    embeddings: np.ndarray, labels: Sequence[str]
) -> Tuple[np.ndarray, np.ndarray]:
    """Cosine scores of every same-speaker pair and every different-speaker pair.

    Embeddings are L2-normalised first, so the dot product is the cosine.
    """
    x = np.asarray(embeddings, dtype=np.float64)
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    sims = x @ x.T
    y = np.asarray(labels)
    same_mask = y[:, None] == y[None, :]
    upper = np.triu(np.ones_like(same_mask, dtype=bool), k=1)
    return sims[same_mask & upper], sims[~same_mask & upper]


def equal_error_rate(same: np.ndarray, diff: np.ndarray) -> float:
    """The error rate at the threshold where false accepts equal false rejects."""
    thresholds = np.unique(np.concatenate([same, diff]))
    # Sorted once, each threshold is then a binary search (O(n log n) overall).
    false_reject = np.searchsorted(np.sort(same), thresholds, side="left") / len(same)
    false_accept = 1.0 - np.searchsorted(np.sort(diff), thresholds, side="left") / len(
        diff
    )
    best = int(np.argmin(np.abs(false_reject - false_accept)))
    return float((false_reject[best] + false_accept[best]) / 2.0)


def d_prime(same: np.ndarray, diff: np.ndarray) -> float:
    """Separation of the two score distributions, in pooled standard deviations."""
    pooled = np.sqrt((np.var(same) + np.var(diff)) / 2.0)
    return float((np.mean(same) - np.mean(diff)) / pooled) if pooled > 0 else 0.0


def bootstrap_eer(
    embeddings: np.ndarray,
    labels: Sequence[str],
    rounds: int = 200,
    seed: int = 0,
) -> Tuple[float, float]:
    """95% interval of the EER, resampling whole speakers with replacement.

    A speaker drawn twice contributes two copies of the same utterances. Pairs
    between two copies of one speaker are dropped (they are neither a fair
    same-speaker nor different-speaker trial); pairs inside one copy are
    same-speaker trials, pairs across different speakers are different-speaker
    trials.
    """
    x = np.asarray(embeddings, dtype=np.float64)
    x = x / np.linalg.norm(x, axis=1, keepdims=True)
    sims = x @ x.T
    y = np.asarray(labels)
    speakers = np.unique(y)
    members = {s: np.where(y == s)[0] for s in speakers}
    rng = np.random.default_rng(seed)
    values: List[float] = []
    for _ in range(rounds):
        picked = rng.choice(speakers, size=len(speakers), replace=True)
        idx = np.concatenate([members[s] for s in picked])
        draw = np.concatenate(
            [np.full(len(members[s]), n) for n, s in enumerate(picked)]
        )
        orig = y[idx]
        sub = sims[np.ix_(idx, idx)]
        upper = np.triu(np.ones_like(sub, dtype=bool), k=1)
        same = (draw[:, None] == draw[None, :]) & upper
        diff = (orig[:, None] != orig[None, :]) & upper
        if same.any() and diff.any():
            values.append(equal_error_rate(sub[same], sub[diff]))
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


# --- Degradations (pure) -----------------------------------------------------


def gain(y: np.ndarray, factor: float) -> np.ndarray:
    """Scale the level, clipping at full scale like a real converter."""
    return np.clip(y * factor, -1.0, 1.0).astype(np.float32)


def add_noise(y: np.ndarray, snr_db: float, seed: int = 0) -> np.ndarray:
    """Add white noise at the given signal-to-noise ratio."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(len(y))
    scale = np.sqrt(np.mean(y**2) / (10 ** (snr_db / 10))) / np.sqrt(np.mean(noise**2))
    return np.clip(y + scale * noise, -1.0, 1.0).astype(np.float32)


def telephone_band(y: np.ndarray) -> np.ndarray:
    """Band-limit to 4 kHz by a round trip through 8 kHz."""
    low = librosa.resample(y, orig_sr=SAMPLE_RATE, target_sr=8000)
    return librosa.resample(low, orig_sr=8000, target_sr=SAMPLE_RATE).astype(np.float32)


def pad_and_pauses(
    y: np.ndarray, edge_s: float = 3.0, pause_s: float = 1.5
) -> np.ndarray:
    """Add leading/trailing silence and a long pause in the middle."""
    edge = np.zeros(int(edge_s * SAMPLE_RATE), dtype=np.float32)
    pause = np.zeros(int(pause_s * SAMPLE_RATE), dtype=np.float32)
    mid = len(y) // 2
    return np.concatenate([edge, y[:mid], pause, y[mid:], edge]).astype(np.float32)


DEGRADATIONS: Dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "quiet (x0.03)": lambda y: gain(y, 0.03),
    "loud, clipped (x8)": lambda y: gain(y, 8.0),
    "noise (15 dB SNR)": lambda y: add_noise(y, 15.0),
    "noise (5 dB SNR)": lambda y: add_noise(y, 5.0),
    "telephone band": telephone_band,
    "long pauses and padding": pad_and_pauses,
}

# --- Pipelines ---------------------------------------------------------------


def _trim_only(path: str) -> np.ndarray:
    """Load at 16 kHz and trim silence exactly as `preprocess_audio` does, but
    keep the recording's own level (no peak normalisation)."""
    y, _ = librosa.load(path, sr=SAMPLE_RATE)
    trimmed, _ = librosa.effects.trim(y, top_db=30)
    return trimmed


def _raw(path: str) -> np.ndarray:
    """Load at 16 kHz with no trimming and no level change."""
    y, _ = librosa.load(path, sr=SAMPLE_RATE)
    return y


def _pipelines() -> Dict[str, Callable[[str], np.ndarray]]:
    """The preprocessing pipelines under test, each taking a file path.

    ``normalize_volume(..., increase_only=True)`` (what resemblyzer uses) never
    turns a loud clip down, so applied after peak normalisation it changes
    nothing; the level variants therefore start from the un-normalised audio.
    """
    from resemblyzer.audio import normalize_volume, preprocess_wav, trim_long_silences
    from resemblyzer.hparams import audio_norm_target_dBFS as target

    from backend.services.audio_processing import preprocess_audio

    return {
        "current": preprocess_audio,
        "resemblyzer": lambda p: preprocess_wav(p),
        "current+vad": lambda p: trim_long_silences(preprocess_audio(p)),
        "trim+level": lambda p: normalize_volume(_trim_only(p), target),
        "trim+level+vad": lambda p: trim_long_silences(
            normalize_volume(_trim_only(p), target)
        ),
        # Ablations of resemblyzer's own pipeline (increase-only level, then
        # pause trimming, no librosa trim), to find which part matters.
        "vad-only": lambda p: trim_long_silences(_raw(p)),
        "level-only": lambda p: normalize_volume(_raw(p), target, increase_only=True),
        "trim+level(inc)": lambda p: normalize_volume(
            _trim_only(p), target, increase_only=True
        ),
    }


def _embed_all(
    encoder, pipeline: Callable[[str], np.ndarray], paths: Sequence[str]
) -> Tuple[np.ndarray, float]:
    """Embed every path; returns the embeddings and the mean seconds per clip."""
    out = []
    start = time.perf_counter()
    for path in paths:
        out.append(
            encoder.embed_utterance(np.asarray(pipeline(path), dtype=np.float32))
        )
    return np.stack(out), (time.perf_counter() - start) / max(len(paths), 1)


def load_dataset(data_dir: Path) -> Tuple[List[str], List[str]]:
    """Return (paths, speaker labels) from one sub-directory per speaker."""
    paths: List[str] = []
    labels: List[str] = []
    for speaker_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        files = sorted(
            f for f in speaker_dir.iterdir() if f.suffix.lower() in AUDIO_SUFFIXES
        )
        if len(files) < 3:
            continue
        paths.extend(str(f) for f in files)
        labels.extend([speaker_dir.name] * len(files))
    if len(set(labels)) < 3:
        raise SystemExit("need at least 3 speakers with 3 or more files each")
    return paths, labels


def discrimination(encoder, pipelines, paths, labels) -> Dict[str, dict]:
    """Speaker-verification quality and cost per pipeline."""
    results: Dict[str, dict] = {}
    embeddings: Dict[str, np.ndarray] = {}
    for name, pipeline in pipelines.items():
        emb, seconds = _embed_all(encoder, pipeline, paths)
        embeddings[name] = emb
        same, diff = verification_scores(emb, labels)
        low, high = bootstrap_eer(emb, labels)
        results[name] = {
            "eer": equal_error_rate(same, diff),
            "eer_ci95": [low, high],
            "d_prime": d_prime(same, diff),
            "same_mean": float(np.mean(same)),
            "diff_mean": float(np.mean(diff)),
            "seconds_per_clip": seconds,
        }
    reference = embeddings["resemblyzer"]
    for name, emb in embeddings.items():
        cos = np.sum(emb * reference, axis=1) / (
            np.linalg.norm(emb, axis=1) * np.linalg.norm(reference, axis=1)
        )
        results[name]["cosine_to_resemblyzer"] = float(np.mean(cos))
    return results


def robustness(
    encoder, pipelines, paths, per_speaker_limit: int = 2, labels=None
) -> Dict[str, dict]:
    """Mean cosine between a clip's embedding and its degraded copy's, per pipeline.

    A pipeline that rejects the degraded clip (too little speech) counts as a
    rejection, reported separately, not as a similarity of zero.
    """
    from fastapi import HTTPException

    subset: List[str] = []
    seen: Dict[str, int] = {}
    for path, label in zip(paths, labels):
        if seen.get(label, 0) < per_speaker_limit:
            subset.append(path)
            seen[label] = seen.get(label, 0) + 1

    table: Dict[str, dict] = {name: {} for name in pipelines}
    with tempfile.TemporaryDirectory() as tmp:
        for degradation, apply in DEGRADATIONS.items():
            variants: List[str] = []
            for i, path in enumerate(subset):
                y, _ = librosa.load(path, sr=SAMPLE_RATE)
                target = os.path.join(tmp, f"{i}.wav")
                sf.write(target, apply(y), SAMPLE_RATE, subtype="PCM_16")
                variants.append(target)
            for name, pipeline in pipelines.items():
                sims: List[float] = []
                rejected = 0
                for clean_path, bad_path in zip(subset, variants):
                    try:
                        a = encoder.embed_utterance(
                            np.asarray(pipeline(clean_path), np.float32)
                        )
                        b = encoder.embed_utterance(
                            np.asarray(pipeline(bad_path), np.float32)
                        )
                    except HTTPException:
                        rejected += 1
                        continue
                    sims.append(
                        float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
                    )
                table[name][degradation] = {
                    "mean_cosine": float(np.mean(sims)) if sims else None,
                    "rejected": rejected,
                    "n": len(subset),
                }
    return table


CLONE_PIPELINES = ("current", "resemblyzer", "trim+level", "trim+level+vad")
# What matters when the upload itself is poor: the pipelines that can be adopted.
DEGRADED_CLONE_PIPELINES = ("current", "resemblyzer", "trim+level(inc)")
DEGRADED_CLONE_CASES = (
    "quiet (x0.03)",
    "loud, clipped (x8)",
    "noise (15 dB SNR)",
    "telephone band",
)
CLONE_TEXTS = (
    "The quick brown fox jumps over the lazy dog near the old river bank.",
    "She sells sea shells by the sea shore, and the shells she sells are surely seashells.",
    "Please call Stella and ask her to bring these things with her from the store.",
)


def paired_difference(
    candidate: Sequence[float], baseline: Sequence[float]
) -> Dict[str, float]:
    """Mean paired difference with a 95% interval and the share of units improved."""
    d = np.asarray(candidate, dtype=np.float64) - np.asarray(baseline, dtype=np.float64)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
    return {
        "mean": float(d.mean()),
        "ci95_low": float(d.mean() - 1.96 * se),
        "ci95_high": float(d.mean() + 1.96 * se),
        "improved": float(np.mean(d > 0)),
        "n": len(d),
    }


def clone_similarity(
    encoder,
    pipelines,
    paths,
    labels,
    speakers: int,
    texts_per_speaker: int = 1,
    seed: int = 1234,
    degrade: Optional[Callable[[np.ndarray], np.ndarray]] = None,
) -> Dict[str, dict]:
    """How close the cloned voice is to the real speaker, per pipeline.

    For each speaker the first utterance is the reference given to the cloner;
    the score is the cosine between the clone's embedding and the mean
    embedding of that speaker's *other* utterances, both computed with
    resemblyzer's own pipeline as the judge.

    The synthesizer and vocoder sample stochastically (measured: the same
    pipeline scored 0.8145 and 0.8179 on two runs), which can swamp a small
    difference. Each synthesis is therefore seeded from its (speaker, text)
    unit alone, so every pipeline gets the same random draws for the same unit
    and the comparison is paired.

    ``degrade``, if given, is applied to the reference recording only (the
    target stays clean), which measures quality when the user's upload is poor.
    """
    import asyncio

    import torch
    from resemblyzer.audio import preprocess_wav

    from backend.services.tts_pipeline import run_inference_pipeline

    judge = pipelines["resemblyzer"]
    by_speaker: Dict[str, List[str]] = {}
    for path, label in zip(paths, labels):
        by_speaker.setdefault(label, []).append(path)

    scores: Dict[str, List[float]] = {name: [] for name in pipelines}
    durations: Dict[str, List[float]] = {name: [] for name in pipelines}
    for n, (speaker, files) in enumerate(sorted(by_speaker.items())[:speakers]):
        reference, others = files[0], files[1:]
        target = np.mean(
            [encoder.embed_utterance(np.asarray(judge(p), np.float32)) for p in others],
            axis=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            reference_path = reference
            if degrade is not None:
                y, _ = librosa.load(reference, sr=SAMPLE_RATE)
                reference_path = os.path.join(tmp, "reference.wav")
                sf.write(reference_path, degrade(y), SAMPLE_RATE, subtype="PCM_16")
            embeddings = {
                name: encoder.embed_utterance(
                    np.asarray(pipeline(reference_path), np.float32)
                )
                for name, pipeline in pipelines.items()
            }
        for k in range(texts_per_speaker):
            text = CLONE_TEXTS[(n + k) % len(CLONE_TEXTS)]
            for name in pipelines:
                torch.manual_seed(seed + 1000 * n + k)
                out_path, duration = asyncio.run(
                    run_inference_pipeline(text, embeddings[name], f"study-{speaker}")
                )
                clone = encoder.embed_utterance(preprocess_wav(out_path))
                scores[name].append(
                    float(
                        np.dot(clone, target)
                        / (np.linalg.norm(clone) * np.linalg.norm(target))
                    )
                )
                durations[name].append(duration)
        logger.info("cloned speaker %d/%d", n + 1, speakers)
    return {
        name: {
            "mean_similarity": float(np.mean(vals)),
            "per_unit": vals,
            "mean_duration_s": float(np.mean(durations[name])),
            "vs_current": (
                paired_difference(vals, scores["current"])
                if name != "current"
                else None
            ),
        }
        for name, vals in scores.items()
    }


def main(argv: Optional[List[str]] = None) -> int:
    """Run the study and print a summary; write the full results as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("preprocessing_study.json"))
    parser.add_argument(
        "--clone", type=int, default=0, help="speakers to clone (needs weights)"
    )
    parser.add_argument(
        "--clone-texts", type=int, default=1, help="sentences per cloned speaker"
    )
    parser.add_argument(
        "--clone-degraded",
        type=int,
        default=0,
        metavar="SPEAKERS",
        help="also clone from degraded reference recordings (needs weights)",
    )
    parser.add_argument(
        "--clone-pipelines",
        default=",".join(CLONE_PIPELINES),
        help="comma-separated pipelines for --clone; must include current and resemblyzer",
    )
    parser.add_argument(
        "--clone-only",
        action="store_true",
        help="skip the discrimination and robustness studies (with --clone)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from resemblyzer import VoiceEncoder

    encoder = VoiceEncoder("cpu")
    pipelines = _pipelines()
    paths, labels = load_dataset(args.data_dir)
    logger.info("%d clips, %d speakers", len(paths), len(set(labels)))

    report: dict = {"clips": len(paths), "speakers": len(set(labels))}
    if not ((args.clone or args.clone_degraded) and args.clone_only):
        report["discrimination"] = discrimination(encoder, pipelines, paths, labels)
        report["robustness"] = robustness(encoder, pipelines, paths, labels=labels)
    if args.clone or args.clone_degraded:
        from backend.services.tts_pipeline import load_models

        load_models("cpu")
    if args.clone_degraded:
        chosen = {name: pipelines[name] for name in DEGRADED_CLONE_PIPELINES}
        report["clone_degraded"] = {
            case: clone_similarity(
                encoder,
                chosen,
                paths,
                labels,
                args.clone_degraded,
                degrade=DEGRADATIONS[case],
            )
            for case in DEGRADED_CLONE_CASES
        }
    if args.clone:
        # The judge ("resemblyzer") plus the pipelines a change could pick.
        names = [n.strip() for n in args.clone_pipelines.split(",") if n.strip()]
        missing = {"current", "resemblyzer"} - set(names)
        unknown = set(names) - set(pipelines)
        if missing or unknown:
            raise SystemExit(
                f"--clone-pipelines must include current and resemblyzer and use "
                f"known names (missing={sorted(missing)}, unknown={sorted(unknown)})"
            )
        chosen = {name: pipelines[name] for name in names}
        report["clone"] = clone_similarity(
            encoder, chosen, paths, labels, args.clone, args.clone_texts
        )
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
