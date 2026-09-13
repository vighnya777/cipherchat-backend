"""JSON chat helpers for mobile clients."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from cipherchat.chat import services as chat_svc
from cipherchat.services.storage import store

api_chat_bp = Blueprint("api_chat", __name__, url_prefix="/api/v1")


def _require_auth():
    return session.get("authenticated") and session.get("user_email")


@api_chat_bp.route("/rooms/<path:room_id>/messages", methods=["GET"])
def list_messages(room_id: str):
    """Paginated-ish message history for a room the user can access."""
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    limit = min(int(request.args.get("limit", 50)), 200)
    before = request.args.get("before")  # message_id cursor (optional)

    # Access check via existing can_access if available
    try:
        from cipherchat.chat.events import can_access_room
        if not can_access_room(room_id, email):
            return jsonify({"error": "forbidden"}), 403
    except Exception:
        # Fallback: private rooms must contain user
        if room_id.startswith("dm_"):
            data = store.private_rooms.get(room_id) or {}
            if email not in data.get("users", []):
                return jsonify({"error": "forbidden"}), 403

    try:
        messages = store.backend.get_messages(room_id, limit=500)
    except Exception:
        # In-memory fallback
        if room_id.startswith("dm_"):
            messages = (store.private_rooms.get(room_id) or {}).get("messages", [])
        else:
            messages = store.chat_rooms.get(room_id, [])

    if not isinstance(messages, list):
        messages = list(messages) if messages else []

    if before:
        idx = next((i for i, m in enumerate(messages) if m.get("message_id") == before), None)
        if idx is not None:
            messages = messages[:idx]

    messages = messages[-limit:]
    return jsonify({"room": room_id, "messages": messages, "count": len(messages)})


@api_chat_bp.route("/rooms", methods=["GET"])
def list_rooms():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    convos = chat_svc.get_existing_conversations(email)
    return jsonify({"conversations": convos})


@api_chat_bp.route('/rooms/<path:room_id>/messages/search', methods=['GET'])
def search_messages(room_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    
    email = session["user_email"]
    q = request.args.get("q", "")
    if len(q) < 2:
        return jsonify({"error": "query too short", "results": [], "count": 0}), 400

    try:
        from cipherchat.chat.events import can_access_room
        if not can_access_room(room_id, email):
            return jsonify({"error": "forbidden"}), 403
    except Exception:
        if room_id.startswith("dm_"):
            data = store.private_rooms.get(room_id) or {}
            if email not in data.get("users", []):
                return jsonify({"error": "forbidden"}), 403

    try:
        messages = store.backend.get_messages(room_id, limit=500)
    except Exception:
        if room_id.startswith("dm_"):
            messages = (store.private_rooms.get(room_id) or {}).get("messages", [])
        else:
            messages = store.chat_rooms.get(room_id, [])

    if not isinstance(messages, list):
        messages = list(messages) if messages else []

    q_lower = q.lower()
    results = [m for m in messages if m.get("message") and q_lower in m.get("message").lower()]
    
    return jsonify({"results": results, "count": len(results)})


@api_chat_bp.route('/rooms/<path:room_id>/pinned', methods=['GET'])
def pinned_messages(room_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    
    email = session["user_email"]
    
    try:
        from cipherchat.chat.events import can_access_room
        if not can_access_room(room_id, email):
            return jsonify({"error": "forbidden"}), 403
    except Exception:
        if room_id.startswith("dm_"):
            data = store.private_rooms.get(room_id) or {}
            if email not in data.get("users", []):
                return jsonify({"error": "forbidden"}), 403

    try:
        messages = store.backend.get_messages(room_id, limit=500)
    except Exception:
        if room_id.startswith("dm_"):
            messages = (store.private_rooms.get(room_id) or {}).get("messages", [])
        else:
            messages = store.chat_rooms.get(room_id, [])
            
    if not isinstance(messages, list):
        messages = list(messages) if messages else []

    results = [m for m in messages if m.get("pinned") is True]
    return jsonify({"messages": results, "count": len(results)})


@api_chat_bp.route('/rooms/<path:room_id>/info', methods=['GET'])
def room_info(room_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
        
    email = session["user_email"]

    try:
        from cipherchat.chat.events import can_access_room
        if not can_access_room(room_id, email):
            return jsonify({"error": "forbidden"}), 403
    except Exception:
        if room_id.startswith("dm_"):
            data = store.private_rooms.get(room_id) or {}
            if email not in data.get("users", []):
                return jsonify({"error": "forbidden"}), 403

    try:
        messages = store.backend.get_messages(room_id, limit=500)
    except Exception:
        if room_id.startswith("dm_"):
            messages = (store.private_rooms.get(room_id) or {}).get("messages", [])
        else:
            messages = store.chat_rooms.get(room_id, [])

    if not isinstance(messages, list):
        messages = list(messages) if messages else []

    participants = []
    room_type = "dm" if room_id.startswith("dm_") else "group"
    
    if room_type == "dm":
        data = store.private_rooms.get(room_id) or {}
        users = data.get("users", [])
        for u in users:
            presence = chat_svc.presence_for(u) if hasattr(chat_svc, 'presence_for') else {}
            online = chat_svc.is_user_online(u) if hasattr(chat_svc, 'is_user_online') else False
            participants.append({
                "email": u,
                "online": online,
                "last_seen": presence.get("last_seen")
            })
    else:
        users = getattr(store, 'channel_members', {}).get(room_id, [])
        for u in users:
            presence = chat_svc.presence_for(u) if hasattr(chat_svc, 'presence_for') else {}
            online = chat_svc.is_user_online(u) if hasattr(chat_svc, 'is_user_online') else False
            participants.append({
                "email": u,
                "online": online,
                "last_seen": presence.get("last_seen")
            })

    return jsonify({
        "room_id": room_id,
        "type": room_type,
        "participants": participants,
        "message_count": len(messages)
    })


@api_chat_bp.route('/users/<path:email>/status', methods=['GET'])
def user_status(email):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    
    presence = chat_svc.presence_for(email) if hasattr(chat_svc, 'presence_for') else {}
    return jsonify(presence)
