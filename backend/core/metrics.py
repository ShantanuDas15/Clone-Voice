"""Prometheus metrics for the inference pipeline (HARDENING_PLAN.md finding M8)."""

import time
from contextlib import contextmanager
from typing import Callable, Iterator

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Dedicated registry: exposes only our metrics (no default process/platform
# collectors) and avoids duplicate-registration errors on module reloads.
registry = CollectorRegistry()

# Inference forward passes take from tens of ms (mock/CPU test doubles) to the
# 30 s call timeout, so buckets span that whole range.
_LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60)

INFERENCE_STAGE_SECONDS = Histogram(
    "clonevoice_inference_stage_seconds",
    "Wall-clock time spent in each inference stage.",
    ["stage"],  # encoder | synthesizer | vocoder | save_output
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)
INFERENCE_WAIT_SECONDS = Histogram(
    "clonevoice_inference_semaphore_wait_seconds",
    "Time a request waited for the inference permit (incl. timed-out waits).",
    buckets=_LATENCY_BUCKETS,
    registry=registry,
)
INFERENCE_REJECTIONS = Counter(
    "clonevoice_inference_rejections_total",
    "Inference requests rejected or abandoned, by reason.",
    ["reason"],  # queue_full | acquire_timeout | call_timeout
    registry=registry,
)
INFERENCE_QUEUE_DEPTH = Gauge(
    "clonevoice_inference_queue_depth",
    "Requests currently waiting for the inference permit.",
    registry=registry,
)
INFERENCE_IN_FLIGHT = Gauge(
    "clonevoice_inference_in_flight",
    "1 while the inference permit is held (a forward pass may be running), else 0.",
    registry=registry,
)


def bind_gauges(
    queue_depth: Callable[[], float], in_flight: Callable[[], float]
) -> None:
    """Make the gauges read live values at scrape time instead of being pushed."""
    INFERENCE_QUEUE_DEPTH.set_function(queue_depth)
    INFERENCE_IN_FLIGHT.set_function(in_flight)


@contextmanager
def observe_stage(stage: str) -> Iterator[None]:
    """Record the duration of the wrapped block under ``stage`` (even on error)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        INFERENCE_STAGE_SECONDS.labels(stage=stage).observe(time.perf_counter() - start)
