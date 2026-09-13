"""
Secure OAuth account resolution for CipherChat (store-backed).

Policy:
- Require verified provider email
- Match existing account by oauth provider+id, then by email
- Do not create a second account for the same email
- New OAuth users are created as pending + verified (admin approval still required)
- Rejected / unapproved / missing accounts are denied with controlled messages
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from flask import url_for

from cipherchat.auth.validators import normalize_email
from cipherchat.services.storage import store

logger = logging.getLogger(__name__)


@dataclass
class OAuthIdentity:
    provider: str
    provider_user_id: str
    email: str
    email_verified: bool
    name: Optional[str] = None
    username_hint: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class OAuthResult:
    ok: bool
    email: Optional[str] = None
    is_new_user: bool = False
    error_message: Optional[str] = None
    error_code: Optional[str] = None


def safe_next_redirect(next_page: Optional[str], fallback_endpoint: str = "chat.chat") -> str:
    """Only allow relative same-origin paths (no open redirects)."""
    if not next_page:
        return url_for(fallback_endpoint)
    next_page = str(next_page).strip()
    if not next_page.startswith("/") or next_page.startswith("//") or "\\" in next_page:
        return url_for(fallback_endpoint)
    lowered = next_page.lower()
    if "javascript:" in lowered or "data:" in lowered:
        return url_for(fallback_endpoint)
    return next_page


def _deny(code: str, message: str) -> OAuthResult:
    logger.warning("OAuth deny [%s]: %s", code, message)
    return OAuthResult(ok=False, error_code=code, error_message=message)


def _unique_username(base: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", (base or "user"))[:18] or "user"
    if len(base) < 3:
        base = (base + "user")[:3]
    username = base
    counter = 1
    while username.lower() in {k.lower() for k in store.username_index.keys()} or any(
        (u.get("username") or "").lower() == username.lower() for u in store.users.values()
    ):
        suffix = str(counter)
        username = f"{base[: max(1, 20 - len(suffix))]}{suffix}"
        counter += 1
        if counter > 500:
            import secrets
            username = f"u{secrets.token_hex(4)}"
            break
    return username


def _find_by_oauth(provider: str, provider_user_id: str) -> Optional[str]:
    """Return account email if this OAuth identity is already linked."""
    pid = str(provider_user_id)
    for email, user in (store.users.items() if hasattr(store.users, "items") else []):
        if user.get("oauth_provider") == provider and str(user.get("oauth_id") or "") == pid:
            return email
    return None


def _status_message(user: dict) -> Optional[str]:
    status = user.get("status")
    if status == "approved":
        return None
    if status == "pending":
        return "Awaiting admin approval."
    if status == "rejected":
        return "Your access request was rejected. Contact an administrator."
    if status == "suspended" or status == "banned":
        return "Your account has been suspended."
    return "Your account cannot sign in at this time."


def resolve_oauth_user(identity: OAuthIdentity) -> OAuthResult:
    provider = (identity.provider or "").strip().lower()
    provider_user_id = str(identity.provider_user_id or "").strip()
    email = normalize_email(identity.email)

    if provider not in ("google", "github"):
        return _deny("invalid_provider", "Unsupported OAuth provider.")
    if not provider_user_id:
        return _deny("missing_provider_id", "OAuth provider did not return a stable user id.")
    if not email:
        return _deny(
            "missing_email",
            "Could not retrieve your email from the provider. "
            "Make a verified email available and try again.",
        )
    if not identity.email_verified:
        return _deny(
            "unverified_email",
            "Your provider email is not verified. Verify it with the provider, then try again.",
        )

    # A) Existing OAuth link
    linked_email = _find_by_oauth(provider, provider_user_id)
    if linked_email:
        user = store.users.get(linked_email)
        if not user:
            return _deny("account_missing", "Linked account no longer exists.")
        blocked = _status_message(user)
        if blocked:
            return _deny("not_approved", blocked)
        return OAuthResult(ok=True, email=linked_email, is_new_user=False)

    # B) Existing local account by email
    user = store.users.get(email)
    if user:
        # Conflict: email already linked to a different OAuth identity
        existing_provider = user.get("oauth_provider")
        existing_id = str(user.get("oauth_id") or "")
        if existing_provider and existing_id and (
            existing_provider != provider or existing_id != provider_user_id
        ):
            return _deny(
                "email_linked_other",
                "This email already belongs to an account linked with a different sign-in method.",
            )

        # Link OAuth fields
        user["oauth_provider"] = provider
        user["oauth_id"] = provider_user_id
        if identity.avatar_url and not (user.get("profile") or {}).get("avatar"):
            profile = dict(user.get("profile") or {})
            profile["avatar"] = identity.avatar_url
            user["profile"] = profile
        # OAuth with verified email proves ownership
        user["verified"] = True
        store.set_user(email, user)

        blocked = _status_message(user)
        if blocked:
            # Linking succeeded but login not allowed until approved
            return _deny("not_approved", blocked)
        return OAuthResult(ok=True, email=email, is_new_user=False)

    # C) New user → pending access request (admin approval required)
    username = _unique_username(identity.username_hint or email.split("@")[0])
    user_record = {
        "username": username,
        "status": "pending",
        "verified": True,  # provider verified the email
        "role": "user",
        "created_at": datetime.now().isoformat(),
        "last_seen": datetime.now().isoformat(),
        "profile": {
            "avatar": identity.avatar_url,
            "bio": "",
            "phone": "",
            "display_name": identity.name or "",
        },
        "password_hash": None,
        "login_count": 0,
        "permissions": [],
        "oauth_provider": provider,
        "oauth_id": provider_user_id,
    }
    try:
        store.set_user(email, user_record)
        store.username_index[username.lower()] = email
        store.username_index[username] = email
    except Exception:
        logger.exception("Failed to create OAuth user")
        return _deny("create_failed", "Could not create account. Please try again later.")

    logger.info("OAuth pending account created via %s", provider)
    return OAuthResult(
        ok=False,  # not login-ready until approved
        email=email,
        is_new_user=True,
        error_code="pending",
        error_message="Account created. Awaiting admin approval before you can sign in.",
    )
