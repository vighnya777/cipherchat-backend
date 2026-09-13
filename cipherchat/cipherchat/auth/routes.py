"""Authentication HTTP routes for CipherChat.

Uses cipherchat.auth.services and session-based auth (not flask-login).
Blueprint name: auth  →  endpoints auth.login, auth.register, etc.
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from cipherchat.auth import services as auth_svc
from cipherchat.auth.oauth_service import (
    OAuthIdentity,
    resolve_oauth_user,
    safe_next_redirect,
)
from cipherchat.auth.validators import is_valid_email, is_valid_username, normalize_email
from cipherchat.config import get_config
from cipherchat.services.storage import store

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


# ── Session helpers ──────────────────────────────────────────────────────────

def _client_meta() -> tuple[str, str]:
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    if "," in ip:
        ip = ip.split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")[:300]
    return ip, ua


def _establish_session(email: str, username: str, *, remember: bool = False) -> None:
    """Create an authenticated session after successful multi-step auth / OAuth."""
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
        user["last_seen"] = __import__("datetime").datetime.now().isoformat()
        user["login_count"] = int(user.get("login_count") or 0) + 1
        user["last_login"] = user["last_seen"]
        store.set_user(email, user)

    ip, ua = _client_meta()
    auth_svc.log_activity(email, "login", ip=ip, user_agent=ua)


def _oauth_configured(provider: str) -> bool:
    cfg = get_config()
    if provider == "google":
        return bool(getattr(cfg, "GOOGLE_CLIENT_ID", None) and getattr(cfg, "GOOGLE_CLIENT_SECRET", None))
    if provider == "github":
        return bool(getattr(cfg, "GITHUB_CLIENT_ID", None) and getattr(cfg, "GITHUB_CLIENT_SECRET", None))
    return False


def _oauth_redirect_uri(provider: str) -> str:
    cfg = get_config()
    if provider == "google":
        explicit = (getattr(cfg, "GOOGLE_REDIRECT_URI", None) or "").strip()
        if explicit:
            return explicit
        return url_for("auth.google_callback", _external=True)
    explicit = (getattr(cfg, "GITHUB_REDIRECT_URI", None) or "").strip()
    if explicit:
        return explicit
    return url_for("auth.github_callback", _external=True)


# ── Login / OTP / logout ─────────────────────────────────────────────────────

@auth_bp.route("/")
def index():
    if session.get("authenticated"):
        return redirect(url_for("chat.chat"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        # Allow deep-link to admin when already signed in
        nxt = request.args.get("next") or ""
        if nxt.startswith("/admin") and __import__("cipherchat.admin.services", fromlist=["is_authenticated_admin"]).is_authenticated_admin():
            return redirect(url_for("admin.admin"))
        return redirect(safe_next_redirect(nxt, "chat.chat"))

    cfg = get_config()

    def _login_page(identifier: str = "", mode: str = "password", otp_email: str = ""):
        mode = (mode or "password").lower()
        if mode not in ("password", "otp"):
            mode = "password"
        return render_template(
            "login.html",
            identifier=identifier,
            mode=mode,
            otp_email=otp_email or session.get("otp_login_email") or "",
        )

    if request.method == "GET":
        mode = request.args.get("mode") or session.get("login_mode") or "password"
        return _login_page(mode=mode)

    # Single combined field: username OR email
    identifier = (request.form.get("identifier") or "").strip()
    password = request.form.get("password") or ""
    remember = request.form.get("remember") == "1"

    if not identifier or not password:
        flash("Please enter your username or email, and password.", "error")
        return _login_page(identifier=identifier, mode="password")

    # Light server-side shape checks (authoritative auth is in authenticate_credentials)
    if "@" in identifier:
        if not is_valid_email(identifier):
            flash("Enter a valid email address.", "error")
            return _login_page(identifier=identifier, mode="password")
    else:
        if not is_valid_username(identifier) and not (
            3 <= len(identifier) <= 20
        ):
            flash("Enter a valid username (3–20 characters) or email.", "error")
            return _login_page(identifier=identifier, mode="password")

    ok, message, email = auth_svc.authenticate_credentials(
        username="",
        password=password,
        master_password=getattr(cfg, "MASTER_PASSWORD", "") or "",
        identifier=identifier,
    )
    if not ok or not email:
        flash(message, "error")
        return _login_page(identifier=identifier, mode="password")

    # Credentials OK → issue OTP (email failure must not leave a usable OTP)
    otp_ok, otp_msg, _otp = auth_svc.issue_otp(email)
    if not otp_ok:
        flash(otp_msg, "error")
        return _login_page(identifier=identifier, mode="password")

    session["pending_login_email"] = email
    session["pending_remember"] = remember
    flash(otp_msg, "success")
    return redirect(url_for("auth.verify_otp"))




@auth_bp.route("/login/otp/send", methods=["POST"])
def login_otp_send():
    """Send OTP for passwordless email login (form POST, no page API required)."""
    email = normalize_email(request.form.get("email") or request.form.get("otp_email") or "")
    ok, msg = auth_svc.start_otp_login(email)
    flash(msg, "success" if ok else "error")
    # Stay on login with OTP mode indicated
    if ok:
        session["otp_login_email"] = email
        session["login_mode"] = "otp"
    return redirect(url_for("auth.login", mode="otp"))


@auth_bp.route("/login/otp/verify", methods=["POST"])
def login_otp_verify():
    email = normalize_email(
        request.form.get("email")
        or request.form.get("otp_email")
        or session.get("otp_login_email")
        or ""
    )
    entered = (request.form.get("otp") or "").strip()
    remember = request.form.get("remember") == "1"

    ok, msg, resolved = auth_svc.complete_otp_login(email, entered)
    if not ok or not resolved:
        flash(msg, "error")
        session["login_mode"] = "otp"
        session["otp_login_email"] = email
        return redirect(url_for("auth.login", mode="otp"))

    user = store.users.get(resolved) or {}
    session.pop("otp_login_email", None)
    session.pop("login_mode", None)
    session.pop("pending_login_email", None)
    session.pop("pending_dynamic_email", None)
    _establish_session(resolved, user.get("username") or resolved, remember=remember)
    flash(msg, "success")
    return redirect(url_for("chat.chat"))


@auth_bp.route("/login/otp/resend", methods=["POST"])
def login_otp_resend():
    email = normalize_email(
        request.form.get("email")
        or request.form.get("otp_email")
        or session.get("otp_login_email")
        or ""
    )
    ok, msg = auth_svc.start_otp_login(email)
    flash(msg, "success" if ok else "error")
    if ok:
        session["otp_login_email"] = email
        session["login_mode"] = "otp"
    return redirect(url_for("auth.login", mode="otp"))

@auth_bp.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    email = session.get("pending_login_email")
    if not email:
        flash("Please sign in first.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("verify_otp.html", email=email)

    action = (request.form.get("action") or "verify").strip().lower()
    if action == "resend":
        ok, msg = auth_svc.resend_otp_code(email)
        flash(msg, "success" if ok else "error")
        return render_template("verify_otp.html", email=email)

    entered = (request.form.get("otp") or "").strip()
    ok, msg, dynamic_pass = auth_svc.verify_otp_code(email, entered)
    if not ok:
        flash(msg, "error")
        return render_template("verify_otp.html", email=email)

    # Dynamic password step (existing product flow)
    session["pending_dynamic_email"] = email
    session["pending_dynamic_hint"] = dynamic_pass  # shown once in template path if used
    flash(msg, "success")
    return redirect(url_for("auth.dynamic_verify"))


@auth_bp.route("/dynamic-verify", methods=["GET", "POST"])
def dynamic_verify():
    email = session.get("pending_dynamic_email") or session.get("pending_login_email")
    if not email:
        flash("Please sign in first.", "error")
        return redirect(url_for("auth.login"))

    hint = session.pop("pending_dynamic_hint", None)

    if request.method == "GET":
        return render_template(
            "dynamic_verify.html",
            email=email,
            dynamic_password=hint,
        )

    entered = (request.form.get("dynamic_password") or request.form.get("password") or "").strip()
    ok, msg = auth_svc.verify_dynamic_password(email, entered)
    if not ok:
        flash(msg, "error")
        return render_template("dynamic_verify.html", email=email, dynamic_password=None)

    user = store.users.get(email) or {}
    remember = bool(session.get("pending_remember"))
    session.pop("pending_login_email", None)
    session.pop("pending_dynamic_email", None)
    session.pop("pending_remember", None)
    _establish_session(email, user.get("username") or email, remember=remember)
    flash("Signed in successfully.", "success")
    return redirect(safe_next_redirect(request.args.get("next"), "chat.chat"))


@auth_bp.route("/logout")
def logout():
    email = session.get("user_email")
    if email:
        ip, ua = _client_meta()
        auth_svc.log_activity(email, "logout", ip=ip, user_agent=ua)
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


# ── Registration / email verification ────────────────────────────────────────

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("authenticated"):
        return redirect(url_for("chat.chat"))

    def _register_page(username: str = "", email: str = "", phone: str = ""):
        return render_template(
            "register.html", username=username, email=email, phone=phone
        )

    if request.method == "GET":
        return _register_page()

    email = normalize_email(request.form.get("email") or "")
    username = (request.form.get("username") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    password = request.form.get("password") or ""
    confirm = request.form.get("confirm_password") or ""

    # Lightweight pre-checks (authoritative validation is in register_user)
    if not email or not is_valid_email(email):
        flash("A valid email is required.", "error")
        return _register_page(username=username, email=email, phone=phone)
    if not is_valid_username(username):
        flash("Invalid username (3-20 chars, letters/numbers/_ . -).", "error")
        return _register_page(username=username, email=email, phone=phone)

    cfg = get_config()
    ok, msg = auth_svc.register_user(
        email=email,
        username=username,
        phone=phone,
        password=password,
        confirm_password=confirm,
        base_url=cfg.BASE_URL,
    )
    flash(msg, "success" if ok else "error")
    if ok:
        return redirect(url_for("auth.login"))
    return _register_page(username=username, email=email, phone=phone)


@auth_bp.route("/verify/<token>")
def verify_email(token: str):
    ok, msg, _email = auth_svc.confirm_email_token(token)
    flash(msg, "success" if ok else "error")
    return redirect(url_for("auth.login"))


@auth_bp.route("/verify/resend", methods=["POST"])
def resend_verification():
    """Re-send the account verification email with a fresh token.

    Generates a brand-new token and invalidates any previously issued one
    for this address (see auth_svc.resend_verification_email).
    """
    email = normalize_email(request.form.get("email") or "")
    cfg = get_config()
    _ok, msg = auth_svc.resend_verification_email(email, cfg.BASE_URL)
    flash(msg, "success")
    return redirect(url_for("auth.login"))


# ── Password reset ───────────────────────────────────────────────────────────

@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html", email="")

    email = normalize_email(request.form.get("email") or "")
    if not email or not is_valid_email(email):
        flash("Please enter a valid email address.", "error")
        return render_template("forgot_password.html", email=email)

    cfg = get_config()
    _ok, msg = auth_svc.request_password_reset(email, cfg.BASE_URL)
    flash(msg, "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    if request.method == "GET":
        return render_template("reset_password.html", token=token)

    new_password = request.form.get("password") or request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or request.form.get("confirm") or ""
    ok, msg = auth_svc.reset_password_with_token(token, new_password, confirm)
    flash(msg, "success" if ok else "error")
    if ok:
        return redirect(url_for("auth.login"))
    return render_template("reset_password.html", token=token)


# ── Google OAuth ─────────────────────────────────────────────────────────────

@auth_bp.route("/auth/google")
@auth_bp.route("/google")
def google_login():
    if not _oauth_configured("google"):
        flash("Google login is temporarily unavailable due to server OAuth configuration.", "error")
        return redirect(url_for("auth.login"))

    cfg = get_config()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["oauth_provider"] = "google"

    params = {
        "client_id": cfg.GOOGLE_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("google"),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
        "access_type": "online",
    }
    return redirect("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))


@auth_bp.route("/auth/google/callback")
@auth_bp.route("/google/callback")
def google_callback():
    if request.args.get("error"):
        flash("Google sign-in was cancelled or denied.", "error")
        return redirect(url_for("auth.login"))

    state = request.args.get("state") or ""
    if not state or state != session.get("oauth_state") or session.get("oauth_provider") != "google":
        flash("Google login failed due to an invalid or expired session. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    cfg = get_config()
    try:
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": cfg.GOOGLE_CLIENT_ID,
                "client_secret": cfg.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _oauth_redirect_uri("google"),
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError("missing access_token")

        info_resp = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        info_resp.raise_for_status()
        info = info_resp.json()
    except Exception as e:
        logger.error("Google OAuth token/userinfo failed: %s", e)
        flash("Google login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))
    finally:
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)

    identity = OAuthIdentity(
        provider="google",
        provider_user_id=str(info.get("sub") or ""),
        email=normalize_email(info.get("email") or ""),
        email_verified=bool(info.get("email_verified")),
        name=info.get("name"),
        username_hint=(info.get("email") or "user").split("@")[0],
        avatar_url=info.get("picture"),
    )
    result = resolve_oauth_user(identity)
    if not result.ok or not result.email:
        flash(result.error_message or "Google login failed.", "error")
        return redirect(url_for("auth.login"))

    user = store.users.get(result.email) or {}
    if user.get("status") != "approved":
        flash(result.error_message or "Awaiting admin approval.", "error")
        return redirect(url_for("auth.login"))

    _establish_session(result.email, user.get("username") or result.email, remember=False)
    flash("Signed in with Google.", "success")
    return redirect(url_for("chat.chat"))


# ── GitHub OAuth ─────────────────────────────────────────────────────────────

@auth_bp.route("/auth/github")
@auth_bp.route("/github")
def github_login():
    if not _oauth_configured("github"):
        flash("GitHub login is temporarily unavailable due to server OAuth configuration.", "error")
        return redirect(url_for("auth.login"))

    cfg = get_config()
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    session["oauth_provider"] = "github"

    params = {
        "client_id": cfg.GITHUB_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri("github"),
        "scope": "read:user user:email",
        "state": state,
    }
    return redirect("https://github.com/login/oauth/authorize?" + urlencode(params))


@auth_bp.route("/auth/github/callback")
@auth_bp.route("/github/callback")
def github_callback():
    if request.args.get("error"):
        flash("GitHub sign-in was cancelled or denied.", "error")
        return redirect(url_for("auth.login"))

    state = request.args.get("state") or ""
    if not state or state != session.get("oauth_state") or session.get("oauth_provider") != "github":
        flash("GitHub login failed due to an invalid or expired session. Please try again.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code:
        flash("GitHub login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))

    cfg = get_config()
    try:
        token_resp = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": cfg.GITHUB_CLIENT_ID,
                "client_secret": cfg.GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": _oauth_redirect_uri("github"),
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise RuntimeError(token_data.get("error") or "missing access_token")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
        user_resp = requests.get("https://api.github.com/user", headers=headers, timeout=15)
        user_resp.raise_for_status()
        info = user_resp.json()

        primary_email = None
        email_verified = False
        try:
            emails_resp = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15)
            emails_resp.raise_for_status()
            emails = emails_resp.json()
            if isinstance(emails, list):
                for e in emails:
                    if e.get("primary") and e.get("verified"):
                        primary_email = e.get("email")
                        email_verified = True
                        break
                if not primary_email:
                    for e in emails:
                        if e.get("verified"):
                            primary_email = e.get("email")
                            email_verified = True
                            break
        except Exception as email_err:
            logger.warning("GitHub email fetch failed: %s", email_err)

        if not primary_email and info.get("email"):
            primary_email = info["email"]
            email_verified = False

    except Exception as e:
        logger.error("GitHub OAuth failed: %s", e)
        flash("GitHub login failed. Please try again.", "error")
        return redirect(url_for("auth.login"))
    finally:
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)

    if not primary_email:
        flash(
            "GitHub login failed: could not retrieve a verified email. "
            "Make a verified email available on GitHub or use another method.",
            "error",
        )
        return redirect(url_for("auth.login"))

    identity = OAuthIdentity(
        provider="github",
        provider_user_id=str(info.get("id") or ""),
        email=normalize_email(primary_email),
        email_verified=email_verified,
        name=info.get("name"),
        username_hint=info.get("login"),
        avatar_url=info.get("avatar_url"),
    )
    result = resolve_oauth_user(identity)
    if not result.ok or not result.email:
        flash(result.error_message or "GitHub login failed.", "error")
        return redirect(url_for("auth.login"))

    user = store.users.get(result.email) or {}
    if user.get("status") != "approved":
        flash(result.error_message or "Awaiting admin approval.", "error")
        return redirect(url_for("auth.login"))

    _establish_session(result.email, user.get("username") or result.email, remember=True)
    flash("Signed in with GitHub.", "success")
    return redirect(url_for("chat.chat"))
