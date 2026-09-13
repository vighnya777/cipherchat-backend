"""Input validators for authentication forms."""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def is_valid_email(raw: str) -> bool:
    try:
        validate_email(raw, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False


def is_valid_username(username: str) -> bool:
    if not username or len(username) < 3 or len(username) > 20:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_.-]+$", username))


def is_valid_phone(phone: str) -> bool:
    """Loose E.164-ish validator: optional leading '+', 7-20 digits total.

    Empty string is treated as valid (phone is optional).
    """
    phone = (phone or "").strip()
    if not phone:
        return True
    return bool(re.match(r"^\+?[0-9 ()\-.]{7,20}$", phone)) and \
        sum(ch.isdigit() for ch in phone) >= 7
