"""Keep search text out of the access log.

uvicorn logs the whole request line, query string included. The History
search box sends what the user types as `?q=`, and typed speech is personal
data (CLAUDE.md §9 logging, GENERATION_DELETE_PLAN decision 7), so the value
is replaced before the line is formatted.
"""

import logging
import re

_SEARCH_PARAM = re.compile(r"([?&]q=)[^&#\s]*")
REDACTED = "[redacted]"


def redact_search(path: str) -> str:
    """Return `path` with the value of its `q` query parameter hidden."""
    return _SEARCH_PARAM.sub(rf"\1{REDACTED}", path)


class RedactSearchFilter(logging.Filter):
    """Rewrite the request path in a uvicorn access record; never drops it."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the path argument (third of uvicorn's access-log arguments)."""
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], redact_search(args[2]), *args[3:])
        return True
