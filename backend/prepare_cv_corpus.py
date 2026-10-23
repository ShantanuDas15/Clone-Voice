"""Build an elderly-speech evaluation corpus from Mozilla Common Voice (SPEECH_QUALITY_PLAN.md S0.2b).

    python -m backend.prepare_cv_corpus --cv-dir <cv-corpus/en> --out <dir> [--per-group 10]

Reads ``validated.tsv`` (or, for a release split into speaker-disjoint subsets, ``train.tsv``,
``dev.tsv`` and ``test.tsv``) and the ``clips/`` folder of an English Common Voice release (licence CC0-1.0)
and writes, per chosen speaker, one *reference* of 10 to 30 s (several of the speaker's own clips
joined with a short silence) and five *held-out* clips of 3 to 20 s, as 16 kHz mono WAV, in the layout
``backend/evaluate_synthesis.py`` reads (``<out>/<speaker>/0_ref.wav``, ``1_<clip>.wav`` ...), plus
``groups.json`` and ``manifest.json``.

Two groups come from the self-declared age field, both from Common Voice so the recording conditions
(crowd-sourced microphones, mp3) are the same and only age differs:

    elderly            sixties and seventies (Common Voice has no older band)
    cv_adult_control   twenties, thirties and forties

A result is only about age when ``elderly`` is read against ``cv_adult_control``; read against the
studio-quality LibriSpeech groups it would mix age with recording quality.

Licence terms (the datasheet): do not try to identify speakers and do not re-host or re-share the
data. Speakers are therefore named by a hash of their ``client_id``, the manifest holds no raw ids or
sentence text, and the corpus belongs in a scratch directory, never in the repository. Age is
self-declared and opt-in, so speakers without it are skipped. There is no child group: Common
Voice's youngest band is teens.

The selection functions are pure and unit-tested; the dataset is never committed.
"""

import argparse
import csv
import hashlib
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

import librosa
import numpy as np
import soundfile as sf

from backend.prepare_eval_corpus import (
    HELDOUT_CLIPS,
    HELDOUT_SECONDS,
    REFERENCE_SECONDS,
    SAMPLE_RATE,
)

logger = logging.getLogger(__name__)

AGE_GROUPS: Mapping[str, str] = {
    "sixties": "elderly",
    "seventies": "elderly",
    "eighties": "elderly",
    "nineties": "elderly",
    "twenties": "cv_adult_control",
    "thirties": "cv_adult_control",
    "fourties": "cv_adult_control",  # Common Voice's own spelling
    "forties": "cv_adult_control",
}
# Clips of one speaker are joined with this much silence to make the reference.
JOIN_SILENCE_SECONDS = 0.25
# A speaker needs at least this many clips before their durations are read.
MIN_CLIPS = 4
LICENCE_NOTE = (
    "Mozilla Common Voice (CC0-1.0). Terms: do not identify speakers, do not re-host or "
    "re-share. Speakers are hashed; keep this corpus out of the repository."
)

# --- Selection (pure) --------------------------------------------------------


def age_group(age: Optional[str]) -> Optional[str]:
    """The study group of a self-declared age band, or ``None`` if it has none or is unused."""
    return AGE_GROUPS.get((age or "").strip().lower())


def speaker_hash(client_id: str) -> str:
    """A short stable pseudonym for a Common Voice ``client_id``."""
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:12]


def plan_speaker(
    clips: Sequence[Tuple[str, float]],
) -> Optional[Tuple[List[str], List[str]]]:
    """Choose ``(reference_clips, held_out_clips)`` from ``(clip_id, seconds)``, or ``None``.

    The reference is the first clips, in id order, whose total length (plus the joins) reaches
    the minimum of 10 s without passing 30 s; the held-out clips are the next ``HELDOUT_CLIPS`` of
    3 to 20 s. Whole clips only, none used twice.
    """
    low, high = REFERENCE_SECONDS
    ordered = sorted(clips)
    reference: List[str] = []
    total = 0.0
    used = 0
    for clip_id, seconds in ordered:
        used += 1
        joined = total + seconds + (JOIN_SILENCE_SECONDS if reference else 0.0)
        if joined > high:
            return None
        reference.append(clip_id)
        total = joined
        if total >= low:
            break
    else:
        return None
    lo, hi = HELDOUT_SECONDS
    held = [c for c, s in ordered[used:] if lo <= s <= hi][:HELDOUT_CLIPS]
    if len(held) < HELDOUT_CLIPS:
        return None
    return reference, held


# --- Reading and writing (needs the dataset) ---------------------------------


SPLIT_FILES = ("train.tsv", "dev.tsv", "test.tsv")


def tsv_files(cv_dir: Path) -> List[Path]:
    """The metadata files of a release: ``validated.tsv``, else the train/dev/test split files."""
    validated = cv_dir / "validated.tsv"
    if validated.is_file():
        return [validated]
    return [cv_dir / name for name in SPLIT_FILES if (cv_dir / name).is_file()]


def read_speakers(
    tsv: Union[Path, Sequence[Path]],
) -> Dict[str, Dict[str, List[str]]]:
    """Group the clip paths of every speaker with a usable age: ``{group: {client_id: [paths]}}``."""
    paths = [tsv] if isinstance(tsv, Path) else list(tsv)
    groups: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for path in paths:
        with open(path, newline="", encoding="utf-8") as handle:
            # QUOTE_NONE: sentences hold stray quote marks that would otherwise merge rows.
            for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
                group = age_group(row.get("age"))
                if group is not None and row.get("client_id") and row.get("path"):
                    groups[group][row["client_id"]].append(row["path"])
    return {g: dict(clients) for g, clients in groups.items()}


def _load(path: Path) -> np.ndarray:
    """Decode a clip to mono float32 at 16 kHz (Common Voice clips are mp3 at 32 or 48 kHz)."""
    samples, rate = sf.read(path, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if rate != SAMPLE_RATE:
        samples = librosa.resample(samples, orig_sr=rate, target_sr=SAMPLE_RATE)
    return np.asarray(samples, dtype=np.float32)


def _seconds(path: Path) -> Optional[float]:
    """Length of a clip in seconds, or ``None`` if the file is missing or unreadable."""
    try:
        info = sf.info(path)
    except (OSError, RuntimeError):
        return None
    return info.frames / info.samplerate


def choose_speakers(
    clients: Mapping[str, Sequence[str]], clips_dir: Path, count: int
) -> List[Tuple[str, List[str], List[str]]]:
    """Take the first ``count`` speakers, in hash order, who can fill a reference and held-out set."""
    chosen: List[Tuple[str, List[str], List[str]]] = []
    for client_id in sorted(clients, key=speaker_hash):
        paths = clients[client_id]
        if len(paths) < MIN_CLIPS + HELDOUT_CLIPS - 1:
            continue
        measured = [(p, _seconds(clips_dir / p)) for p in paths]
        plan = plan_speaker([(p, s) for p, s in measured if s is not None])
        if plan is not None:
            chosen.append((client_id, plan[0], plan[1]))
        if len(chosen) == count:
            break
    return chosen


def write_corpus(cv_dir: Path, out: Path, per_group: int) -> Dict[str, object]:
    """Write the chosen speakers' audio, ``groups.json`` and ``manifest.json``; return the manifest."""
    clips_dir = cv_dir / "clips"
    by_group = read_speakers(tsv_files(cv_dir))
    gap = np.zeros(int(JOIN_SILENCE_SECONDS * SAMPLE_RATE), dtype=np.float32)
    groups: Dict[str, str] = {}
    details: Dict[str, object] = {}
    for group in sorted(set(AGE_GROUPS.values())):
        picked = choose_speakers(by_group.get(group, {}), clips_dir, per_group)
        if len(picked) < per_group:
            logger.warning(
                "group %s: only %d of %d speakers qualified",
                group,
                len(picked),
                per_group,
            )
        for client_id, reference, held in picked:
            name = speaker_hash(client_id)
            speaker_dir = out / name
            speaker_dir.mkdir(parents=True, exist_ok=True)
            parts: List[np.ndarray] = []
            for clip in reference:
                parts.extend([_load(clips_dir / clip), gap])
            sf.write(
                speaker_dir / "0_ref.wav",
                np.concatenate(parts[:-1]),
                SAMPLE_RATE,
                subtype="PCM_16",
            )
            for i, clip in enumerate(held, 1):
                sf.write(
                    speaker_dir / f"1_{i}.wav",
                    _load(clips_dir / clip),
                    SAMPLE_RATE,
                    subtype="PCM_16",
                )
            groups[name] = group
            details[name] = {
                "group": group,
                "reference_clips": len(reference),
                "held_out_clips": len(held),
            }
    manifest = {
        "source": "Mozilla Common Voice (CC0-1.0)",
        "licence_note": LICENCE_NOTE,
        "sample_rate": SAMPLE_RATE,
        "age_groups": dict(AGE_GROUPS),
        "group_note": "groups come from self-declared age; elderly is read against cv_adult_control",
        "speakers": details,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "groups.json").write_text(json.dumps(groups, indent=2))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: Optional[List[str]] = None) -> int:
    """Prepare the corpus and print a short summary."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cv-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-group", type=int, default=10)
    args = parser.parse_args(argv)
    if args.per_group < 1:
        raise SystemExit("--per-group must be at least 1")
    if not tsv_files(args.cv_dir):
        raise SystemExit(
            f"{args.cv_dir}: no validated.tsv or train/dev/test .tsv files found"
        )
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    manifest = write_corpus(args.cv_dir, args.out, args.per_group)
    counts: Dict[str, int] = defaultdict(int)
    for info in manifest["speakers"].values():  # type: ignore[union-attr]
        counts[info["group"]] += 1
    print(json.dumps({"out": str(args.out), "per_group": dict(counts)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
