"""Guards HARDENING_PLAN.md finding P2-H2: advisory-fixed dependency floors."""

import re
from importlib.metadata import version
from pathlib import Path
from typing import Dict, Tuple

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
MINIMUMS: Dict[str, Tuple[int, ...]] = {
    "python-multipart": (0, 0, 31),
    "starlette": (1, 3, 1),
    "authlib": (1, 6, 12),
    "torch": (2, 6, 0),
    "python-dotenv": (1, 2, 2),
}


def _parse(ver: str) -> Tuple[int, ...]:
    """Convert a release string like '2.13.0+cpu' into a comparable tuple."""
    return tuple(int(part) for part in re.findall(r"\d+", ver.split("+")[0])[:3])


def _pins() -> Dict[str, str]:
    """Return {name: version} for every exact pin in requirements.txt."""
    pins = {}
    for line in (BACKEND_DIR / "requirements.txt").read_text().splitlines():
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[.*\])?==([^\s#;]+)", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


@pytest.mark.parametrize("name,minimum", MINIMUMS.items())
def test_requirements_pin_meets_advisory_floor(name, minimum):
    """The pinned version must be at or above the advisory-fixed release."""
    assert _parse(_pins()[name]) >= minimum


@pytest.mark.parametrize("name,minimum", MINIMUMS.items())
def test_installed_version_meets_advisory_floor(name, minimum):
    """The installed package (what the suite actually runs on) must too."""
    assert _parse(version(name)) >= minimum


def test_fastapi_release_supports_pinned_starlette():
    """fastapi must not cap starlette below the pinned, advisory-fixed one."""
    assert _parse(_pins()["fastapi"]) >= (0, 136, 0)
