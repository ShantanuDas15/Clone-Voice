"""Positive control for the question metric (SPEECH_QUALITY_PLAN.md S0.3).

    python -m backend.question_control --parquet <test.clean/0000.parquet> --out report.json

``evaluate_synthesis`` says a ``?`` rises about as often as chance. That reading is only
meaningful if the metric (the pitch slope over the last 0.3 s, ``final_f0_slope``) can tell
real questions from real statements. This tool runs it on **human** speech: LibriSpeech
utterances that look like yes/no questions against utterances that look like statements, and
reports how often a question ends higher than a statement (an AUC; 0.5 is chance).

LibriSpeech transcripts have no punctuation, so the labels are a heuristic on the words: a short
utterance that opens with an auxiliary verb and a pronoun ("DO YOU", "IS IT") and has no speech
attribution ("SAID", "ASKED") is a yes/no question; one that opens with neither an auxiliary nor a
wh-word is a statement. Wh-questions are left out on purpose, they often fall in pitch. The labels
are noisy and the set of questions is small, so read the interval, not the point value.

The metric functions are pure and unit-tested; the dataset is never committed. Reading the
parquet needs ``pyarrow`` (``pip install pyarrow``); it is not a runtime dependency.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from backend.evaluate_synthesis import bootstrap_ci, f0_track, final_f0_slope
from backend.prepare_eval_corpus import _decode

logger = logging.getLogger(__name__)

AUXILIARIES = frozenset(
    "DO DOES DID IS ARE WAS WERE HAVE HAS HAD WILL WOULD CAN COULD SHALL SHOULD MAY MIGHT".split()
)
WH_WORDS = frozenset("WHO WHOM WHOSE WHAT WHICH WHERE WHEN WHY HOW".split())
PRONOUNS = frozenset("YOU HE SHE IT THEY WE I THERE THAT THIS".split())
ATTRIBUTIONS = frozenset(
    "SAID ASKED ASKS ASK REPLIED CRIED ANSWERED INQUIRED EXCLAIMED DEMANDED "
    "SAYS REPLY CRY WHISPERED MURMURED".split()
)
MIN_WORDS = 4
MAX_WORDS = 15


def _words(text: str) -> List[str]:
    """Upper-case words of a transcript."""
    return text.upper().split()


def is_yes_no_question(text: str, max_words: int = MAX_WORDS) -> bool:
    """True for a short utterance that opens with an auxiliary and a pronoun, with no attribution."""
    words = _words(text)
    return (
        MIN_WORDS <= len(words) <= max_words
        and words[0] in AUXILIARIES
        and words[1] in PRONOUNS
        and not ATTRIBUTIONS.intersection(words)
    )


def is_statement(text: str, max_words: int = MAX_WORDS) -> bool:
    """True for a short utterance that opens with neither an auxiliary nor a wh-word."""
    words = _words(text)
    return (
        MIN_WORDS <= len(words) <= max_words
        and words[0] not in AUXILIARIES
        and words[0] not in WH_WORDS
        and not ATTRIBUTIONS.intersection(words)
    )


def auc(positives: Sequence[float], negatives: Sequence[float]) -> Optional[float]:
    """Chance that a random positive scores above a random negative (ties count half)."""
    if len(positives) == 0 or len(negatives) == 0:
        return None
    p = np.asarray(positives, dtype=np.float64)[:, None]
    n = np.asarray(negatives, dtype=np.float64)[None, :]
    return float(np.mean((p > n) + 0.5 * (p == n)))


def bootstrap_auc(
    positives: Sequence[float],
    negatives: Sequence[float],
    n_boot: int = 2000,
    seed: int = 0,
) -> Tuple[float, float, float]:
    """AUC and a 95% percentile bootstrap interval over both groups; nan when either is empty."""
    point = auc(positives, negatives)
    if point is None:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    p, n = np.asarray(positives), np.asarray(negatives)
    draws = [
        auc(
            p[rng.integers(0, len(p), len(p))],
            n[rng.integers(0, len(n), len(n))],
        )
        for _ in range(n_boot)
    ]
    low, high = np.percentile(draws, [2.5, 97.5])
    return point, float(low), float(high)


def summarize(
    question_slopes: Sequence[float], statement_slopes: Sequence[float]
) -> Dict[str, object]:
    """Final-slope statistics of both classes and how well the slope separates them."""
    point, low, high = bootstrap_auc(question_slopes, statement_slopes)
    q_mean, q_low, q_high = bootstrap_ci(question_slopes)
    s_mean, s_low, s_high = bootstrap_ci(statement_slopes)
    return {
        "questions": {
            "n": len(question_slopes),
            "mean_slope": q_mean,
            "ci_low": q_low,
            "ci_high": q_high,
            "share_rising": (
                float(np.mean(np.asarray(question_slopes) > 0))
                if len(question_slopes)
                else None
            ),
        },
        "statements": {
            "n": len(statement_slopes),
            "mean_slope": s_mean,
            "ci_low": s_low,
            "ci_high": s_high,
            "share_rising": (
                float(np.mean(np.asarray(statement_slopes) > 0))
                if len(statement_slopes)
                else None
            ),
        },
        "auc": point,
        "auc_ci_low": low,
        "auc_ci_high": high,
        "separates": bool(low > 0.5) if np.isfinite(low) else False,
    }


def read_candidates(
    path: Path, max_statements: int, seed: int
) -> Tuple[List[Tuple[str, np.ndarray]], List[Tuple[str, np.ndarray]]]:
    """Decode the question and (a seeded sample of the) statement utterances of a parquet file."""
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise SystemExit("pyarrow is required: pip install pyarrow")
    rows = pq.read_table(path, columns=["id", "text", "audio"]).to_pylist()
    questions = [r for r in rows if is_yes_no_question(r["text"])]
    statements = [r for r in rows if is_statement(r["text"])]
    rng = np.random.default_rng(seed)
    if len(statements) > max_statements:
        keep = rng.choice(len(statements), size=max_statements, replace=False)
        statements = [statements[i] for i in sorted(keep)]

    def decode(items: List[dict]) -> List[Tuple[str, np.ndarray]]:
        """Pair each utterance's text with its decoded audio."""
        return [(r["text"], _decode(r["audio"]["bytes"])) for r in items]

    return decode(questions), decode(statements)


def slopes(clips: Sequence[Tuple[str, np.ndarray]]) -> List[float]:
    """Final pitch slope of each clip, skipping clips too short or unvoiced to measure."""
    out = []
    for _, audio in clips:
        value = final_f0_slope(f0_track(audio))
        if value is not None:
            out.append(value)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """Run the control on a LibriSpeech parquet file and write the JSON report."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--parquet", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-statements", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args(argv)
    if args.max_statements < 1:
        raise SystemExit("--max-statements must be at least 1")

    questions, statements = read_candidates(
        args.parquet, args.max_statements, args.seed
    )
    report = summarize(slopes(questions), slopes(statements))
    report["question_texts"] = [text for text, _ in questions]
    text = json.dumps(report, indent=2)
    if args.out is not None:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
