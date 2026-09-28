"""Unit tests for backend.core.validators (HARDENING_PLAN.md finding P2-L1)."""

import pytest

from backend.core.validators import require_nonblank_name


@pytest.mark.parametrize("value", ["", "   ", "\t\n ", " "])
def test_require_nonblank_name_rejects_blank(value: str):
    """A string that is empty or whitespace-only must raise ValueError."""
    with pytest.raises(ValueError):
        require_nonblank_name(value)


def test_require_nonblank_name_strips_surrounding_whitespace():
    """Surrounding whitespace must be stripped from an otherwise valid name."""
    assert require_nonblank_name("  Alice  ") == "Alice"


def test_require_nonblank_name_preserves_internal_whitespace():
    """Whitespace between words must not be collapsed or removed."""
    assert require_nonblank_name("  Alice   Bob  ") == "Alice   Bob"
