"""SMTP email delivery service with structured error handling.

Never raises to callers. Never logs secrets (passwords, OTP, tokens).
Never reports success when delivery failed.
"""

from __future__ import annotations

import logging
import re
import smtplib
import socket
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from typing import Optional

from cipherchat.config import get_config

logger = logging.getLogger(__name__)

# Simple practical email shape check (full RFC is overkill here)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class EmailResult:
    """Structured outcome of an email send attempt."""

    success: bool
    error_code: Optional[str] = None  # config | invalid_recipient | auth | timeout | connection | smtp | unknown
    # Safe for logs only – never include credentials or message body secrets
    detail: Optional[str] = None

    @property
    def user_message(self) -> str:
        """User-facing message – never exposes internal details."""
        if self.success:
            return "Email sent successfully."
        return "Unable to send the email right now. Please try again later."


def _validate_recipient(to_email: str) -> Optional[str]:
    """Return normalized email or None if invalid."""
    if not to_email or not isinstance(to_email, str):
        return None
    # parseaddr handles "Name <email@x.com>"
    _, addr = parseaddr(to_email.strip())
    addr = (addr or to_email).strip().lower()
    if not _EMAIL_RE.match(addr) or len(addr) > 320:
        return None
    return addr


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """
    Backward-compatible wrapper.

    Returns True only when SMTP accepted the message.
    Prefer send_email_result() for new code.
    """
    return send_email_result(to_email, subject, html_body).success


def send_email_result(to_email: str, subject: str, html_body: str) -> EmailResult:
    """
    Attempt SMTP delivery with full validation and structured errors.

    - Validates SMTP config before connecting
    - Validates recipient format
    - Uses TLS (STARTTLS) with timeout
    - Logs technical failures without secrets
    - Never raises
    """
    cfg = get_config()

    # --- Configuration ---
    if not cfg.SMTP_EMAIL or not cfg.SMTP_PASSWORD:
        logger.warning(
            "Email not sent: SMTP credentials missing (recipient domain=%s subject=%r)",
            (to_email or "").split("@")[-1] if to_email else "?",
            subject[:80] if subject else "",
        )
        return EmailResult(False, "config", "SMTP credentials not configured")

    if not cfg.SMTP_HOST or not cfg.SMTP_PORT:
        logger.error("Email not sent: SMTP host/port missing")
        return EmailResult(False, "config", "SMTP host/port not configured")

    recipient = _validate_recipient(to_email)
    if not recipient:
        logger.warning("Email not sent: invalid recipient format")
        return EmailResult(False, "invalid_recipient", "Invalid recipient address")

    if not subject or not isinstance(subject, str):
        logger.warning("Email not sent: missing subject")
        return EmailResult(False, "unknown", "Missing subject")

    if not html_body:
        logger.warning("Email not sent: empty body (subject=%r)", subject[:80])
        return EmailResult(False, "unknown", "Empty body")

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject[:200]
        msg["From"] = formataddr(("CipherChat", cfg.SMTP_EMAIL))
        msg["To"] = recipient
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(cfg.SMTP_HOST, int(cfg.SMTP_PORT), timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(cfg.SMTP_EMAIL, cfg.SMTP_PASSWORD)
            server.sendmail(cfg.SMTP_EMAIL, [recipient], msg.as_string())

        # Log success without body content
        logger.info(
            "Email delivered: to_domain=%s subject=%r",
            recipient.split("@")[-1],
            subject[:80],
        )
        return EmailResult(True)

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed: %s", type(exc).__name__)
        return EmailResult(False, "auth", "SMTP authentication failed")
    except smtplib.SMTPRecipientsRefused as exc:
        logger.warning("SMTP recipients refused for domain=%s", recipient.split("@")[-1])
        return EmailResult(False, "invalid_recipient", "Recipient refused by server")
    except smtplib.SMTPSenderRefused as exc:
        logger.error("SMTP sender refused: %s", type(exc).__name__)
        return EmailResult(False, "smtp", "Sender address refused")
    except smtplib.SMTPDataError as exc:
        logger.error("SMTP data error: %s", type(exc).__name__)
        return EmailResult(False, "smtp", "SMTP data error")
    except (socket.timeout, TimeoutError) as exc:
        logger.error("SMTP timeout connecting to %s:%s", cfg.SMTP_HOST, cfg.SMTP_PORT)
        return EmailResult(False, "timeout", "SMTP connection timed out")
    except (ConnectionRefusedError, ConnectionResetError, OSError) as exc:
        logger.error(
            "SMTP connection failure to %s:%s (%s)",
            cfg.SMTP_HOST,
            cfg.SMTP_PORT,
            type(exc).__name__,
        )
        return EmailResult(False, "connection", "Could not connect to mail server")
    except smtplib.SMTPException as exc:
        logger.error("SMTP error: %s", type(exc).__name__)
        return EmailResult(False, "smtp", f"SMTP error: {type(exc).__name__}")
    except Exception as exc:
        logger.exception("Unexpected email failure: %s", type(exc).__name__)
        return EmailResult(False, "unknown", f"Unexpected error: {type(exc).__name__}")
