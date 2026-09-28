"""Shared, framework-agnostic input validators used across API and schema layers."""


def require_nonblank_name(value: str) -> str:
    """Strip surrounding whitespace; raise ValueError if nothing is left.

    HARDENING_PLAN.md finding P2-L1: a bare `min_length=1` constraint still
    accepts a whitespace-only string such as `"   "`, since it counts
    characters, not content.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("Name cannot be blank")
    return stripped
