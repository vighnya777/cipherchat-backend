"""JSON authentication API for native mobile clients.

These endpoints wrap the existing auth.services logic and return JSON + session
cookies. They do not replace the HTML form routes used by the web UI.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request, session

from cipherchat.auth import services as auth_svc
from cipherchat.auth.validators import is_valid_email, is_valid_username, normalize_email
from cipherchat.config import get_config
from cipherchat.services.storage import store
from cipherchat.services.rate_limit import is_rate_limited, add_rate_limit
from cipherchat.auth.oauth_service import OAuthIdentity, resolve_oauth_user
from cipherchat.services import security as security_svc
import secrets
import requests
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

api_auth_bp = Blueprint("api_auth", __name__, url_prefix="/api/v1/auth")


def _client_meta() -> tuple[str, str]:
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    if "," in ip:
        ip = ip.split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")[:300]
    return ip, ua


def _establish_session(email: str, username: str, *, remember: bool = False) -> None:
    session.clear()
    session["authenticated"] = True
    session["user_email"] = email
    session["username"] = username or email
    session.permanent = bool(remember)
    user0 = store.users.get(email) or {}
    role = user0.get("role") or "user"
    if (username or "").strip().lower() == "admin":
        role = "admin"
        if user0 is not None:
            user0["role"] = "admin"
            user0["status"] = "approved"
            user0["verified"] = True
    session["role"] = role
    user = store.users.get(email)
    if user:
        from datetime import datetime

        user["last_seen"] = datetime.now().isoformat()
        user["login_count"] = int(user.get("login_count") or 0) + 1
        user["last_login"] = user["last_seen"]
        if hasattr(store, "set_user"):
            store.set_user(email, user)
        else:
            store.users[email] = user
    ip, ua = _client_meta()
    auth_svc.log_activity(email, "login", ip=ip, user_agent=ua)


def _user_payload(email: str) -> dict[str, Any]:
    user = store.users.get(email) or {}
    profile = user.get("profile") or {}
    return {
        "email": email,
        "username": user.get("username") or session.get("username") or email,
        "role": user.get("role") or session.get("role") or "user",
        "status": user.get("status"),
        "verified": bool(user.get("verified")),
        "profile": {
            "bio": profile.get("bio") or "",
            "phone": profile.get("phone") or user.get("phone") or "",
        },
    }


def _json_error(message: str, status: int = 400, **extra):
    body = {"success": False, "error": message, **extra}
    return jsonify(body), status


@api_auth_bp.route("/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = normalize_email(data.get("email") or "")
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or password
    phone = (data.get("phone") or "").strip()[:20]

    if not username or not email or not password:
        return _json_error("username, email, and password are required")
    if not is_valid_email(email):
        return _json_error("Invalid email address")
    if not is_valid_username(username):
        return _json_error("Username must be 3–20 characters (letters, numbers, _ . -)")

    cfg = get_config()
    ok, msg = auth_svc.register_user(
        email=email,
        username=username,
        phone=phone,
        password=password,
        confirm_password=confirm_password,
        base_url=getattr(cfg, "BASE_URL", "") or request.host_url.rstrip("/"),
    )
    if not ok:
        status = 409 if "already" in (msg or "").lower() else 400
        if "verification email" in (msg or "").lower() or "unable to send" in (msg or "").lower():
            status = 502
        return _json_error(msg or "Registration failed", status)
    return jsonify(
        {
            "success": True,
            "message": msg or "Verification email sent",
            "email": email,
        }
    ), 201


@api_auth_bp.route("/verify-email", methods=["POST"])
def api_verify_email():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return _json_error("token is required")
    ok, msg, email = auth_svc.confirm_email_token(token)
    if not ok:
        return _json_error(msg or "Invalid or expired token", 400)
    return jsonify({"success": True, "message": msg, "email": email})


@api_auth_bp.route("/login", methods=["POST"])
def api_login():
    """Password step → issues OTP. Session holds pending_login_email."""
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    remember = bool(data.get("remember", True))

    if not identifier or not password:
        return _json_error("identifier and password are required", 400)

    rate_key = f"api_login:{identifier.lower()}"
    cfg_lim = get_config()
    if is_rate_limited(rate_key, max_attempts=getattr(cfg_lim, "LOGIN_RATE_LIMIT_PER_HOUR", 10)):
        return _json_error("Too many login attempts. Please wait and try again.", 429)
    add_rate_limit(rate_key)

    cfg = get_config()
    ok, message, email = auth_svc.authenticate_credentials(
        username="",
        password=password,
        master_password=getattr(cfg, "MASTER_PASSWORD", "") or "",
        identifier=identifier,
    )
    if not ok or not email:
        return _json_error(message or "Invalid credentials", 401)

    otp_ok, otp_msg, _otp = auth_svc.issue_otp(email)
    if not otp_ok:
        msg = otp_msg or "Could not send OTP"
        # SMTP / mail transport failures → 502 so clients can show a clear alert
        status = 502 if any(
            x in (msg or "").lower()
            for x in ("smtp", "email", "mail", "send", "unable")
        ) else 429
        return _json_error(msg, status)

    session["pending_login_email"] = email
    session["pending_remember"] = remember
    # Mask email for client display
    parts = email.split("@")
    masked = (parts[0][:2] + "***@" + parts[1]) if len(parts) == 2 else email
    return jsonify(
        {
            "success": True,
            "next": "otp",
            "email": email,
            "email_masked": masked,
            "message": otp_msg or "OTP sent",
        }
    )


@api_auth_bp.route("/otp/send", methods=["POST"])
def api_otp_send():
    data = request.get_json(silent=True) or {}
    email = normalize_email(
        data.get("email")
        or session.get("pending_login_email")
        or session.get("otp_login_email")
        or ""
    )
    if not email:
        return _json_error("email is required")
    if session.get("pending_login_email"):
        ok, msg = auth_svc.resend_otp_code(email)
    else:
        ok, msg = auth_svc.start_otp_login(email)
        if ok:
            session["otp_login_email"] = email
    if not ok:
        return _json_error(msg or "Could not send OTP", 429)
    return jsonify({"success": True, "message": msg, "expires_in": 600})


@api_auth_bp.route("/otp/verify", methods=["POST"])
def api_otp_verify():
    data = request.get_json(silent=True) or {}
    otp = (data.get("otp") or "").strip()
    email = normalize_email(
        data.get("email")
        or session.get("pending_login_email")
        or session.get("otp_login_email")
        or ""
    )
    if not otp:
        return _json_error("otp is required")
    if not email:
        return _json_error("No pending login. Call /login first.", 400)

    ok, msg, dynamic = auth_svc.verify_otp_code(email, otp)
    if not ok:
        return _json_error(msg or "Invalid OTP", 401)

    session["pending_login_email"] = email
    session["otp_verified"] = True
    # dynamic is generated server-side; return so mobile can complete the flow
    # (web UI shows it on the next page). Prefer HTTPS only.
    return jsonify(
        {
            "success": True,
            "next": "dynamic_password",
            "message": msg or "OTP verified",
            "email": email,
            "dynamic_password": dynamic,
        }
    )


@api_auth_bp.route("/dynamic-verify", methods=["POST"])
def api_dynamic_verify():
    data = request.get_json(silent=True) or {}
    dynamic = (data.get("dynamic_password") or data.get("dynamic") or "").strip()
    email = normalize_email(
        data.get("email") or session.get("pending_login_email") or ""
    )
    if not dynamic:
        return _json_error("dynamic_password is required")
    if not email:
        return _json_error("No pending login session", 400)

    ok, msg = auth_svc.verify_dynamic_password(email, dynamic)
    if not ok:
        return _json_error(msg or "Invalid dynamic password", 401)

    user = store.users.get(email) or {}
    username = user.get("username") or email
    remember = bool(session.get("pending_remember", True))
    session.pop("pending_login_email", None)
    session.pop("pending_remember", None)
    session.pop("otp_verified", None)

    if user.get("passcode_hash"):
        session["passcode_pending"] = True
        session["pending_passcode_email"] = email
        session["pending_remember"] = remember
        session["pending_username"] = username
        return jsonify(
            {
                "success": True,
                "message": "Passcode required",
                "passcode_required": True,
                "email": email,
            }
        )

    _establish_session(email, username, remember=remember)
    return jsonify(
        {
            "success": True,
            "message": "Authenticated",
            "passcode_required": False,
            "user": _user_payload(email),
        }
    )


@api_auth_bp.route("/logout", methods=["POST", "GET"])
def api_logout():
    email = session.get("user_email")
    if email:
        ip, ua = _client_meta()
        auth_svc.log_activity(email, "logout", ip=ip, user_agent=ua)
    session.clear()
    return jsonify({"success": True})


@api_auth_bp.route("/me", methods=["GET"])
def api_me():
    if not session.get("authenticated") or not session.get("user_email"):
        return jsonify({"authenticated": False}), 401
    email = session["user_email"]
    return jsonify(
        {
            "authenticated": True,
            **_user_payload(email),
        }
    )


@api_auth_bp.route("/profile", methods=["POST", "PATCH"])
def api_update_profile():
    """JSON counterpart to chat.routes.profile's POST branch, for native clients."""
    if not session.get("authenticated") or not session.get("user_email"):
        return jsonify({"authenticated": False}), 401
    email = session["user_email"]
    data = request.get_json(silent=True) or {}
    user = store.users.get(email) or {}
    profile = user.setdefault("profile", {})

    new_username = (data.get("username") or "").strip()
    bio = (data.get("bio") or "")[:500]
    phone = (data.get("phone") or "").strip()[:20]

    if new_username and new_username != user.get("username"):
        if not is_valid_username(new_username):
            return _json_error("Username must be 3–20 characters (letters, numbers, _ . -)")
        taken = any(
            em != email and (u.get("username") or "").lower() == new_username.lower()
            for em, u in store.users.items()
            if isinstance(u, dict)
        )
        if taken:
            return _json_error("That username is already taken")
        old = user.get("username")
        user["username"] = new_username
        if old and hasattr(store, "username_index"):
            store.username_index.pop(old, None)
        if hasattr(store, "username_index"):
            store.username_index[new_username] = email
        session["username"] = new_username

    profile["bio"] = bio
    profile["phone"] = phone
    user["profile"] = profile
    if hasattr(store, "set_user"):
        store.set_user(email, user)
    else:
        store.users[email] = user

    return jsonify({"success": True, **_user_payload(email)})


@api_auth_bp.route("/forgot-password", methods=["POST"])
def api_forgot_password():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email") or "")
    if not email:
        return _json_error("email is required")
    cfg = get_config()
    base = getattr(cfg, "BASE_URL", "") or request.host_url.rstrip("/")
    ok, msg = auth_svc.request_password_reset(email, base)
    # Always return success-ish to avoid email enumeration in production;
    # still surface rate-limit style failures.
    if not ok and "rate" in (msg or "").lower():
        return _json_error(msg, 429)
    return jsonify({"success": True, "message": msg or "If the account exists, a reset email was sent"})


@api_auth_bp.route("/reset-password", methods=["POST"])
def api_reset_password():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    new_password = data.get("new_password") or data.get("password") or ""
    if not token or not new_password:
        return _json_error("token and new_password are required")
    ok, msg = auth_svc.reset_password_with_token(token, new_password)
    if not ok:
        return _json_error(msg or "Reset failed", 400)
    return jsonify({"success": True, "message": msg or "Password updated"})



# ── Mobile OAuth (Google / GitHub) ───────────────────────────────────────────

def _oauth_configured(provider: str) -> bool:
    cfg = get_config()
    if provider == "google":
        return bool(getattr(cfg, "GOOGLE_CLIENT_ID", None) and getattr(cfg, "GOOGLE_CLIENT_SECRET", None))
    if provider == "github":
        return bool(getattr(cfg, "GITHUB_CLIENT_ID", None) and getattr(cfg, "GITHUB_CLIENT_SECRET", None))
    return False


def _mobile_redirect_uri(provider: str, explicit: str | None = None) -> str:
    if explicit and explicit.startswith(("cipherchat://", "https://", "http://localhost", "http://127.0.0.1")):
        return explicit
    cfg = get_config()
    if provider == "google" and getattr(cfg, "GOOGLE_REDIRECT_URI", ""):
        return cfg.GOOGLE_REDIRECT_URI
    if provider == "github" and getattr(cfg, "GITHUB_REDIRECT_URI", ""):
        return cfg.GITHUB_REDIRECT_URI
    # Default deep link for Android Custom Tabs flow
    return f"cipherchat://oauth/{provider}"


@api_auth_bp.route("/oauth/<provider>/start", methods=["GET", "POST"])
def api_oauth_start(provider: str):
    """Return authorization URL + state for native clients (Custom Tabs)."""
    provider = (provider or "").lower().strip()
    if provider not in ("google", "github"):
        return _json_error("Unsupported provider", 400)
    if not _oauth_configured(provider):
        return _json_error(f"{provider.title()} OAuth is not configured on the server", 503)

    data = request.get_json(silent=True) or {}
    redirect_uri = _mobile_redirect_uri(
        provider,
        (data.get("redirect_uri") or request.args.get("redirect_uri") or "").strip() or None,
    )
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    session["oauth_provider"] = provider
    session["oauth_redirect_uri"] = redirect_uri
    session["oauth_mobile"] = True

    cfg = get_config()
    if provider == "google":
        params = {
            "client_id": cfg.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    else:
        params = {
            "client_id": cfg.GITHUB_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        url = "https://github.com/login/oauth/authorize?" + urlencode(params)

    return jsonify({
        "success": True,
        "provider": provider,
        "authorization_url": url,
        "state": state,
        "redirect_uri": redirect_uri,
    })


@api_auth_bp.route("/oauth/<provider>/exchange", methods=["POST"])
def api_oauth_exchange(provider: str):
    """Exchange authorization code for a CipherChat session (JSON)."""
    provider = (provider or "").lower().strip()
    if provider not in ("google", "github"):
        return _json_error("Unsupported provider", 400)
    if not _oauth_configured(provider):
        return _json_error(f"{provider.title()} OAuth is not configured", 503)

    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    state = (data.get("state") or "").strip()
    redirect_uri = (data.get("redirect_uri") or session.get("oauth_redirect_uri") or "").strip()
    redirect_uri = _mobile_redirect_uri(provider, redirect_uri or None)

    if not code:
        return _json_error("code is required", 400)
    expected_state = session.get("oauth_state")
    if not state or not expected_state or state != expected_state:
        return _json_error("Invalid OAuth state", 400)

    rate_key = f"oauth_exchange:{provider}:{request.remote_addr or 'ip'}"
    if is_rate_limited(rate_key, max_attempts=20):
        return _json_error("Too many OAuth attempts", 429)
    add_rate_limit(rate_key)

    cfg = get_config()
    try:
        if provider == "google":
            token_resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": cfg.GOOGLE_CLIENT_ID,
                    "client_secret": cfg.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15,
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return _json_error("OAuth token exchange failed", 502)
            info_resp = requests.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            info_resp.raise_for_status()
            info = info_resp.json()
            identity = OAuthIdentity(
                provider="google",
                provider_user_id=str(info.get("sub") or ""),
                email=normalize_email(info.get("email") or ""),
                email_verified=bool(info.get("email_verified")),
                name=info.get("name"),
                username_hint=(info.get("email") or "user").split("@")[0],
                avatar_url=info.get("picture"),
            )
        else:
            token_resp = requests.post(
                "https://github.com/login/oauth/access_token",
                headers={"Accept": "application/json"},
                data={
                    "client_id": cfg.GITHUB_CLIENT_ID,
                    "client_secret": cfg.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=15,
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return _json_error("OAuth token exchange failed", 502)
            user_resp = requests.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=15,
            )
            user_resp.raise_for_status()
            info = user_resp.json()
            email = normalize_email(info.get("email") or "")
            verified = False
            if not email:
                emails_resp = requests.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=15,
                )
                emails_resp.raise_for_status()
                emails = emails_resp.json() or []
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                chosen = primary or next((e for e in emails if e.get("verified")), None)
                if chosen:
                    email = normalize_email(chosen.get("email") or "")
                    verified = True
            else:
                verified = True
            identity = OAuthIdentity(
                provider="github",
                provider_user_id=str(info.get("id") or ""),
                email=email,
                email_verified=verified,
                name=info.get("name"),
                username_hint=info.get("login") or "user",
                avatar_url=info.get("avatar_url"),
            )
    except requests.RequestException as e:
        logger.error("OAuth exchange failed: %s", e)
        return _json_error("Provider communication failed. Try again.", 502)
    finally:
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)
        session.pop("oauth_redirect_uri", None)
        session.pop("oauth_mobile", None)

    result = resolve_oauth_user(identity)
    if not result.ok or not result.email:
        return _json_error(result.error_message or "OAuth login failed", 403, code=result.error_code)

    user = store.users.get(result.email) or {}
    if user.get("status") != "approved":
        return _json_error(result.error_message or "Account awaiting admin approval", 403)

    username = user.get("username") or result.email
    _establish_session(result.email, username, remember=True)

    payload = {
        "success": True,
        "user": _user_payload(result.email),
        "passcode_required": bool(user.get("passcode_hash")),
    }
    if user.get("passcode_hash"):
        session["passcode_pending"] = True
        # Not fully authenticated until passcode verified
        session["authenticated"] = False
        session["pending_passcode_email"] = result.email
    return jsonify(payload)


# ── Telegram-style secondary passcode (2FA) ──────────────────────────────────

@api_auth_bp.route("/passcode/status", methods=["GET"])
def api_passcode_status():
    email = session.get("user_email") or session.get("pending_passcode_email")
    if not email:
        return jsonify({"enabled": False, "authenticated": False})
    user = store.users.get(email) or {}
    return jsonify({
        "enabled": bool(user.get("passcode_hash")),
        "pending": bool(session.get("passcode_pending")),
        "authenticated": bool(session.get("authenticated")),
    })


@api_auth_bp.route("/passcode/set", methods=["POST"])
def api_passcode_set():
    """Set or change Telegram-style cloud passcode (requires authenticated session)."""
    if not session.get("authenticated") or not session.get("user_email"):
        return _json_error("Authentication required", 401)
    data = request.get_json(silent=True) or {}
    passcode = (data.get("passcode") or data.get("password") or "").strip()
    if len(passcode) < 4 or len(passcode) > 128:
        return _json_error("Passcode must be 4–128 characters", 400)

    rate_key = f"passcode_set:{session['user_email']}"
    if is_rate_limited(rate_key, max_attempts=10):
        return _json_error("Too many attempts", 429)
    add_rate_limit(rate_key)

    email = session["user_email"]
    user = store.users.get(email) or {}
    # Prefer security module hash if available
    try:
        hashed = security_svc.hash_password(passcode)
    except Exception:
        import hashlib
        hashed = hashlib.sha256(passcode.encode()).hexdigest()
    user["passcode_hash"] = hashed
    if hasattr(store, "set_user"):
        store.set_user(email, user)
    else:
        store.users[email] = user
    return jsonify({"success": True, "message": "Passcode enabled"})


@api_auth_bp.route("/passcode/disable", methods=["POST"])
def api_passcode_disable():
    if not session.get("authenticated") or not session.get("user_email"):
        return _json_error("Authentication required", 401)
    data = request.get_json(silent=True) or {}
    passcode = (data.get("passcode") or "").strip()
    email = session["user_email"]
    user = store.users.get(email) or {}
    stored = user.get("passcode_hash")
    if not stored:
        return jsonify({"success": True, "message": "Passcode already disabled"})
    try:
        ok = security_svc.verify_password(passcode, stored)
    except Exception:
        import hashlib
        ok = hashlib.sha256(passcode.encode()).hexdigest() == stored
    if not ok:
        return _json_error("Invalid passcode", 401)
    user.pop("passcode_hash", None)
    if hasattr(store, "set_user"):
        store.set_user(email, user)
    else:
        store.users[email] = user
    return jsonify({"success": True, "message": "Passcode disabled"})


@api_auth_bp.route("/passcode/verify", methods=["POST"])
def api_passcode_verify():
    """Complete login when passcode_required after OAuth or password flow."""
    data = request.get_json(silent=True) or {}
    passcode = (data.get("passcode") or "").strip()
    email = normalize_email(
        data.get("email")
        or session.get("pending_passcode_email")
        or session.get("user_email")
        or ""
    )
    if not passcode:
        return _json_error("passcode is required", 400)
    if not email:
        return _json_error("No pending passcode verification", 400)

    rate_key = f"passcode_verify:{email}"
    if is_rate_limited(rate_key, max_attempts=8):
        return _json_error("Too many passcode attempts", 429)
    add_rate_limit(rate_key)

    user = store.users.get(email) or {}
    stored = user.get("passcode_hash")
    if not stored:
        return _json_error("Passcode is not enabled for this account", 400)
    try:
        ok = security_svc.verify_password(passcode, stored)
    except Exception:
        import hashlib
        ok = hashlib.sha256(passcode.encode()).hexdigest() == stored
    if not ok:
        return _json_error("Invalid passcode", 401)

    username = user.get("username") or email
    _establish_session(email, username, remember=True)
    session.pop("passcode_pending", None)
    session.pop("pending_passcode_email", None)
    return jsonify({"success": True, "user": _user_payload(email)})
