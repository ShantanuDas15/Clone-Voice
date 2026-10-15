"""Make the audio for a listening test from pipeline variants (SPEECH_QUALITY_PLAN.md S0.6).

    python -m backend.make_listening_stimuli --corpus <dir> --out <dir> \\
        [--variants eval_data/listening_variants.json] [--source benchmark|paragraphs|typed]
        [--speakers 6] [--texts 10] [--seed 1]
    python -m backend.listening_test build --system current=<dir>/current --system flat_pause=<dir>/flat_pause ...

Runs the production pipeline (the real weights, on the CPU) once per variant, speaker and text and
writes ``<out>/<variant>/<speaker>/<i>.wav``, the layout ``listening_test`` reads. A variant is a
set of ``Settings`` overrides (pause table, limiter, best-of-N, ...); the first variant in the file
is the baseline. Every variant uses the same seed for the same speaker and text, so the pair
differs only by the setting. The corpus is the layout ``prepare_eval_corpus`` writes. Evaluation
only: it needs the model weights and resemblyzer, and is never imported by the app.
"""

import argparse
import contextlib
import json
import logging
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Sequence

import numpy as np

from backend import evaluate_synthesis as ev
from backend.score_engine_outputs import DEFAULT_TEXTS, load_benchmark_texts

DEFAULT_VARIANTS = (
    Path(__file__).resolve().parent / "eval_data" / "listening_variants.json"
)
logger = logging.getLogger(__name__)

Synthesizer = Callable[[str, np.ndarray, str, int], "tuple[np.ndarray, int]"]


def load_variants(path: Path = DEFAULT_VARIANTS) -> Dict[str, Dict[str, object]]:
    """Read ``{variant name: Settings overrides}``, in file order (the first is the baseline)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    variants = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants, dict) or len(variants) < 2:
        raise SystemExit(f"{path} needs a 'variants' object with at least two variants")
    for name, overrides in variants.items():
        if not name or "/" in name or name in (".", "..") or name == "degraded":
            raise SystemExit(f"bad variant name {name!r}")
        if not isinstance(overrides, dict):
            raise SystemExit(f"variant {name!r} must map setting names to values")
    return variants


def check_overrides(settings: object, overrides: Mapping[str, object]) -> None:
    """Refuse an override naming no setting, or giving a value of another kind."""
    for key, value in overrides.items():
        if not hasattr(settings, key) or key.startswith("_"):
            raise ValueError(f"unknown setting {key!r}")
        current = getattr(settings, key)
        if isinstance(current, dict):
            if not isinstance(value, dict) or not set(value) <= set(current):
                raise ValueError(
                    f"{key} must be an object using only {sorted(current)}"
                )
        elif isinstance(current, bool) or isinstance(value, bool):
            if type(current) is not type(value):
                raise ValueError(f"{key} must be a boolean")
        elif isinstance(current, (int, float)):
            if not isinstance(value, (int, float)):
                raise ValueError(f"{key} must be a number")
        elif type(current) is not type(value):
            raise ValueError(f"{key} must be {type(current).__name__}")


@contextlib.contextmanager
def applied(settings: object, overrides: Mapping[str, object]) -> Iterator[None]:
    """Apply setting overrides for the block, then put every touched setting back."""
    check_overrides(settings, overrides)
    saved = {key: getattr(settings, key) for key in overrides}
    try:
        for key, value in overrides.items():
            current = saved[key]
            setattr(
                settings,
                key,
                {**current, **value} if isinstance(current, dict) else value,
            )
        yield
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)


def output_path(out: Path, variant: str, speaker: str, index: int) -> Path:
    """Where a variant's rendering of text ``index`` for ``speaker`` goes."""
    return out / variant / speaker / f"{index}.wav"


def generate(
    settings: object,
    variants: Mapping[str, Mapping[str, object]],
    speakers: Mapping[str, np.ndarray],
    texts: Sequence[str],
    out: Path,
    seed: int,
    synthesize: Synthesizer,
) -> int:
    """Write every variant's audio; returns the number of files made.

    ``speakers`` maps a name to its embedding. ``synthesize(text, embedding, speaker, seed)``
    returns the waveform and sample rate. All overrides are checked before anything runs.
    """
    import soundfile as sf

    for overrides in variants.values():
        check_overrides(settings, overrides)
    made = 0
    for variant, overrides in variants.items():
        with applied(settings, overrides):
            for n, (speaker, embedding) in enumerate(speakers.items()):
                for i, text in enumerate(texts):
                    wave, rate = synthesize(
                        text, embedding, speaker, seed + 1000 * n + i
                    )
                    path = output_path(out, variant, speaker, i)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    sf.write(str(path), wave, rate, subtype="PCM_16")
                    made += 1
        logger.info("variant %s done", variant)
    return made


def _pipeline_synthesize(
    text: str, embedding: np.ndarray, speaker: str, seed: int
) -> "tuple[np.ndarray, int]":
    """Run the production pipeline for one text; the pipeline's own file is removed."""
    import asyncio
    import os

    import soundfile as sf
    import torch

    from backend.services.tts_pipeline import run_inference_pipeline

    torch.manual_seed(seed)
    path, _ = asyncio.run(run_inference_pipeline(text, embedding, f"stimuli-{speaker}"))
    try:
        wave, rate = sf.read(path, dtype="float32")
    finally:
        os.remove(path)
    return np.asarray(wave, np.float32), int(rate)


def main(argv: Optional[List[str]] = None) -> int:
    """Synthesize every variant for the chosen speakers and texts."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variants", type=Path, default=DEFAULT_VARIANTS)
    parser.add_argument("--texts", type=int, default=10, help="how many texts")
    parser.add_argument(
        "--source",
        choices=("benchmark", "paragraphs", "typed"),
        default="benchmark",
        help="benchmark: the 10 single sentences of the engine study; paragraphs: multi-sentence "
        "text (needed to hear pause changes); typed: times, dates and symbols",
    )
    parser.add_argument("--texts-file", type=Path, default=DEFAULT_TEXTS)
    parser.add_argument("--speakers", type=int, default=6)
    parser.add_argument("--groups", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.texts < 1 or args.speakers < 1:
        raise SystemExit("--texts and --speakers must be at least 1")
    variants = load_variants(args.variants)
    from backend.core.config import settings

    for overrides in variants.values():
        check_overrides(settings, overrides)
    if args.source == "benchmark":
        texts = [t["text"] for t in load_benchmark_texts(args.texts_file)]
    else:
        texts = [t["text"] for t in ev.load_stimuli(ev.DEFAULT_SENTENCES, args.source)]
    texts = texts[: args.texts]
    if args.source == "benchmark" and any(
        "TTS_PAUSE_SECONDS" in v for v in variants.values()
    ):
        logger.warning(
            "a variant changes the pauses, but the benchmark texts are single sentences: "
            "the clips will be identical; use --source paragraphs"
        )
    dataset = ev.load_dataset(args.corpus)
    groups = ev.load_groups(args.groups or (args.corpus / "groups.json"))
    chosen = ev.select_speakers(dataset, groups, args.speakers)

    from resemblyzer import VoiceEncoder

    from backend.services.tts_pipeline import load_models

    load_models("cpu")
    encoder = VoiceEncoder("cpu")
    embeddings = {s: ev.reference_embedding(encoder, dataset[s][0]) for s in chosen}
    made = generate(
        settings, variants, embeddings, texts, args.out, args.seed, _pipeline_synthesize
    )
    print(f"{made} clips for {list(variants)} in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
