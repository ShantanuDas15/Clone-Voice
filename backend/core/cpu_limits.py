"""Detect the container CPU limit so torch doesn't oversubscribe it.

HARDENING_PLAN.md finding P2-L11: PyTorch sizes its CPU thread pool from the
*host's* core count and ignores a cgroup CPU quota (`docker run --cpus=2`,
Kubernetes CPU limits). Measured on this project's vocoder under a 2-CPU quota
on a 24-core host: 75.4 s with torch's default threads against 10.6 s with two,
and event-loop lag of 88 ms against 1.2 ms. This module reads the quota so the
thread count can follow it.

Supports cgroup v2 (`cpu.max`) and v1 (`cpu.cfs_quota_us` / `cpu.cfs_period_us`)
and takes the tightest quota found on the process's own cgroup and every parent
up to the root, since a pod- or slice-level limit constrains its children too.
Everything is read from injectable paths so it can be tested without a container.
"""

import logging
import math
import os
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

CGROUP_ROOT = "/sys/fs/cgroup"
PROC_CGROUP = "/proc/self/cgroup"


def _read(path: str) -> Optional[str]:
    """Return a small file's stripped text, or ``None`` if unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _quota_cpus(quota: str, period: str) -> Optional[float]:
    """Return quota/period as a CPU count; ``None`` if unlimited or malformed."""
    try:
        quota_us, period_us = int(quota), int(period)
    except ValueError:  # cgroup v2 writes "max" when there is no limit
        return None
    if quota_us <= 0 or period_us <= 0:  # cgroup v1 writes -1 for no limit
        return None
    return quota_us / period_us


def _v2_limit(directory: str) -> Optional[float]:
    """Read a cgroup v2 ``cpu.max`` ("<quota|max> <period>") in ``directory``."""
    parts = (_read(os.path.join(directory, "cpu.max")) or "").split()
    return _quota_cpus(parts[0], parts[1]) if len(parts) == 2 else None


def _v1_limit(directory: str) -> Optional[float]:
    """Read cgroup v1 ``cpu.cfs_quota_us`` and ``cpu.cfs_period_us``."""
    quota = _read(os.path.join(directory, "cpu.cfs_quota_us"))
    period = _read(os.path.join(directory, "cpu.cfs_period_us"))
    return _quota_cpus(quota, period) if quota and period else None


def _tightest(start: str, stop: str, reader) -> Optional[float]:
    """Return the smallest limit from ``start`` up through its parents to ``stop``."""
    limits = []
    directory = os.path.normpath(start)
    stop = os.path.normpath(stop)
    while True:
        limit = reader(directory)
        if limit is not None:
            limits.append(limit)
        if directory == stop or not directory.startswith(stop) or directory == "/":
            break
        directory = os.path.dirname(directory)
    return min(limits) if limits else None


def detect_cpu_limit(
    cgroup_root: str = CGROUP_ROOT, proc_cgroup: str = PROC_CGROUP
) -> Optional[float]:
    """Return the CPU limit (in CPUs, possibly fractional) or ``None`` if unlimited."""
    text = _read(proc_cgroup)
    if not text:
        return None
    limits = []
    for line in text.splitlines():
        _, controllers, path = (line.split(":", 2) + ["", ""])[:3]
        relative = path.lstrip("/")
        if controllers == "":  # cgroup v2 unified hierarchy ("0::/path")
            limit = _tightest(
                os.path.join(cgroup_root, relative), cgroup_root, _v2_limit
            )
        elif "cpu" in controllers.split(","):  # cgroup v1 cpu controller
            mounts = [
                os.path.join(cgroup_root, name)
                for name in ("cpu,cpuacct", "cpu", "cpuacct,cpu")
            ]
            mount = next((m for m in mounts if os.path.isdir(m)), mounts[0])
            limit = _tightest(os.path.join(mount, relative), mount, _v1_limit)
        else:
            continue
        if limit is not None:
            limits.append(limit)
    return min(limits) if limits else None


def _usable_cores() -> int:
    """Return the number of CPUs this process may be scheduled on."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not available on every platform
        return os.cpu_count() or 1


def resolve_thread_count(
    configured: int,
    env: Optional[Mapping[str, str]] = None,
    cgroup_root: str = CGROUP_ROOT,
    proc_cgroup: str = PROC_CGROUP,
    cores: Optional[int] = None,
) -> Optional[int]:
    """Return the torch thread count to set, or ``None`` to leave torch's default.

    An explicit ``configured`` value (> 0) always wins. Otherwise an operator's
    own ``OMP_NUM_THREADS`` is respected, and the cgroup CPU limit is used only
    when it is tighter than the cores the process can already see.
    """
    if configured > 0:
        return configured
    if "OMP_NUM_THREADS" in (os.environ if env is None else env):
        return None
    limit = detect_cpu_limit(cgroup_root, proc_cgroup)
    if limit is None:
        return None
    threads = max(1, math.ceil(limit))
    return threads if threads < (cores or _usable_cores()) else None
