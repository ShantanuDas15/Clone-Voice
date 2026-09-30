"""Outgoing transactional email: verification and password-reset messages.

Delivery is selected by ``settings.EMAIL_BACKEND`` and uses only the standard
library. Sending never raises into a request: callers run it as a background
task, and a failure is logged with the user id (never the address or the link)
so the user can simply request another message.
"""

import html
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
    """Build a link into the web app carrying `token` in the URL fragment.

    A fragment (`#token=...`) is never sent to a server, so the token stays out
    of access logs and `Referer` headers; the web app reads it in the browser
    and removes it from the address bar.
    """
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/{path}#{urlencode({'token': token})}"


def _html_body(name: str, intro: str, button: str, url: str, footnote: str) -> str:
    """Render the HTML alternative: one call-to-action button plus the raw link."""
    e = html.escape
    return f"""<!doctype html>
<html>
<body style="margin:0;padding:24px;background:#f4f5f7;">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:8px;\
padding:32px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;\
font-size:15px;line-height:1.5;color:#1f2933;">
<p style="margin:0 0 16px;font-size:20px;font-weight:600;">CloneVoice</p>
<p style="margin:0 0 12px;">Hi {e(name)},</p>
<p style="margin:0 0 24px;">{e(intro)}</p>
<p style="margin:0 0 24px;"><a href="{e(url)}" style="display:inline-block;\
padding:12px 24px;background:#2563eb;color:#ffffff;text-decoration:none;\
border-radius:6px;font-weight:600;">{e(button)}</a></p>
<p style="margin:0 0 8px;font-size:13px;color:#52606d;">Or copy this link into \
your browser:</p>
<p style="margin:0 0 24px;font-size:13px;word-break:break-all;color:#52606d;">\
{e(url)}</p>
<p style="margin:0;font-size:13px;color:#52606d;">{e(footnote)}</p>
</div>
</body>
</html>
"""


def _compose(
    to: str,
    subject: str,
    name: str,
    intro: str,
    button: str,
    url: str,
    footnote: str,
) -> EmailMessage:
    """Build a multipart message: a plain-text part and an HTML alternative."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.EMAIL_FROM
    message["To"] = to
    message.set_content(f"Hi {name},\n\n{intro}\n\n{url}\n\n{footnote}\n")
    message.add_alternative(
        _html_body(name, intro, button, url, footnote), subtype="html"
    )
    return message


def build_verification_message(to: str, name: str, token: str) -> EmailMessage:
    """Compose the address-verification email."""
    hours = settings.EMAIL_VERIFICATION_EXPIRE_HOURS
    return _compose(
        to,
        "Verify your CloneVoice email address",
        name,
        "Confirm your email address to start cloning voices:",
        "Verify email address",
        _link("verify-email", token),
        f"The link expires in {hours} hours. If you did not create a CloneVoice "
        "account, you can ignore this message.",
    )


def build_password_reset_message(
    to: str, name: str, token: str, has_password: bool = True
) -> EmailMessage:
    """Compose the password-reset email (or the set-a-password one)."""
    minutes = settings.PASSWORD_RESET_EXPIRE_MINUTES
    if has_password:
        subject = "Reset your CloneVoice password"
        intro = (
            "Someone asked to reset the password for this account. "
            "To choose a new one, use the link below:"
        )
        button = "Reset password"
    else:
        subject = "Set a password for your CloneVoice account"
        intro = (
            "This account signs in with Google. To also sign in with your "
            "email and a password, use the link below:"
        )
        button = "Set password"
    return _compose(
        to,
        subject,
        name,
        intro,
        button,
        _link("reset-password", token),
        f"The link works once and expires in {minutes} minutes. If you did not "
        "ask for this, ignore this message: your password has not changed.",
    )


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
            "text": message.get_body(("plain",)).get_content(),
            "html": message.get_body(("html",)).get_content(),
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
