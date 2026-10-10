"""Build the evaluation corpus for backend/evaluate_synthesis.py (SPEECH_QUALITY_PLAN.md S0.2).

    python -m backend.prepare_eval_corpus --parquet <test.clean/0000.parquet> --out <dir>

Reads LibriSpeech test-clean (Hugging Face ``openslr/librispeech_asr``, licence CC BY 4.0) from
its parquet file and writes, per chosen speaker, one *reference* clip of 10 to 30 s (the length
the product asks users for) and five *held-out* clips of 3 to 20 s, as 16 kHz mono WAV:

    <out>/<speaker>/0_ref_<id>.wav        the clip given to the cloner (sorts first)
    <out>/<speaker>/1_<id>.wav ...        real speech the clone is compared with
    <out>/groups.json                     speaker -> group, for ``--groups``
    <out>/manifest.json                   provenance: source, selection, per-speaker pitch

LibriSpeech has no gender column, so groups come from the *measured* median F0 of the clips:
``adult_low_f0`` (below 165 Hz, mostly men) and ``adult_high_f0`` (mostly women). These are
labelled by pitch because that is what is measured; they are not a claim about gender.

There is no child or elderly speech here: no licensed source has been verified yet (plan section
7.2), and children's voices carry consent duties of their own. Those groups stay empty until
then, so a result from this corpus says nothing about them.

The corpus is written to a scratch directory and never committed. Reading the parquet needs
``pyarrow`` (``pip install pyarrow``, or ``uv run --with pyarrow``); it is not a runtime dependency.
"""

import argparse
import io
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Where the typical male range (about 85 to 155 Hz) meets the typical female one (165 to 255 Hz).
F0_SPLIT_HZ = 165.0
REFERENCE_SECONDS = (10.0, 30.0)
REFERENCE_TARGET_SECONDS = 15.0
HELDOUT_SECONDS = (3.0, 20.0)
HELDOUT_CLIPS = 5

# --- Selection (pure) --------------------------------------------------------


@dataclass(frozen=True)
class Clip:
    """One utterance: its id and its length in seconds."""

    id: str
    seconds: float


def pitch_group(median_f0_hz: Optional[float]) -> str:
    """Name the group of a speaker from their median F0 (``unknown`` if unmeasurable)."""
    if median_f0_hz is None or not np.isfinite(median_f0_hz) or median_f0_hz <= 0:
        return "unknown"
    return "adult_low_f0" if median_f0_hz < F0_SPLIT_HZ else "adult_high_f0"


def choose_speakers(clips: Mapping[str, Sequence[Clip]], count: int) -> List[str]:
    """Pick ``count`` speakers who have a usable reference and enough held-out clips.

    Eligible speakers are sorted and sampled at even spacing, so the choice is deterministic
    and not simply the first ``count`` ids.
    """
    eligible = sorted(s for s, cs in clips.items() if choose_clips(cs) is not None)
    if count < 1:
        raise ValueError("count must be >= 1")
    if len(eligible) <= count:
        return eligible
    step = len(eligible) / count
    return [eligible[int(i * step)] for i in range(count)]


def choose_clips(clips: Sequence[Clip]) -> Optional[Tuple[Clip, List[Clip]]]:
    """Return ``(reference, held_out)`` for one speaker, or ``None`` if they do not qualify.

    The reference is the clip of 10 to 30 s closest to 15 s; the held-out clips are the first
    ``HELDOUT_CLIPS`` others of 3 to 20 s, in id order.
    """
    low, high = REFERENCE_SECONDS
    candidates = [c for c in clips if low <= c.seconds <= high]
    if not candidates:
        return None
    reference = min(
        candidates, key=lambda c: (abs(c.seconds - REFERENCE_TARGET_SECONDS), c.id)
    )
    lo, hi = HELDOUT_SECONDS
    held = [
        c
        for c in sorted(clips, key=lambda c: c.id)
        if c.id != reference.id and lo <= c.seconds <= hi
    ]
    if len(held) < HELDOUT_CLIPS:
        return None
    return reference, held[:HELDOUT_CLIPS]


# --- Reading and writing (needs pyarrow and the dataset) ----------------------


def _decode(audio_bytes: bytes) -> np.ndarray:
    """Decode FLAC/WAV bytes to mono float32 at 16 kHz (LibriSpeech is already 16 kHz)."""
    samples, rate = sf.read(io.BytesIO(audio_bytes), dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate != SAMPLE_RATE:
        raise ValueError(f"expected {SAMPLE_RATE} Hz audio, got {rate} Hz")
    return samples


def read_parquet(path: Path) -> Dict[str, List[Tuple[Clip, bytes]]]:
    """Read every utterance's id, speaker, length and encoded audio, grouped by speaker."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit(
            "pyarrow is required: pip install pyarrow (or `uv run --with pyarrow`)"
        )
    by_speaker: Dict[str, List[Tuple[Clip, bytes]]] = {}
    parquet = pq.ParquetFile(path)
    for group in range(parquet.num_row_groups):
        for row in parquet.read_row_group(
            group, columns=["speaker_id", "id", "audio"]
        ).to_pylist():
            audio_bytes = row["audio"]["bytes"]
            info = sf.info(io.BytesIO(audio_bytes))
            clip = Clip(str(row["id"]), info.frames / info.samplerate)
            by_speaker.setdefault(str(row["speaker_id"]), []).append(
                (clip, audio_bytes)
            )
    return by_speaker


def write_corpus(
    by_speaker: Mapping[str, Sequence[Tuple[Clip, bytes]]], speakers: int, out: Path
) -> Dict[str, object]:
    """Write the chosen speakers' clips, ``groups.json`` and ``manifest.json``; return the manifest."""
    from backend.evaluate_synthesis import (  # the same tracker the study scores with
        f0_track,
    )

    chosen = choose_speakers(
        {s: [c for c, _ in rows] for s, rows in by_speaker.items()}, speakers
    )
    groups: Dict[str, str] = {}
    details: Dict[str, object] = {}
    for speaker in chosen:
        audio = {clip.id: data for clip, data in by_speaker[speaker]}
        picked = choose_clips([c for c, _ in by_speaker[speaker]])
        assert picked is not None  # choose_speakers only returns qualifying speakers
        reference, held = picked
        speaker_dir = out / speaker
        speaker_dir.mkdir(parents=True, exist_ok=True)
        pitches: List[float] = []
        for name, clip in [(f"0_ref_{reference.id}.wav", reference)] + [
            (f"1_{c.id}.wav", c) for c in held
        ]:
            samples = _decode(audio[clip.id])
            sf.write(speaker_dir / name, samples, SAMPLE_RATE, subtype="PCM_16")
            voiced = f0_track(samples)
            pitches.extend(float(v) for v in voiced[np.isfinite(voiced)])
        median = float(np.median(pitches)) if pitches else None
        groups[speaker] = pitch_group(median)
        details[speaker] = {
            "group": groups[speaker],
            "median_f0_hz": median,
            "reference": {"id": reference.id, "seconds": round(reference.seconds, 2)},
            "held_out": [{"id": c.id, "seconds": round(c.seconds, 2)} for c in held],
        }
        logger.info(
            "wrote speaker %s (%s, median F0 %s Hz)",
            speaker,
            groups[speaker],
            median and round(median),
        )
    manifest = {
        "source": "LibriSpeech test-clean via Hugging Face openslr/librispeech_asr (CC BY 4.0)",
        "sample_rate": SAMPLE_RATE,
        "f0_split_hz": F0_SPLIT_HZ,
        "group_note": "groups are measured median-F0 bands, not gender labels; no child/elderly speech",
        "speakers": details,
    }
    (out / "groups.json").write_text(json.dumps(groups, indent=2))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    """Prepare the corpus and print a short summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--speakers", type=int, default=20)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    manifest = write_corpus(read_parquet(args.parquet), args.speakers, args.out)
    counts: Dict[str, int] = {}
    for info in manifest["speakers"].values():  # type: ignore[union-attr]
        counts[info["group"]] = counts.get(info["group"], 0) + 1
    print(
        json.dumps(
            {
                "out": str(args.out),
                "speakers": sum(counts.values()),
                "per_group": counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
