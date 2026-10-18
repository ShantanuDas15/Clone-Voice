"""Process-wide rate-limiter singleton for SlowAPI.

Defining the ``Limiter`` here (rather than in ``main.py``) avoids the circular
import that would arise when ``api/synthesize.py`` or ``api/voice.py`` try to
import from ``main.py``, which itself imports those routers.

Usage
-----
In route modules::

    from backend.core.rate_limit import limiter

    @router.post("/")
    @limiter.limit("5/minute")
    async def my_view(request: Request, ...):
        ...

In ``main.py``::

    from backend.core.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
"""

from typing import Optional

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.core.config import settings
from backend.core.security import decode_token
from backend.services.tts_engine import engine_name_for_user


def get_client_ip(request: Request) -> str:
    """Return the client IP, honouring X-Forwarded-For only behind trusted proxies."""
    proxies = settings.TRUSTED_PROXY_COUNT
    if proxies > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        # Each trusted proxy appends the peer it saw, so the last `proxies`
        # entries are proxy-written; the one at -proxies is the real client.
        # Anything to its left is client-supplied and must not be trusted.
        if len(hops) >= proxies:
            return hops[-proxies]
    return get_remote_address(request)


def build_limiter() -> Limiter:
    """Build the process-wide limiter from settings (key func and storage URI)."""
    return Limiter(
        key_func=get_client_ip,
        enabled=settings.RATE_LIMIT_ENABLED,
        storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    )


# Separates the engine name from the client address in the synthesize rate-limit key.
_ENGINE_KEY_SEPARATOR = "|"


def _caller_engine(request: Request) -> str:
    """The engine that will serve this request's caller, read from the bearer token.

    Only the token's subject is needed, so there is no database lookup. A missing, malformed,
    expired or wrong-type token leaves the caller on ``TTS_ENGINE``: the route itself answers
    401 for those, so the limit only has to be sensible, not authoritative.
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return settings.TTS_ENGINE
    try:
        subject = decode_token(token).get("sub")
    except Exception:  # any failure to read the token means "not identifiable"
        return settings.TTS_ENGINE
    return (
        engine_name_for_user(subject)
        if isinstance(subject, str)
        else settings.TTS_ENGINE
    )


def synthesize_key(request: Request) -> str:
    """The POST /synthesize rate-limit key: the caller's engine, then the client IP (S7.4c)."""
    return f"{_caller_engine(request)}{_ENGINE_KEY_SEPARATOR}{get_client_ip(request)}"


def synthesize_limit(key: Optional[str] = None) -> str:
    """The POST /synthesize limit for the caller's engine (S7.2c, S7.4c); read on every request.

    slowapi passes the key built by ``synthesize_key``, so a canary user is limited at their own
    engine's override. Without a key (a direct call) the active ``TTS_ENGINE`` is used.
    """
    engine = settings.TTS_ENGINE
    if key and _ENGINE_KEY_SEPARATOR in key:
        engine = key.split(_ENGINE_KEY_SEPARATOR, 1)[0]
    return settings.SYNTHESIZE_RATE_LIMIT_BY_ENGINE.get(
        engine, settings.SYNTHESIZE_RATE_LIMIT
    )


limiter: Limiter = build_limiter()
