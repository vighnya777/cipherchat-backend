"""Input validators for authentication forms."""

from __future__ import annotations

import re

from email_validator import EmailNotValidError, validate_email

TEMP_EMAIL_DOMAINS = {
    "10minutemail.com",
    "guerrillamail.com",
    "mailinator.com",
    "tempmail.com",
    "tmpmail.org",
    "yopmail.com",
    "dispostable.com",
    "trashmail.com",
    "maildrop.cc",
    "anonbox.net",
    "sharklasers.com",
}


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def is_temp_email(raw: str) -> bool:
    email = normalize_email(raw)
    if not email or "@" not in email:
        return False
    domain = email.split("@", 1)[1].strip()
    return domain in TEMP_EMAIL_DOMAINS or domain.endswith(".tempmail.com")


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


def normalize_phone(phone: str) -> str:
    """Normalize phone number: trim, keep leading '+' if present, strip other non-digits."""
    if not phone:
        return ""
    phone = phone.strip()
    has_plus = phone.startswith("+")
    digits = re.sub(r"\D", "", phone)
    return ("+" + digits) if has_plus else digits


def is_valid_phone(phone: str) -> bool:
    """
    Validate international phone number format:
    E.164-compatible: optional leading '+', followed by 7 to 15 digits.
    """
    if not phone:
        return False
    norm = normalize_phone(phone)
    digits = re.sub(r"\D", "", norm)
    if len(digits) < 7 or len(digits) > 15:
        return False
    return bool(re.match(r"^\+?[1-9]\d{6,14}$", norm))

