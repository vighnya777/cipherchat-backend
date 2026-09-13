"""Authentication domain services – registration, OTP, reset, credentials.

Integrity rules:
- Email and username are unique (case-insensitive)
- Registration does not claim success if verification email fails
- OTP is never logged; failed email clears pending OTP
- Reset tokens are single-use and short-lived
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from cipherchat.auth.validators import (
    is_valid_phone,
    is_valid_username,
    normalize_email,
    normalize_phone,
)
from cipherchat.config import get_config
from cipherchat.services.email import send_email_result
from cipherchat.services.email_templates import (
    create_otp_email,
    create_password_reset_email,
    create_password_reset_success_email,
    create_verification_email,
    create_welcome_email,
)
from cipherchat.services.rate_limit import add_rate_limit, is_rate_limited
from cipherchat.services.security import (
    generate_dynamic_password,
    generate_otp,
    generate_token,
    hash_password,
    password_strength_ok,
    upgrade_password_hash_if_needed,
    verify_password,
)
from cipherchat.services.storage import store

logger = logging.getLogger(__name__)

# Registration rate limit key prefix
_REG_LIMIT_PREFIX = "reg:"
_RESET_LIMIT_PREFIX = "reset:"


def _normalize_username(username: str) -> str:
    return (username or "").strip()


def _username_key(username: str) -> str:
    """Case-insensitive username key."""
    return _normalize_username(username).lower()


def resolve_user_email(username: str) -> Optional[str]:
    """Resolve username → email using case-insensitive index."""
    key = _username_key(username)
    if not key:
        return None
    # Prefer normalized index
    email = store.username_index.get(key)
    if email:
        return email
    # Fallback: scan (handles legacy mixed-case keys)
    for uname, em in list(store.username_index.items()):
        if uname.lower() == key:
            return em
    return None


def get_user(email: str) -> Optional[dict]:
    return store.users.get(normalize_email(email))


def account_exists_by_email(email: str) -> bool:
    """True if any non-deleted account exists for this email."""
    user = get_user(email)
    if not user:
        return False
    # Treat rejected as existing to prevent re-registration abuse;
    # admin must clear rejected accounts if re-reg is desired.
    return user.get("status") in ("pending", "approved", "rejected")


def account_exists_by_username(username: str) -> bool:
    return resolve_user_email(username) is not None


def account_exists_by_phone(phone: str) -> bool:
    if not phone:
        return False
    norm = normalize_phone(phone)
    if not norm:
        return False
    digits = re.sub(r"\D", "", norm)
    for u in store.users.values():
        if not isinstance(u, dict):
            continue
        prof = u.get("profile") or {}
        u_phone = str(prof.get("phone") or u.get("phone") or "").strip()
        if not u_phone:
            continue
        u_digits = re.sub(r"\D", "", normalize_phone(u_phone))
        if u_digits and (u_digits == digits or (len(u_digits) >= 10 and len(digits) >= 10 and u_digits[-10:] == digits[-10:])):
            return True
    return False


def resolve_login_identifier(identifier: str) -> Optional[str]:
    """
    Resolve a single login identifier (username, email, or phone) to account email.
    """
    value = (identifier or "").strip()
    if not value:
        return None
    if "@" in value:
        email = normalize_email(value)
        return email if get_user(email) else None

    # Check if identifier is a phone number
    phone_clean = re.sub(r"\D", "", value)
    if len(phone_clean) >= 7 and (value.startswith("+") or phone_clean == value.replace(" ", "").replace("-", "")):
        for em, u in store.users.items():
            if isinstance(u, dict):
                prof = u.get("profile") or {}
                u_phone = str(prof.get("phone") or u.get("phone") or "").strip()
                if u_phone:
                    u_digits = re.sub(r"\D", "", normalize_phone(u_phone))
                    if u_digits and (u_digits == phone_clean or (len(u_digits) >= 10 and len(phone_clean) >= 10 and u_digits[-10:] == phone_clean[-10:])):
                        return em

    return resolve_user_email(value)


def authenticate_credentials(
    username: str,
    password: str,
    email_optional: str = "",
    master_password: str = "",
    identifier: str = "",
) -> Tuple[bool, str, Optional[str]]:
    """
    Validate credentials and approval gates.
    Accepts either:
      - identifier (username OR email), or
      - legacy username + optional email
    Returns (ok, message, resolved_email).
    """
    if identifier:
        resolved = resolve_login_identifier(identifier)
        if not resolved:
            logger.info("Login failed: unknown identifier")
            return False, "Unknown username or email.", None
    else:
        resolved = resolve_user_email(username)
        if not resolved:
            logger.info("Login failed: unknown username")
            return False, "Unknown username.", None
        if email_optional and normalize_email(email_optional) != resolved:
            return False, "Username does not match email.", None

    user = get_user(resolved)
    if not user:
        return False, "No account found. Please register and verify your email.", None
    if not user.get("verified"):
        return False, "Email not verified. Check your inbox.", None
    if user.get("status") != "approved":
        return False, "Awaiting admin approval.", None

    user_pass_hash = user.get("password_hash")
    if user_pass_hash:
        if not verify_password(password, user_pass_hash):
            logger.info("Login failed: invalid password for user")
            return False, "Invalid username/password", None
        upgraded = upgrade_password_hash_if_needed(password, user_pass_hash)
        if upgraded:
            user["password_hash"] = upgraded
            store.set_user(resolved, user)
            logger.info("Password hash upgraded to Argon2 for user")
    elif not master_password or password != master_password:
        logger.info("Login failed: invalid master password path")
        return False, "Invalid master password!", None

    return True, "ok", resolved


def issue_otp(email: str) -> Tuple[bool, str, Optional[str]]:
    """
    Create OTP, store it, send email.
    Returns (ok, user_message, otp_or_none).
    OTP is returned only for internal use (e.g. tests) – never log or flash it.
    On email failure the OTP record is removed.
    """
    email = normalize_email(email)
    if is_rate_limited(email):
        return False, "Too many OTP requests. Please try again later.", None

    otp = generate_otp()
    # Invalidate any previous OTP for this email
    store.otp_storage[email] = {
        "otp": otp,
        "expires": datetime.now() + timedelta(minutes=get_config().OTP_EXPIRY_MINUTES),
        "attempts": 0,
    }

    user = store.users.get(email) or {}
    username = user.get("username") or email.split("@")[0] or "there"
    cfg = get_config()
    html = create_otp_email(
        otp,
        username=username,
        app_name="CipherChat",
        expiry_minutes=cfg.OTP_EXPIRY_MINUTES,
    )
    result = send_email_result(email, "Your CipherChat OTP Code", html)
    if not result.success:
        store.otp_storage.pop(email, None)
        logger.warning("OTP email failed for user (code=%s)", result.error_code)
        return False, result.user_message, None

    add_rate_limit(email)
    # Do NOT log the OTP value
    logger.info("OTP issued and emailed for user")
    return True, "OTP sent to your email!", otp


def verify_otp_code(email: str, entered: str) -> Tuple[bool, str, Optional[str]]:
    """Verify OTP. On success returns (True, msg, dynamic_password)."""
    email = normalize_email(email)
    entered = (entered or "").strip()

    if email not in store.otp_storage:
        return False, "OTP expired. Please login again.", None

    otp_data = store.otp_storage[email]
    if datetime.now() > otp_data["expires"]:
        store.otp_storage.pop(email, None)
        return False, "OTP expired. Please login again.", None

    max_attempts = get_config().OTP_MAX_ATTEMPTS
    if otp_data["attempts"] >= max_attempts:
        store.otp_storage.pop(email, None)
        logger.warning("OTP locked out after max attempts")
        return False, "Too many failed attempts. Please login again.", None

    if not entered or entered != otp_data["otp"]:
        otp_data["attempts"] += 1
        # Persist attempt counter for proxy/backends that don't share refs
        store.otp_storage[email] = otp_data
        return False, "Invalid OTP. Please try again.", None

    dynamic_pass = generate_dynamic_password()
    store.dynamic_passwords[email] = {
        "password": dynamic_pass,
        "expires": datetime.now()
        + timedelta(minutes=get_config().DYNAMIC_PASSWORD_EXPIRY_MINUTES),
    }
    store.otp_storage.pop(email, None)
    logger.info("OTP verified successfully")
    return True, "OTP verified! Here is your dynamic password.", dynamic_pass


def resend_otp_code(email: str) -> Tuple[bool, str]:
    email = normalize_email(email)
    if is_rate_limited(email):
        return False, "Too many requests. Please wait."

    otp = generate_otp()
    # Replace any existing OTP (invalidate old)
    store.otp_storage[email] = {
        "otp": otp,
        "expires": datetime.now() + timedelta(minutes=get_config().OTP_EXPIRY_MINUTES),
        "attempts": 0,
    }
    user = store.users.get(email) or {}
    username = user.get("username") or email.split("@")[0] or "there"
    cfg = get_config()
    html = create_otp_email(
        otp,
        username=username,
        app_name="CipherChat",
        expiry_minutes=cfg.OTP_EXPIRY_MINUTES,
    )
    result = send_email_result(email, "Your CipherChat OTP Code (Resent)", html)
    if not result.success:
        store.otp_storage.pop(email, None)
        logger.warning("Resend OTP email failed (code=%s)", result.error_code)
        return False, result.user_message

    add_rate_limit(email)
    logger.info("OTP resent successfully")
    return True, "OTP resent successfully!"


def verify_dynamic_password(email: str, entered: str) -> Tuple[bool, str]:
    email = normalize_email(email)
    entered = (entered or "").strip()
    record = store.dynamic_passwords.get(email)
    if not record:
        return False, "Dynamic password expired. Please login again."
    expires = record["expires"]
    if hasattr(expires, "tzinfo") and expires.tzinfo:
        expires = expires.replace(tzinfo=None)
    if datetime.now() > expires:
        store.dynamic_passwords.pop(email, None)
        return False, "Dynamic password expired. Please login again."
    if entered != record["password"]:
        return False, "Invalid dynamic password."
    store.dynamic_passwords.pop(email, None)
    return True, "Authentication complete."


def register_user(
    email: str,
    username: str,
    phone: str,
    password: str,
    confirm_password: str,
    base_url: str,
) -> Tuple[bool, str]:
    """
    Register a new pending user and send verification email.

    Transaction-style outcome:
    - Validate → uniqueness → create pending user → send email
    - If email fails: remove pending user + token (no orphan account claiming success)
    """
    email = normalize_email(email)
    username = _normalize_username(username)
    phone = (phone or "").strip()[:32]
    password = password or ""
    confirm_password = confirm_password or ""

    # Rate limit registration by email
    reg_key = _REG_LIMIT_PREFIX + email
    if is_rate_limited(reg_key, max_attempts=5, window_hours=1):
        return False, "Too many registration attempts. Please try again later."

    # Input validation
    if not email:
        return False, "Valid email is required"
    if not is_valid_username(username) and not re.match(
        r"^[a-zA-Z0-9_\.\-]{3,20}$", username
    ):
        return False, "Invalid username (3-20 chars, letters/numbers/_ . -)"

    # Phone validation & duplicate check (if phone provided)
    if phone:
        if not is_valid_phone(phone):
            return False, "Please enter a valid international phone number (e.g. +1234567890)"
        if account_exists_by_phone(phone):
            logger.info("Registration rejected: phone number already registered")
            return False, "Phone number is already registered"
        phone = normalize_phone(phone)

    # Duplicate checks (application level; DB unique constraints enforce under Postgres)
    if account_exists_by_username(username):
        logger.info("Registration rejected: username already taken")
        return False, "Username already taken"
    if account_exists_by_email(email):
        logger.info("Registration rejected: email already registered")
        return False, "Email already registered"

    # Password required
    if not password:
        return False, "Password is required"
    ok_strength, strength_msg = password_strength_ok(password)
    if not ok_strength:
        # Fall back to minimum length if policy is strict
        if len(password) < 6:
            return False, "Password must be at least 6 characters"
    if password != confirm_password:
        return False, "Passwords do not match"

    password_hash = hash_password(password)
    token = generate_token(24)

    user_record = {
        "username": username,
        "status": "pending",
        "verified": False,
        "role": "user",
        "created_at": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "phone": phone,
        "profile": {"avatar": None, "bio": "", "phone": phone},
        "password_hash": password_hash,
        "login_count": 0,
        "permissions": [],
    }

    # Create pending account
    try:
        store.set_user(email, user_record)
        store.username_index[_username_key(username)] = email
        # Keep original-case key for legacy lookups
        store.username_index[username] = email
        store.verification_tokens[token] = {
            "email": email,
            "expires": datetime.now() + timedelta(hours=24),
        }
    except Exception:
        logger.exception("Failed to persist registration")
        return False, "Unable to complete registration. Please try again."

    # Prefer app deep link so mobile users open CipherChat Pro directly.
    app_verify_url = f"cipherchat://verify/{token}"
    web_verify_url = f"{base_url.rstrip('/')}/verify/{token}"
    verify_url = app_verify_url  # primary button in email

    try:
        html_body = create_verification_email(verify_url, username, email)
    except Exception:
        logger.exception("Verification email template failed")
        _rollback_registration(email, username, token)
        return False, "Unable to send the verification email right now. Please try again later."

    result = send_email_result(email, "Verify your CipherChat account", html_body)
    if not result.success:
        logger.warning(
            "Registration email failed (code=%s) – rolling back pending account",
            result.error_code,
        )
        _rollback_registration(email, username, token)
        return False, result.user_message

    add_rate_limit(reg_key)
    logger.info("Registration completed; verification email sent")
    return True, "Registration submitted. Check your email to verify."


def _rollback_registration(email: str, username: str, token: str) -> None:
    """Remove partial registration state after email failure."""
    try:
        store.users.pop(email, None)
        store.username_index.pop(_username_key(username), None)
        store.username_index.pop(username, None)
        store.verification_tokens.pop(token, None)
    except Exception:
        logger.exception("Rollback of failed registration incomplete")


def confirm_email_token(token: str) -> Tuple[bool, str, Optional[str]]:
    data = store.verification_tokens.get(token)
    if not data:
        return False, "Invalid or expired verification link.", None
    expires = data["expires"]
    if hasattr(expires, "tzinfo") and expires.tzinfo:
        expires = expires.replace(tzinfo=None)
    if datetime.now() > expires:
        store.verification_tokens.pop(token, None)
        return False, "Verification link expired.", None
    email = data["email"]
    user = store.users.get(email)
    if not user:
        store.verification_tokens.pop(token, None)
        return False, "Account not found.", None
    user["verified"] = True
    store.set_user(email, user)
    store.verification_tokens.pop(token, None)
    username = user.get("username", "")
    # Welcome email is best-effort; verification already succeeded
    send_email_result(
        email, "Welcome to CipherChat", create_welcome_email(email, username)
    )
    logger.info("Email verified for user")
    return True, "Email verified. Awaiting admin approval.", email


def request_password_reset(email: str, base_url: str) -> Tuple[bool, str]:
    """
    Always return a generic success message to avoid user enumeration.
    If the user exists and email fails, still return the generic message
    but do not leave a usable token (token only stored after successful send).
    """
    email = normalize_email(email)
    generic = "If that email exists, a reset link has been sent."

    reset_key = _RESET_LIMIT_PREFIX + (email or "unknown")
    if is_rate_limited(reset_key, max_attempts=5, window_hours=1):
        # Still generic – do not reveal rate limit on specific emails
        return True, generic

    user = store.users.get(email) if email else None
    if not user:
        return True, generic

    token = generate_token(24)
    reset_url = f"{base_url.rstrip('/')}/reset-password/{token}"
    result = send_email_result(
        email,
        "Reset your CipherChat password",
        create_password_reset_email(reset_url, email),
    )
    if not result.success:
        logger.warning("Password reset email failed (code=%s)", result.error_code)
        # No token stored → cannot be used
        return True, generic

    store.reset_tokens[token] = {
        "email": email,
        "expires": datetime.now() + timedelta(hours=1),
    }
    add_rate_limit(reset_key)
    logger.info("Password reset email sent")
    return True, generic


def reset_password_with_token(
    token: str, new_password: str, confirm: str
) -> Tuple[bool, str]:
    data = store.reset_tokens.get(token)
    if not data:
        return False, "Invalid or expired reset link."
    expires = data["expires"]
    if hasattr(expires, "tzinfo") and expires.tzinfo:
        expires = expires.replace(tzinfo=None)
    if datetime.now() > expires:
        store.reset_tokens.pop(token, None)
        return False, "Reset link expired."
    if len(new_password) < 6:
        return False, "Password must be at least 6 characters"
    if new_password != confirm:
        return False, "Passwords do not match"

    email = data["email"]
    user = store.users.get(email)
    if not user:
        store.reset_tokens.pop(token, None)
        return False, "Account not found."

    user["password_hash"] = hash_password(new_password)
    store.set_user(email, user)
    # Single-use: invalidate immediately
    store.reset_tokens.pop(token, None)
    send_email_result(
        email, "Password changed", create_password_reset_success_email()
    )
    logger.info("Password reset completed")
    return True, "Password updated. You can sign in now."




def start_otp_login(email: str) -> Tuple[bool, str]:
    """
    Begin passwordless OTP login.

    Always returns a generic success message when the email shape is valid,
    to avoid account enumeration. OTP is only stored+sent for existing
    verified+approved accounts.
    """
    email = normalize_email(email)
    generic = "If that email is registered, a login code has been sent."

    if not email or "@" not in email:
        return False, "Please enter a valid email address."

    # Rate limit by email key regardless of existence
    if is_rate_limited(email):
        return False, "Too many OTP requests. Please try again later."

    user = store.users.get(email)
    if not user:
        # Do not reveal absence
        add_rate_limit(email)
        return True, generic

    status = user.get("status")
    if status == "pending":
        return False, "Awaiting admin approval."
    if status == "rejected":
        return False, "Your access request was rejected. Contact an administrator."
    if status in ("suspended", "banned"):
        return False, "Your account has been suspended."
    if status != "approved":
        return False, "Your account cannot sign in at this time."
    if not user.get("verified"):
        return False, "Email not verified. Check your inbox."

    ok, msg, _otp = issue_otp(email)
    if not ok:
        return False, msg
    # Prefer generic-ish messaging still
    return True, "OTP sent to your email!"


def complete_otp_login(email: str, entered_otp: str) -> Tuple[bool, str, Optional[str]]:
    """
    Verify OTP for passwordless login.
    On success returns (True, msg, email). Does not issue a dynamic password.
    """
    email = normalize_email(email)
    entered_otp = (entered_otp or "").strip()

    if not email or not entered_otp:
        return False, "Email and OTP are required.", None

    user = store.users.get(email)
    if not user:
        return False, "Invalid or expired OTP.", None
    if user.get("status") != "approved" or not user.get("verified"):
        return False, "Your account cannot sign in at this time.", None

    # Reuse attempt/expiry logic without creating a dynamic password
    if email not in store.otp_storage:
        return False, "OTP expired. Please request a new code.", None

    otp_data = store.otp_storage[email]
    if datetime.now() > otp_data["expires"]:
        store.otp_storage.pop(email, None)
        return False, "OTP expired. Please request a new code.", None

    max_attempts = get_config().OTP_MAX_ATTEMPTS
    if otp_data["attempts"] >= max_attempts:
        store.otp_storage.pop(email, None)
        logger.warning("OTP locked out after max attempts")
        return False, "Too many failed attempts. Please request a new code.", None

    if entered_otp != otp_data["otp"]:
        otp_data["attempts"] += 1
        store.otp_storage[email] = otp_data
        return False, "Invalid OTP. Please try again.", None

    store.otp_storage.pop(email, None)
    logger.info("OTP login verified successfully")
    return True, "Signed in successfully.", email


def log_activity(
    email: str, action: str, ip: str = "", user_agent: str = ""
) -> None:
    entry = {
        "email": email,
        "action": action,
        "timestamp": datetime.now().isoformat(),
        "ip": ip,
        "user_agent": user_agent or "Unknown",
    }
    try:
        store.backend.add_activity(entry)
    except Exception:
        # Fallback for memory proxy list
        if hasattr(store, "activity_logs") and isinstance(store.activity_logs, list):
            store.activity_logs.append(entry)
