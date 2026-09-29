"""Database-outage handling: classify driver errors and answer them uniformly.

Without this, any query that raised while the database was unreachable, the
auth lookup every authenticated route makes included, surfaced as a bare
``500 text/plain "Internal Server Error"``. A client cannot tell that from a
bug, and cannot know to retry. Now a transient error is a JSON ``503`` with
``Retry-After``; anything else is a JSON ``500``.
"""

import logging
import traceback
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (DBAPIError, InterfaceError, OperationalError,
                            SQLAlchemyError)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

logger = logging.getLogger(__name__)

# How long a client should wait before retrying after an outage.
DB_RETRY_AFTER_SECONDS = 5
DB_UNAVAILABLE_DETAIL = (
    "The service is temporarily unavailable. Please try again shortly."
)
INTERNAL_ERROR_DETAIL = "Internal server error"


def is_transient_db_error(error: BaseException) -> bool:
    """True when retrying later can succeed: the database is unreachable, the
    connection dropped, or the connection pool is exhausted."""
    if isinstance(error, (OperationalError, InterfaceError, PoolTimeoutError)):
        return True
    return isinstance(error, DBAPIError) and bool(error.connection_invalidated)


def db_unavailable() -> HTTPException:
    """The 503 to raise from a route that has already handled the failure."""
    return HTTPException(
        status_code=503,
        detail=DB_UNAVAILABLE_DETAIL,
        headers={"Retry-After": str(DB_RETRY_AFTER_SECONDS)},
    )


def _describe(error: SQLAlchemyError, include_message: bool) -> str:
    """A log-safe summary. Postgres error text can embed row values (a
    duplicate-key error quotes the email), so the message is only included for
    transient errors, which describe the connection, never the data."""
    orig: Optional[BaseException] = getattr(error, "orig", None)
    parts = [type(error).__name__]
    if orig is not None:
        parts.append(f"orig={type(orig).__name__}")
        pgcode = getattr(orig, "pgcode", None)
        if pgcode:
            parts.append(f"pgcode={pgcode}")
    if include_message:
        message = str(orig if orig is not None else error).strip()
        parts.append(f"detail={message.splitlines()[0][:200]}" if message else "")
    return " ".join(p for p in parts if p)


async def handle_db_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
    """Answer a database error that no route handled."""
    where = f"{request.method} {request.url.path}"
    if is_transient_db_error(error):
        logger.error(
            "Database unavailable during %s: %s", where, _describe(error, True)
        )
        return JSONResponse(
            status_code=503,
            content={"detail": DB_UNAVAILABLE_DETAIL},
            headers={"Retry-After": str(DB_RETRY_AFTER_SECONDS)},
        )
    # The stack frames, without the exception text (see _describe).
    frames = "".join(traceback.format_tb(error.__traceback__))
    logger.error(
        "Unhandled database error during %s: %s\n%s",
        where,
        _describe(error, False),
        frames,
    )
    return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


def register_db_error_handlers(app: FastAPI) -> None:
    """Install the handler for every SQLAlchemy error on `app`."""
    app.add_exception_handler(SQLAlchemyError, handle_db_error)
