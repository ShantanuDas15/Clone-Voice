"""Measure how far model inference delays the asyncio event loop.

HARDENING_PLAN.md finding P2-M6 suspected that WaveRNN's per-sample Python
loop, run in a worker thread inside the single uvicorn process, competes with
the event loop for the GIL and slows every endpoint (including
`/health/live`). This tool measures that instead of assuming it: it runs the
real synthesizer and vocoder stages in a worker thread, exactly as
`tts_pipeline._InferenceSlot.run()` does, while a 10 ms heartbeat on the event
loop records how late each wake-up is.

  python -m backend.measure_event_loop_lag                # real checkpoints
  python -m backend.measure_event_loop_lag --mock         # fast smoke test
  taskset -c 0,1 python -m backend.measure_event_loop_lag # constrained CPU

Exit status is 0 when the worst loop delay stays within ``--max-lag-ms``
(default 250 ms, far below the 2 s readiness and 5 s container health-check
timeouts) and 1 otherwise, so it can gate a deploy or a hardware change. A
failing result is the signal to move inference into a separate process; a
passing one means that added complexity isn't warranted.

The real run needs the provisioned checkpoints (`download_weights --fetch`).
It derives a realistic speaker embedding by running the encoder on synthesized
audio, because a random embedding makes the synthesizer stop after a few
frames. Never invoked by the running server.
"""

import argparse
import asyncio
import logging
import statistics
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple

import numpy as np

from backend.core.config import settings
from backend.services import tts_pipeline

logger = logging.getLogger(__name__)

DEFAULT_MAX_LAG_MS = 250.0
_SENTENCE = "The quick brown fox jumps over the lazy dog near the riverbank. "
_SEED_TEXT = "The quick brown fox jumps over the lazy dog and keeps running."


@dataclass(frozen=True)
class LagStats:
    """Summary of event-loop wake-up delays, in milliseconds."""

    samples: int
    mean_ms: float
    p99_ms: float
    max_ms: float


def summarize(lags_ms: Sequence[float]) -> LagStats:
    """Reduce raw heartbeat delays to mean, 99th percentile and maximum."""
    if not lags_ms:
        raise ValueError("no lag samples were collected")
    ordered = sorted(lags_ms)
    p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
    return LagStats(
        samples=len(ordered),
        mean_ms=statistics.mean(ordered),
        p99_ms=p99,
        max_ms=ordered[-1],
    )


async def _heartbeat(
    stop: asyncio.Event, lags_ms: List[float], interval_seconds: float
) -> None:
    """Sleep repeatedly and record how much later than asked each wake-up was."""
    while not stop.is_set():
        started = time.perf_counter()
        await asyncio.sleep(interval_seconds)
        lags_ms.append((time.perf_counter() - started - interval_seconds) * 1000)


async def measure_lag(
    work: Callable[[], Awaitable[Any]],
    interval_seconds: float = 0.01,
    warmup_seconds: float = 0.2,
) -> Tuple[LagStats, float, Any]:
    """Run ``work`` while a heartbeat runs; return (lag stats, wall seconds, result).

    Only heartbeat samples taken while ``work`` runs count, so idle warm-up
    noise is excluded. A loop blocked for the whole call still yields one late
    sample when it unblocks, so blocking is always detected.
    """
    stop = asyncio.Event()
    lags_ms: List[float] = []
    beat = asyncio.create_task(_heartbeat(stop, lags_ms, interval_seconds))
    try:
        await asyncio.sleep(warmup_seconds)
        first = len(lags_ms)
        started = time.perf_counter()
        result = await work()
        wall = time.perf_counter() - started
    finally:
        stop.set()
        await beat
    return summarize(lags_ms[first:] or lags_ms[-1:]), wall, result


def _derive_embedding() -> np.ndarray:
    """Return a realistic speaker embedding (encoder run on synthesized audio)."""
    seed = np.random.default_rng(2).normal(size=256).astype("float32")
    seed /= np.linalg.norm(seed)
    wav = tts_pipeline.vocode(tts_pipeline.synthesize_speech(_SEED_TEXT, seed))
    return tts_pipeline.embed_speaker(wav).astype("float32")


def _log_stage(name: str, stats: LagStats, wall: float) -> None:
    """Log one stage's wall time and loop-lag summary."""
    logger.info(
        "%-11s wall=%6.1fs  loop lag ms: mean=%.1f p99=%.1f max=%.1f (n=%d)",
        name,
        wall,
        stats.mean_ms,
        stats.p99_ms,
        stats.max_ms,
        stats.samples,
    )


async def _measure_pipeline(
    text: str, embedding: np.ndarray
) -> List[Tuple[str, LagStats, float]]:
    """Measure the synthesizer and vocoder stages, each in a worker thread."""
    synth_stats, synth_wall, mel = await measure_lag(
        lambda: asyncio.to_thread(tts_pipeline.synthesize_speech, text, embedding)
    )
    voc_stats, voc_wall, audio = await measure_lag(
        lambda: asyncio.to_thread(tts_pipeline.vocode, mel)
    )
    logger.info(
        "Produced %.1f s of audio from %d characters.",
        len(audio) / tts_pipeline.synth_hparams.sample_rate,
        len(text),
    )
    return [
        ("synthesizer", synth_stats, synth_wall),
        ("vocoder", voc_stats, voc_wall),
    ]


def main(argv: Optional[List[str]] = None) -> int:
    """Run the measurement; return 0 if the worst loop lag is within the limit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true", help="use mock models")
    parser.add_argument("--text-chars", type=int, default=500)
    parser.add_argument("--max-lag-ms", type=float, default=DEFAULT_MAX_LAG_MS)
    args = parser.parse_args(argv)

    if args.mock:
        tts_pipeline.load_mock_models("cpu")
        embedding = np.zeros(256, dtype=np.float32)
    else:
        tts_pipeline.load_models(device=settings.DEVICE)
        embedding = _derive_embedding()
    text = (_SENTENCE * (args.text_chars // len(_SENTENCE) + 1))[: args.text_chars]

    results = asyncio.run(_measure_pipeline(text, embedding))
    for name, stats, wall in results:
        _log_stage(name, stats, wall)

    worst = max(stats.max_ms for _, stats, _ in results)
    if worst > args.max_lag_ms:
        logger.error(
            "Worst event-loop lag %.1f ms exceeds %.1f ms: consider running "
            "inference in a separate process (HARDENING_PLAN.md P2-M6).",
            worst,
            args.max_lag_ms,
        )
        return 1
    logger.info(
        "Worst event-loop lag %.1f ms is within %.1f ms.", worst, args.max_lag_ms
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    raise SystemExit(main())
