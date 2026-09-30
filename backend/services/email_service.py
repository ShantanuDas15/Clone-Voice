"""Outgoing transactional email: verification and password-reset messages.

Delivery is selected by ``settings.EMAIL_BACKEND`` and uses only the standard
library. Sending never raises into a request: callers run it as a background
task, and a failure is logged with the user id (never the address or the link)
so the user can simply request another message.
"""

import json
import logging
import smtplib
import urllib.request
import uuid
from email.message import EmailMessage
from urllib.parse import urlencode

from backend.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
DELIVERY_TIMEOUT_SECONDS = 10


def _link(path: str, token: str) -> str:
    """Build a link into the web app carrying `token` as a query parameter."""
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/{path}?{urlencode({'token': token})}"


def build_verification_message(to: str, name: str, token: str) -> EmailMessage:
    """Compose the address-verification email."""
    hours = settings.EMAIL_VERIFICATION_EXPIRE_HOURS
    message = EmailMessage()
    message["Subject"] = "Verify your CloneVoice email address"
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message.set_content(
        f"Hi {name},\n\n"
        "Confirm your email address to start cloning voices:\n\n"
        f"{_link('verify-email', token)}\n\n"
        f"The link expires in {hours} hours. If you did not create a CloneVoice "
        "account, you can ignore this message.\n"
    )
    return message


def build_password_reset_message(
    to: str, name: str, token: str, has_password: bool = True
) -> EmailMessage:
    """Compose the password-reset email (or the set-a-password one)."""
    minutes = settings.PASSWORD_RESET_EXPIRE_MINUTES
    message = EmailMessage()
    message["Subject"] = (
        "Reset your CloneVoice password"
        if has_password
        else "Set a password for your CloneVoice account"
    )
    ask = (
        "Someone asked to reset the password for this account. To choose a new "
        "one, open:"
        if has_password
        else "This account signs in with Google. To also sign in with your email "
        "and a password, open:"
    )
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message.set_content(
        f"Hi {name},\n\n"
        f"{ask}\n\n"
        f"{_link('reset-password', token)}\n\n"
        f"The link works once and expires in {minutes} minutes. If you did not "
        "ask for this, ignore this message: your password has not changed.\n"
    )
    return message


def _send_smtp(message: EmailMessage) -> None:
    """Deliver through the configured SMTP relay."""
    with smtplib.SMTP(
        settings.SMTP_HOST, settings.SMTP_PORT, timeout=DELIVERY_TIMEOUT_SECONDS
    ) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(message)


def _send_resend(message: EmailMessage) -> None:
    """Deliver through the Resend HTTPS API (works where SMTP is blocked)."""
    body = json.dumps(
        {
            "from": message["From"],
            "to": [message["To"]],
            "subject": message["Subject"],
            "text": message.get_content(),
        }
    ).encode()
    request = urllib.request.Request(
        RESEND_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
            # Resend sits behind Cloudflare, which rejects urllib's default UA.
            "User-Agent": "clonevoice-backend",
        },
    )
    with urllib.request.urlopen(request, timeout=DELIVERY_TIMEOUT_SECONDS):
        pass


def deliver(message: EmailMessage) -> None:
    """Send `message` through the configured backend (raises on failure)."""
    backend = settings.EMAIL_BACKEND
    if backend == "smtp":
        _send_smtp(message)
    elif backend == "resend":
        _send_resend(message)
    elif backend == "console":
        # Development only: the body contains the live token link.
        logger.info("EMAIL (console backend)\n%s", message)
    else:
        logger.warning(
            "Email not sent: EMAIL_BACKEND=disabled (subject=%r)", message["Subject"]
        )


def _safe_deliver(message: EmailMessage, user_id: uuid.UUID) -> None:
    """Deliver, logging any failure instead of raising."""
    try:
        deliver(message)
    except OSError:  # network, SMTP and HTTP errors all derive from it
        logger.exception(
            "Email delivery failed (backend=%s) — user_id=%s",
            settings.EMAIL_BACKEND,
            user_id,
        )
    except Exception:
        logger.exception("Unexpected email failure — user_id=%s", user_id)


def send_verification_email(user_id: uuid.UUID, to: str, name: str, token: str) -> None:
    """Send the verification link; never raises."""
    _safe_deliver(build_verification_message(to, name, token), user_id)


def send_password_reset_email(
    user_id: uuid.UUID, to: str, name: str, token: str, has_password: bool = True
) -> None:
    """Send the password-reset (or set-a-password) link; never raises."""
    _safe_deliver(build_password_reset_message(to, name, token, has_password), user_id)
