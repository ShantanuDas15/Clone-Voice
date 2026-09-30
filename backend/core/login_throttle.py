"""Per-account throttle on failed password checks (SEC-3).

The per-IP limit on /login stops one client; it does nothing against many
clients guessing one account. This counts *failures* per account, in the same
storage and strategy as the rest of the rate limiting (so a shared Redis
applies across replicas, and ``limiter.reset()`` clears it in tests).

An address is identified by its salted hash (`hash_email_for_logging`), so the
raw email never reaches the store, and an address with no account is throttled
exactly like a real one: the throttle cannot be used to learn who is
registered. Trade-off, accepted: someone who knows an address can lock that
account's password sign-in for the window (password reset and Google sign-in
are unaffected).
"""

import math
import time

from fastapi import HTTPException, status
from limits import parse

from backend.core.config import settings
from backend.core.rate_limit import limiter
from backend.core.security import hash_email_for_logging

_NAMESPACE = "password-failures"


def email_identity(email: str) -> str:
    """Identify a login attempt's target without storing the address."""
    return f"email:{hash_email_for_logging(email)}"


def user_identity(user_id: object) -> str:
    """Identify a signed-in user (for re-authentication checks)."""
    return f"user:{user_id}"


def _retry_after(item, identity: str) -> int:
    """Seconds until the failure window resets (at least 1)."""
    reset_time, _ = limiter.limiter.get_window_stats(item, _NAMESPACE, identity)
    return max(1, math.ceil(reset_time - time.time()))


def ensure_not_throttled(identity: str) -> None:
    """Raise 429 (with Retry-After) once `identity` has used up its failures."""
    if not limiter.enabled:
        return
    item = parse(settings.AUTH_PASSWORD_FAILURE_LIMIT)
    if not limiter.limiter.test(item, _NAMESPACE, identity):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Try again later.",
            headers={"Retry-After": str(_retry_after(item, identity))},
        )


def record_failure(identity: str) -> None:
    """Count one failed password check against `identity`."""
    if limiter.enabled:
        limiter.limiter.hit(
            parse(settings.AUTH_PASSWORD_FAILURE_LIMIT), _NAMESPACE, identity
        )


def clear_failures(identity: str) -> None:
    """Forget `identity`'s failures after a successful check."""
    if limiter.enabled:
        limiter.limiter.clear(
            parse(settings.AUTH_PASSWORD_FAILURE_LIMIT), _NAMESPACE, identity
        )
