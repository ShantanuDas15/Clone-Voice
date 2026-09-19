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

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.core.config import settings


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


limiter: Limiter = build_limiter()
