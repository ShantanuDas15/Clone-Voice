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

from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.core.config import settings

limiter: Limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
)
