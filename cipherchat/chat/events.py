"""Socket.IO event handlers for real-time chat – event names preserved."""

from __future__ import annotations

import logging
from datetime import datetime

from flask import request, session
from flask_socketio import emit, join_room, leave_room

from cipherchat.chat import services as chat_svc
from cipherchat.chat.groups.events import can_access_room
from cipherchat.config import get_config
from cipherchat.extensions import socketio
from cipherchat.services.storage import store

logger = logging.getLogger(__name__)


def _authenticated() -> bool:
    return bool(session.get("authenticated") and session.get("user_email"))


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _unique_active_users() -> list:
    seen = set()
    result = []
    for sid, info in store.active_users.items():
        email = _normalize_email(info.get("email") or "")
        if not email or email in seen:
            continue
        seen.add(email)
        result.append(
            {
                "email": email,
                "username": info.get("username") or email,
                "sid": sid,
            }
        )
    return result


@socketio.on("connect")
def on_connect():
    if not _authenticated():
        return False
    user_email = _normalize_email(session["user_email"])
    join_room(f"user_{user_email}")
    store.active_users[request.sid] = {
        "email": user_email,
        "username": session.get("username") or user_email,
        "rooms": ["general"],
        "private_rooms": [],
    }
    if user_email in store.users:
        store.users[user_email]["last_seen"] = datetime.now().isoformat()
    else:
        store.users[user_email] = {
            "created_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "profile": {"avatar": None, "bio": ""},
        }

    if "invite_code" in session and "invite_room" in session:
        room_name = session["invite_room"]
        invite_code = session["invite_code"]
        if invite_code in store.invite_links:
            invite_data = store.invite_links[invite_code]
            users_list = invite_data.setdefault("users", [])
            if user_email not in users_list:
                join_room(room_name)
                store.active_users[request.sid]["rooms"].append(room_name)
                invite_data["used_count"] = invite_data.get("used_count", 0) + 1
                users_list.append(user_email)
                session.pop("invite_code", None)
                session.pop("invite_room", None)
                emit(
                    "user_joined",
                    {
                        "email": user_email,
                        "message": f"{user_email} joined via invite link",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    },
                    room=room_name,
                )
            else:
                join_room("general")
        else:
            join_room("general")
    else:
        if get_config().GENERAL_CHAT_ENABLED:
            join_room("general")

    for room_id, room_data in store.private_rooms.items():
        if user_email in room_data.get("users", []):
            join_room(room_id)
            emit(
                "private_chat_ready",
                {
                    "room": room_id,
                    "users": room_data.get("users", []),
                    "auto_open": False,
                },
                room=request.sid,
            )
            emit(
                "room_history",
                {"room": room_id, "messages": room_data.get("messages", [])[-100:]},
                room=request.sid,
            )

    emit("active_users", {"users": _unique_active_users()}, room="general")
    emit("user_status", {"email": user_email, "online": True, "last_seen": None}, broadcast=True)


@socketio.on("disconnect")
def on_disconnect():
    if request.sid not in store.active_users:
        return
    user_data = store.active_users.pop(request.sid)
    user_email = user_data["email"]
    for room in user_data.get("rooms", []):
        leave_room(room)
        emit(
            "user_left",
            {
                "email": user_email,
                "message": f"{user_email} left the chat",
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            },
            room=room,
        )
    if user_email in store.users:
        store.users[user_email]["last_seen"] = datetime.now().isoformat()
    emit("user_status", {"email": user_email, "online": False, "last_seen": datetime.now().isoformat()}, broadcast=True)
    emit("active_users", {"users": _unique_active_users()}, broadcast=True)




@socketio.on("get_active_users")
def on_get_active_users():
    if not _authenticated():
        return
    emit("active_users", {"users": _unique_active_users()})

@socketio.on("send_message")
def handle_message(data):
    if not _authenticated():
        return
    if not isinstance(data, dict):
        return
    user_email = session["user_email"]  # never trust client identity
    raw = data.get("message", "")
    if not isinstance(raw, str):
        raw = ""
    message = chat_svc.sanitize(raw)
    room = data.get("room", "general")
    if not isinstance(room, str) or not room or len(room) > 128:
        return
    # Basic room name safety
    if "/" in room or ".." in room:
        return
    if room == "general" and not get_config().GENERAL_CHAT_ENABLED:
        return
    if not can_access_room(room, user_email):
        return
    attachment = data.get("attachment")
    if attachment is not None and not isinstance(attachment, dict):
        return
    if not message and not attachment:
        return
    # Message validation
    if message and not message.strip():
        return
    if len(message) > 4000:
        message = message[:4000]
    # Reject control characters except newline/tab
    if message and any(ord(ch) < 9 or (13 < ord(ch) < 32) for ch in message):
        message = "".join(ch for ch in message if ord(ch) >= 32 or ch in "\n\t")

    message_data = {
        "message_id": data.get("message_id") or __import__("uuid").uuid4().hex,
        "email": user_email,
        "message": message,
        "room": room,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "attachment": attachment,
        "reply_to": data.get("reply_to"),
        "forwarded_from": data.get("forwarded_from"),
    }
    is_private = room.startswith("dm_")
    chat_svc.append_message(room, message_data, is_private=is_private)

    # Keep last 100 messages for groups
    if not is_private:
        store.chat_rooms[room] = store.chat_rooms[room][-100:]

    emit("receive_message", message_data, room=room)

    if is_private:
        for participant in store.private_rooms.get(room, {}).get("users", []):
            emit(
                "private_chat_ready",
                {"room": room, "users": store.private_rooms.get(room, {}).get("users", [])},
                room=f"user_{participant}",
            )

    if attachment:
        store.room_files[room].append(
            {
                "url": attachment.get("url"),
                "type": attachment.get("type"),
                "name": attachment.get("name"),
                "uploaded_by": user_email,
                "timestamp": datetime.now().isoformat(),
            }
        )
    logger.info("Message sent in %s by %s", room, user_email)


@socketio.on("typing")
def on_typing(data):
    if not _authenticated():
        return
    room = data.get("room", "general")
    emit(
        "typing",
        {"email": session["user_email"], "room": room},
        room=room,
        include_self=False,
    )


@socketio.on("stop_typing")
def on_stop_typing(data):
    if not _authenticated():
        return
    room = data.get("room", "general")
    emit(
        "stop_typing",
        {"email": session["user_email"], "room": room},
        room=room,
        include_self=False,
    )


@socketio.on("add_reaction")
def on_add_reaction(data):
    if not _authenticated():
        return
    user_email = session["user_email"]
    room = data.get("room")
    message_id = data.get("message_id")
    emoji = data.get("emoji")
    action = data.get("action", "add")
    if not room or not message_id or not emoji:
        return
    messages = chat_svc.find_message_container(room)
    target = next((m for m in messages if m.get("message_id") == message_id), None)
    if not target:
        return
    reactions = target.setdefault("reactions", {})
    users = set(reactions.get(emoji, []))
    if action == "remove":
        users.discard(user_email)
    else:
        users.add(user_email)
    reactions[emoji] = list(users)
    emit(
        "reaction_update",
        {"room": room, "message_id": message_id, "reactions": reactions},
        room=room,
    )


@socketio.on("join_room")
def on_join_room(data):
    if not _authenticated():
        return
    room = data.get("room")
    if not room or not isinstance(room, str) or len(room) > 128:
        return
    if "/" in room or ".." in room:
        return
    if room == "general" and not get_config().GENERAL_CHAT_ENABLED:
        return
    if not can_access_room(room, session["user_email"]):
        emit("room_denied", {"room": room, "reason": "not a member"})
        return
    join_room(room)
    sid_data = store.active_users.get(request.sid)
    if sid_data and room not in sid_data["rooms"]:
        sid_data["rooms"].append(room)

    # Send history to the joining client only (so messages appear on screen)
    is_private = room.startswith("dm_")
    try:
        messages = store.backend.get_messages(room, limit=100)
    except Exception:
        if is_private:
            messages = list(store.private_rooms.get(room, {}).get("messages", []))[-100:]
        else:
            messages = list(store.chat_rooms.get(room, []))[-100:]
    emit("room_history", {"room": room, "messages": messages})

    emit(
        "user_joined",
        {
            "email": session["user_email"],
            "message": f"{session['user_email']} joined {room}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        },
        room=room,
        include_self=False,
    )


@socketio.on("leave_room")
def on_leave_room(data):
    if not _authenticated():
        return
    room = data.get("room")
    if not room:
        return
    leave_room(room)
    sid_data = store.active_users.get(request.sid)
    if sid_data and room in sid_data["rooms"]:
        sid_data["rooms"].remove(room)
    emit(
        "user_left",
        {
            "email": session["user_email"],
            "message": f"{session['user_email']} left {room}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        },
        room=room,
    )


@socketio.on("initiate_private_chat")
def on_initiate_private_chat(data):
    """Start (or resolve) a 1:1 chat room with another user.

    IMPORTANT: every rejection path here MUST emit ``private_chat_error`` back
    to the requesting socket. Previously several of these branches just
    ``return``ed silently, which left clients waiting on a timeout with no
    way to distinguish "user isn't registered" from "you're not logged in"
    from "the server blew up" — they all looked identical (a hang) to the
    caller. See client-side timeout handling for the corresponding
    generic-message regression this caused.
    """
    data = data or {}

    def _reject(error: str, message: str) -> None:
        emit(
            "private_chat_error",
            {"error": error, "message": message},
            room=request.sid,
        )

    if not _authenticated():
        _reject("unauthorized", "You must be signed in to start a chat.")
        return

    raw_target = data.get("target_email") or data.get("email") or ""
    if not raw_target.strip():
        _reject("missing_target", "No user was specified.")
        return

    target = store.resolve_email(raw_target) or _normalize_email(raw_target)
    user_email = _normalize_email(session["user_email"])

    if target == user_email:
        _reject("self_chat", "You can't start a chat with yourself.")
        return

    if not target or target not in store.users:
        _reject(
            "user_not_found",
            "This person hasn't joined CipherChat yet.",
        )
        return

    try:
        room_id = chat_svc.get_or_create_private_room(user_email, target)
    except ValueError as exc:
        _reject("invalid_participants", str(exc))
        return
    except Exception:
        logger.exception(
            "initiate_private_chat failed for %s -> %s", user_email, target
        )
        _reject("server_error", "Something went wrong starting the chat.")
        return

    join_room(room_id)
    sid_data = store.active_users.get(request.sid)
    if sid_data and room_id not in sid_data.get("private_rooms", []):
        sid_data.setdefault("private_rooms", []).append(room_id)

    for sid, info in store.active_users.items():
        if _normalize_email(info.get("email")) == target:
            target_data = store.active_users.get(sid)
            if target_data and room_id not in target_data.get("private_rooms", []):
                target_data.setdefault("private_rooms", []).append(room_id)
            join_room(room_id, sid=sid)
            break

    emit(
        "private_chat_ready",
        {"room": room_id, "users": [user_email, target], "auto_open": True},
        room=request.sid,
    )
    emit(
        "private_chat_ready",
        {"room": room_id, "users": [user_email, target], "auto_open": False, "unread": 1},
        room=f"user_{target}",
    )


@socketio.on("typing_private")
def on_typing_private(data):
    if not _authenticated():
        return
    room = data.get("room")
    if room and room.startswith("dm_"):
        emit(
            "typing",
            {"email": session["user_email"], "room": room, "type": "private"},
            room=room,
            include_self=False,
        )


@socketio.on("stop_typing_private")
def on_stop_typing_private(data):
    if not _authenticated():
        return
    room = data.get("room")
    if room and room.startswith("dm_"):
        emit(
            "stop_typing",
            {"email": session["user_email"], "room": room, "type": "private"},
            room=room,
            include_self=False,
        )


@socketio.on("admin_join")
def on_admin_join():
    from cipherchat.admin.services import is_authenticated_admin

    if not is_authenticated_admin():
        return
    join_room("admin_room")


@socketio.on("admin_leave")
def on_admin_leave():
    leave_room("admin_room")


@socketio.on("admin_request_stats")
def on_admin_request_stats():
    from cipherchat.admin.services import calculate_admin_stats, is_authenticated_admin

    if not is_authenticated_admin():
        return
    emit("admin_stats", calculate_admin_stats())


@socketio.on('edit_message')
def on_edit_message(data):
    if not _authenticated():
        return
    room = data.get("room")
    message_id = data.get("message_id")
    new_body = data.get("new_body")
    if not room or not message_id or not isinstance(new_body, str):
        return
    if len(new_body) > 4000:
        return
    new_body = chat_svc.sanitize(new_body)
    messages = chat_svc.find_message_container(room)
    target = next((m for m in messages if m.get("message_id") == message_id), None)
    if not target:
        return
    if target.get("email") != session["user_email"]:
        return
    target["message"] = new_body
    target["edited_at"] = datetime.now().isoformat()
    try:
        store.backend.edit_message(message_id, new_body)
    except Exception:
        pass
    emit("message_edited", {
        "room": room,
        "message_id": message_id,
        "new_body": new_body,
        "edited_at": target["edited_at"],
        "email": session["user_email"]
    }, room=room)


@socketio.on('delete_message')
def on_delete_message(data):
    if not _authenticated():
        return
    room = data.get("room")
    message_id = data.get("message_id")
    if not room or not message_id:
        return
    messages = chat_svc.find_message_container(room)
    target = next((m for m in messages if m.get("message_id") == message_id), None)
    if not target:
        return
    from cipherchat.admin.services import is_authenticated_admin
    if target.get("email") != session["user_email"] and not is_authenticated_admin():
        return
    try:
        messages.remove(target)
    except (ValueError, AttributeError):
        pass
    try:
        store.backend.delete_message(message_id)
    except Exception:
        pass
    emit("message_deleted", {
        "room": room,
        "message_id": message_id,
        "email": target.get("email")
    }, room=room)


@socketio.on('pin_message')
def on_pin_message(data):
    if not _authenticated():
        return
    room = data.get("room")
    message_id = data.get("message_id")
    if not room or not message_id:
        return
    messages = chat_svc.find_message_container(room)
    target = next((m for m in messages if m.get("message_id") == message_id), None)
    if target:
        target["pinned"] = True
    try:
        store.backend.pin_message(message_id, True)
    except Exception:
        pass
    emit("message_pinned", {
        "room": room,
        "message_id": message_id,
        "pinned": True
    }, room=room)


@socketio.on('unpin_message')
def on_unpin_message(data):
    if not _authenticated():
        return
    room = data.get("room")
    message_id = data.get("message_id")
    if not room or not message_id:
        return
    messages = chat_svc.find_message_container(room)
    target = next((m for m in messages if m.get("message_id") == message_id), None)
    if target:
        target["pinned"] = False
    try:
        store.backend.pin_message(message_id, False)
    except Exception:
        pass
    emit("message_pinned", {
        "room": room,
        "message_id": message_id,
        "pinned": False
    }, room=room)
