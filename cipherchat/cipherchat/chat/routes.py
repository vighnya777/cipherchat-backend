from __future__ import annotations

import re

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from cipherchat.chat import services as chat_svc
from cipherchat.config import get_config
from cipherchat.services.storage import store

chat_bp = Blueprint("chat", __name__)

# Matches URLs produced by the existing media upload endpoint (cipherchat.media.routes),
# e.g. "/uploads/ab12cd34ef56_avatar.png". Used only to sanity-check that an
# incoming "avatar" value actually points at a file we generated ourselves.
_SAFE_AVATAR_URL = re.compile(r"^/uploads/[A-Za-z0-9._-]+$")


def _wants_json() -> bool:
    if request.is_json:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _require_auth():
    return session.get("authenticated") and session.get("user_email")


def _users_items():
    try:
        return list(store.users.items())
    except Exception:
        return []


@chat_bp.route("/chat")
def chat():
    if not _require_auth():
        return redirect(url_for("auth.login"))
    return render_template(
        "chat/chat.html",
        user_email=session.get("user_email"),
        username=session.get("username", session.get("user_email")),
        general_chat_enabled=get_config().GENERAL_CHAT_ENABLED,
    )


@chat_bp.route("/create-invite", methods=["POST"])
def create_invite():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or request.form
    room = data.get("room") or "general"
    code = chat_svc.create_invite(room, session["user_email"])
    base = get_config().BASE_URL
    return jsonify({"success": True, "code": code, "url": f"{base}/join/{code}"})


@chat_bp.route("/join/<invite_code>")
def join_via_invite(invite_code):
    if not _require_auth():
        flash("Please sign in to join via invite.", "error")
        return redirect(url_for("auth.login"))
    inv = chat_svc.consume_invite(invite_code)
    if not inv:
        flash("Invalid or expired invite.", "error")
        return redirect(url_for("chat.chat"))
    flash(f"Joined room: {inv['room']}", "success")
    return redirect(url_for("chat.chat"))


@chat_bp.route("/get-invites")
def get_invites():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    mine = {
        code: data
        for code, data in store.invite_links.items()
        if data.get("created_by") == email
    }
    out = {}
    for code, data in mine.items():
        out[code] = {
            **data,
            "expires": data["expires"].isoformat()
            if hasattr(data["expires"], "isoformat")
            else data["expires"],
        }
    return jsonify(out)


@chat_bp.route("/revoke-invite/<invite_code>", methods=["POST"])
def revoke_invite(invite_code):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    inv = store.invite_links.get(invite_code)
    if not inv or inv.get("created_by") != session["user_email"]:
        return jsonify({"error": "not found"}), 404
    store.invite_links.pop(invite_code, None)
    return jsonify({"success": True})


@chat_bp.route("/get-contacts")
def get_contacts():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    user = session["user_email"]
    conversations = chat_svc.get_existing_conversations(user)
    contacts = chat_svc.get_contacts(user)
    return jsonify({"success": True, "contacts": contacts, "conversations": conversations})


@chat_bp.route("/search-users")
def search_users():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    query = request.args.get("q", "")
    return jsonify(chat_svc.search_users(query, session["user_email"]))


@chat_bp.route("/user/<path:identifier>")
def view_user_profile(identifier):
    """Public profile lookup — works whether the target user is online or
    offline. A registered account always exists/is viewable; presence
    (online/offline/last seen) is layered on separately."""
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401

    identifier = (identifier or "").strip().lower()
    email = identifier if identifier in store.users else store.username_index.get(identifier)
    if not email or email not in store.users:
        return jsonify({"error": "not found"}), 404

    user = store.users[email]
    if user.get("status") != "approved":
        return jsonify({"error": "not found"}), 404

    profile = user.get("profile", {}) or {}
    presence = chat_svc.presence_for(email)

    def _fmt(iso_value):
        if not iso_value:
            return None
        try:
            import datetime as _dt
            return _dt.datetime.fromisoformat(str(iso_value)).strftime("%b %d, %Y")
        except Exception:
            return str(iso_value)

    return jsonify(
        {
            "email": email,
            "username": user.get("username", email),
            "display_name": profile.get("display_name") or user.get("username", email),
            "bio": profile.get("bio", ""),
            "avatar": profile.get("avatar"),
            "member_since": _fmt(user.get("created_at")),
            "online": presence["online"],
            "last_seen": presence["last_seen"],
        }
    )


@chat_bp.route("/room-files")
def get_room_files():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    room = request.args.get("room", "general")
    return jsonify(store.room_files.get(room, []))


@chat_bp.route("/match-contacts", methods=["POST"])
def match_contacts():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    items = payload.get("contacts") or []
    if not isinstance(items, list):
        return jsonify({"error": "invalid payload"}), 400
    items = items[:200]

    me = session["user_email"]
    emails = set()
    phones = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        email = (raw.get("email") or "").strip().lower()
        tel = "".join(ch for ch in str(raw.get("tel") or "") if ch.isdigit() or ch == "+")
        if email and "@" in email:
            emails.add(email)
        if tel and len(tel) >= 7:
            phones.add(tel[-10:])

    matched = []
    seen = set()
    for email, user in _users_items():
        if not isinstance(user, dict) or email == me:
            continue
        if user.get("status") != "approved":
            continue
        profile = user.get("profile") or {}
        phone = "".join(ch for ch in str(profile.get("phone") or "") if ch.isdigit() or ch == "+")
        phone_key = phone[-10:] if phone else ""
        if email not in emails and not (phone_key and phone_key in phones):
            continue
        if email in seen:
            continue
        seen.add(email)
        matched.append({"email": email, "username": user.get("username") or email, "on_cipherchat": True})

    q = (payload.get("query") or "").strip().lower()
    if q and len(q) >= 2:
        for email, user in _users_items():
            if not isinstance(user, dict) or email == me:
                continue
            if user.get("status") != "approved" or email in seen:
                continue
            uname = (user.get("username") or "").lower()
            phone = str((user.get("profile") or {}).get("phone") or "")
            if q in email or q in uname or (q.isdigit() and q in phone):
                matched.append({"email": email, "username": user.get("username") or email, "on_cipherchat": True})
                seen.add(email)

    return jsonify({"matched": matched, "count": len(matched)})


@chat_bp.route("/profile", methods=["GET", "POST"])
def profile():
    if not _require_auth():
        return redirect(url_for("auth.login"))
    email = session["user_email"]
    user = store.users.get(email) or {}
    profile = user.setdefault("profile", {})

    if request.method == "POST":
        from cipherchat.auth.validators import is_valid_phone, is_valid_username

        payload = request.get_json(silent=True) if request.is_json else None
        form = payload if payload is not None else request.form

        new_username = (form.get("username") or "").strip()
        bio = (form.get("bio") or "")[:500]
        phone = (form.get("phone") or "").strip()[:20]
        avatar = form.get("avatar", None)  # None = untouched, "" = remove, url = set

        errors = {}

        if new_username and new_username != user.get("username"):
            if not is_valid_username(new_username):
                errors["username"] = "Username must be 3–20 characters (letters, numbers, _ . -)."
            else:
                taken = any(
                    em != email and (u.get("username") or "").lower() == new_username.lower()
                    for em, u in _users_items()
                    if isinstance(u, dict)
                )
                if taken:
                    errors["username"] = "That username is already taken."

        if phone and not is_valid_phone(phone):
            errors["phone"] = "Enter a valid phone number (7–20 digits)."

        if avatar not in (None, ""):
            if not _SAFE_AVATAR_URL.match(avatar):
                errors["avatar"] = "Invalid avatar image. Please upload again."

        if errors:
            if _wants_json():
                return jsonify({"success": False, "errors": errors}), 400
            for msg in errors.values():
                flash(msg, "error")
            return redirect(url_for("chat.profile"))

        if new_username and new_username != user.get("username"):
            old = user.get("username")
            user["username"] = new_username
            if old and old in store.username_index:
                store.username_index.pop(old, None)
            store.username_index[new_username] = email
            session["username"] = new_username

        profile["bio"] = bio
        profile["phone"] = phone
        if avatar is not None:
            profile["avatar"] = avatar or None
        user["profile"] = profile

        import datetime as _dt
        user["last_profile_update"] = _dt.datetime.now().isoformat()

        store.set_user(email, user) if hasattr(store, "set_user") else store.users.__setitem__(email, user)

        if _wants_json():
            return jsonify({
                "success": True,
                "message": "Profile updated.",
                "profile": {
                    "username": user.get("username"),
                    "bio": profile.get("bio", ""),
                    "phone": profile.get("phone", ""),
                    "avatar": profile.get("avatar"),
                },
            })

        flash("Profile updated.", "success")
        return redirect(url_for("chat.profile"))

    # ---- GET: build a read-only view model without inventing any data ----
    recent_activity = []
    try:
        logs = getattr(store, "activity_logs", []) or []
        recent_activity = [
            entry for entry in logs
            if isinstance(entry, dict) and entry.get("email") == email
        ][-5:][::-1]
    except Exception:
        recent_activity = []

    is_online = False
    try:
        is_online = any(
            isinstance(info, dict) and info.get("email") == email
            for info in getattr(store, "active_users", {}).values()
        )
    except Exception:
        is_online = False

    def _fmt(iso_value):
        if not iso_value:
            return None
        try:
            import datetime as _dt
            return _dt.datetime.fromisoformat(str(iso_value)).strftime("%b %d, %Y · %I:%M %p")
        except Exception:
            return str(iso_value)

    return render_template(
        "chat/profile.html",
        user_email=email,
        username=user.get("username") or session.get("username"),
        user=user,
        profile=profile,
        recent_activity=recent_activity,
        is_online=is_online,
        member_since_display=_fmt(user.get("created_at")),
        last_login_display=_fmt(user.get("last_login") or user.get("last_seen")),
        last_update_display=_fmt(user.get("last_profile_update")),
    )