from __future__ import annotations

import logging

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
logger = logging.getLogger(__name__)


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
    query = (request.args.get("q") or "").strip()
    results = chat_svc.search_users(query, session["user_email"])
    return jsonify({"success": True, "results": results})


@chat_bp.route("/start-chat", methods=["POST"])
def start_chat():
    """Find-or-create a 1:1 chat room with another user, synchronously.

    This is the REST counterpart to the ``initiate_private_chat`` socket
    event. Unlike the socket flow (which requires an active connection and
    a round trip that can silently time out), this gives the client an
    immediate, explicit success/error response — including *why* it failed
    (unregistered user vs. self-chat vs. server error), so the UI never has
    to fall back to a generic "could not open chat" message.

    Reuses ``chat_svc.get_or_create_private_room`` — the exact same
    idempotent lookup/creation logic the socket path uses — so both entry
    points always agree on room identity and never create duplicate rooms.
    """
    if not _require_auth():
        return jsonify({"success": False, "error": "unauthorized", "message": "Please sign in."}), 401

    data = request.get_json(silent=True) or {}
    raw_target = (data.get("email") or data.get("target_email") or "").strip()
    if not raw_target:
        return jsonify({
            "success": False,
            "error": "missing_target",
            "message": "No user was specified.",
        }), 400

    me = (session.get("user_email") or "").strip().lower()
    target = store.resolve_email(raw_target.strip().lower()) or raw_target.strip().lower()

    if target == me:
        return jsonify({
            "success": False,
            "error": "self_chat",
            "message": "You can't start a chat with yourself.",
        }), 400

    if target not in store.users:
        return jsonify({
            "success": False,
            "error": "user_not_found",
            "message": "This person hasn't joined CipherChat yet.",
        }), 404

    user = store.users.get(target) or {}
    if user.get("status") and user.get("status") != "approved":
        return jsonify({
            "success": False,
            "error": "user_not_available",
            "message": "This user's account isn't active yet.",
        }), 409

    try:
        room_id = chat_svc.get_or_create_private_room(me, target)
    except ValueError as exc:
        return jsonify({"success": False, "error": "invalid_participants", "message": str(exc)}), 400
    except Exception:
        logger.exception("start_chat failed for %s -> %s", me, target)
        return jsonify({
            "success": False,
            "error": "server_error",
            "message": "Something went wrong starting the chat.",
        }), 500

    # Preserve real-time-notification parity with the socket-based
    # initiate_private_chat flow: let the target user's active sessions know
    # a new/updated private chat exists even though this request came in via
    # REST, not over their socket connection.
    try:
        from cipherchat.extensions import socketio

        socketio.emit(
            "private_chat_ready",
            {"room": room_id, "users": [me, target], "auto_open": False, "unread": 1},
            room=f"user_{target}",
        )
    except Exception:
        pass

    profile = user.get("profile") or {}
    display_name = profile.get("display_name") or user.get("username") or target

    return jsonify({
        "success": True,
        "room": room_id,
        "email": target,
        "username": user.get("username", target),
        "display_name": display_name,
    })


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
        from cipherchat.auth.validators import is_valid_username
        new_username = (request.form.get("username") or "").strip()
        bio = (request.form.get("bio") or "")[:500]
        phone = (request.form.get("phone") or "").strip()[:20]

        if new_username and new_username != user.get("username"):
            if not is_valid_username(new_username):
                flash("Username must be 3–20 characters (letters, numbers, _ . -).", "error")
            else:
                taken = any(
                    em != email and (u.get("username") or "").lower() == new_username.lower()
                    for em, u in _users_items()
                    if isinstance(u, dict)
                )
                if taken:
                    flash("That username is already taken.", "error")
                else:
                    old = user.get("username")
                    user["username"] = new_username
                    if old and old in store.username_index:
                        store.username_index.pop(old, None)
                    store.username_index[new_username] = email
                    session["username"] = new_username

        profile["bio"] = bio
        profile["phone"] = phone
        user["profile"] = profile
        store.set_user(email, user) if hasattr(store, "set_user") else store.users.__setitem__(email, user)
        flash("Profile updated.", "success")
        return redirect(url_for("chat.profile"))

    return render_template(
        "chat/profile.html",
        user_email=email,
        username=user.get("username") or session.get("username"),
        user=user,
        profile=profile,
    )