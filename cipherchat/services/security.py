"""
Security helpers: password hashing, browser headers, origin checks, sanitization.
"""

from __future__ import annotations

import html
import os
import re
import secrets
import string
from urllib.parse import urlparse

import bcrypt

from cipherchat.config import get_config

# Optional Argon2 – preferred when available
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHash

    _argon2 = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        salt_len=16,
    )
    HAS_ARGON2 = True
except ImportError:
    _argon2 = None
    HAS_ARGON2 = False
    VerifyMismatchError = Exception  # type: ignore
    InvalidHash = Exception  # type: ignore


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Hash a password. Prefer Argon2, fall back to bcrypt."""
    cfg = get_config()
    if cfg.PREFER_ARGON2 and HAS_ARGON2:
        return "argon2:" + _argon2.hash(plain)
    hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    return "bcrypt:" + hashed.decode("utf-8")


def verify_password(plain: str, stored: str | None) -> bool:
    """Verify a password against a stored hash (supports both schemes)."""
    if not stored or not plain:
        return False
    try:
        if stored.startswith("argon2:"):
            if not HAS_ARGON2:
                return False
            _argon2.verify(stored[7:], plain)
            return True
        if stored.startswith("bcrypt:"):
            return bcrypt.checkpw(plain.encode("utf-8"), stored[7:].encode("utf-8"))
        # Legacy bare bcrypt hashes from older versions
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    except (VerifyMismatchError, InvalidHash, ValueError, TypeError):
        return False


def password_strength_ok(password: str) -> tuple[bool, str]:
    """Basic password policy. Returns (ok, message)."""
    cfg = get_config()
    if len(password) < cfg.PASSWORD_MIN_LENGTH:
        return False, f"Password must be at least {cfg.PASSWORD_MIN_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password):
        return False, "Password must contain at least one letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
    return True, ""


# ---------------------------------------------------------------------------
# Token / OTP generators
# ---------------------------------------------------------------------------

def generate_otp(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_dynamic_password(min_len: int = 10, max_len: int = 12) -> str:
    length = secrets.randbelow(max_len - min_len + 1) + min_len
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_invite_code(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


# ---------------------------------------------------------------------------
# Input sanitization
# ---------------------------------------------------------------------------

def sanitize_message(message: str) -> str:
    """Escape HTML and trim excessive whitespace while preserving intentional newlines."""
    if not message:
        return ""
    cleaned = html.escape(message.strip())
    # Collapse runs of more than 3 newlines
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned[:4000]  # hard length cap




def needs_rehash(stored: str | None) -> bool:
    """True when stored hash should be upgraded to Argon2."""
    if not stored:
        return False
    if stored.startswith("argon2:"):
        return False
    # bcrypt or legacy bare bcrypt
    return True


def upgrade_password_hash_if_needed(plain: str, stored: str | None) -> str | None:
    """
    After successful verification, return a new Argon2 hash if the stored
    hash is bcrypt/legacy; otherwise return None (no change needed).
    """
    if not stored or not verify_password(plain, stored):
        return None
    if not needs_rehash(stored):
        return None
    return hash_password(plain)

# ---------------------------------------------------------------------------
# Browser origin & response hardening
# ---------------------------------------------------------------------------

def allowed_socket_origin(origin: str | None) -> bool:
    """Allow configured web clients, local development, and E2B previews."""
    if not origin:
        return False
    normalized = origin.rstrip("/")
    host = (urlparse(origin).hostname or "").lower()
    configured = {
        value.strip().rstrip("/")
        for value in os.getenv("SOCKET_CORS_ORIGINS", "").split(",")
        if value.strip()
    }
    return (
        normalized in configured
        or host in {"localhost", "127.0.0.1", "e2b.app"}
        or host.endswith(".e2b.app")
    )


def apply_browser_security_headers(response, is_secure: bool):
    """Apply production-oriented security headers for the server-rendered UI."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.socket.io https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "img-src 'self' data: blob: https:; "
        "media-src 'self' blob:; "
        "connect-src 'self' ws: wss: https://e2b.app https://*.e2b.app"
    )
    if is_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response
