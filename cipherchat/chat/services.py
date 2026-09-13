"""Chat domain services."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from cipherchat.services.security import generate_invite_code, sanitize_message
from cipherchat.services.storage import store


def get_or_create_private_room(user_a: str, user_b: str) -> str:
    # Normalize participants to canonical emails (username resolution + lowercasing)
    def _norm(u: str) -> str:
        if not u:
            return ""
        resolved = store.resolve_email((u or "").strip().lower())
        return (resolved or (u or "").strip().lower())

    a = _norm(user_a)
    b = _norm(user_b)
    if not a or not b:
        raise ValueError("Both participants must be valid users/emails")

    pair = tuple(sorted([a, b]))

    canonical_room = None
    rooms_to_remove = []
    for room_id, data in list(store.private_rooms.items()):
        users = data.get("users", []) or []
        norm_users = [_norm(u) for u in users]
        if norm_users != users:
            try:
                data["users"] = list(dict.fromkeys([u for u in norm_users if u]))
                store.private_rooms[room_id] = data
            except Exception:
                pass

        if tuple(sorted(norm_users)) == pair:
            if canonical_room is None:
                canonical_room = room_id
            else:
                try:
                    canonical = store.private_rooms.get(canonical_room, {})
                    dup = store.private_rooms.get(room_id, {})
                    canonical_msgs = canonical.setdefault("messages", [])
                    dup_msgs = dup.get("messages", [])
                    if dup_msgs:
                        canonical_msgs.extend(dup_msgs)
                        canonical["messages"] = canonical_msgs
                    ca = canonical.get("created_at")
                    da = dup.get("created_at")
                    if da and (not ca or da < ca):
                        canonical["created_at"] = da
                    store.private_rooms[canonical_room] = canonical
                    rooms_to_remove.append(room_id)
                except Exception:
                    pass

    for rid in rooms_to_remove:
        try:
            store.private_rooms.pop(rid, None)
        except Exception:
            pass

    if canonical_room:
        return canonical_room

    room_id = f"dm_{uuid.uuid4().hex[:12]}"
    store.private_rooms[room_id] = {
        "users": [pair[0], pair[1]],
        "messages": [],
        "created_at": datetime.now().isoformat(),
    }
    return room_id


def append_message(room: str, message: dict, is_private: bool = False) -> dict:
    message.setdefault("id", uuid.uuid4().hex)
    message.setdefault("message_id", message["id"])
    message.setdefault("timestamp", datetime.now().isoformat())
    return store.backend.append_message(room, message, is_private=is_private)


def find_message_container(room: str):
    # Prefer backend messages (works for both memory and postgres)
    return store.backend.get_messages(room, limit=500)


def create_invite(room: str, created_by: str, max_uses: int = 5, hours: int = 24) -> str:
    from datetime import timedelta

    code = generate_invite_code()
    data = {
        "room": room,
        "created_by": created_by,
        "expires": datetime.now() + timedelta(hours=hours),
        "max_uses": max_uses,
        "used_count": 0,
        "users": [],
    }
    store.backend.set_invite(code, data)
    return code


def consume_invite(code: str) -> Optional[dict]:
    inv = store.backend.get_invite(code)
    if not inv:
        return None
    expires = inv["expires"]
    if hasattr(expires, "tzinfo") is False or True:
        if datetime.now() > (expires.replace(tzinfo=None) if hasattr(expires, "tzinfo") and expires.tzinfo else expires):
            store.backend.delete_invite(code)
            return None
    if inv["used_count"] >= inv["max_uses"]:
        return None
    inv["used_count"] += 1
    store.backend.set_invite(code, inv)
    return inv


def private_room_id(user_a: str, user_b: str) -> Optional[str]:
    """Return an existing private-room id for the given pair, or None.

    Does not create a room; only looks up an existing one using canonicalized
    participant emails.
    """
    def _norm(u: str) -> str:
        if not u:
            return ""
        resolved = store.resolve_email((u or "").strip().lower())
        return (resolved or (u or "").strip().lower())

    a = _norm(user_a)
    b = _norm(user_b)
    if not a or not b:
        return None
    pair = tuple(sorted([a, b]))
    for room_id, data in store.private_rooms.items():
        users = data.get("users", []) or []
        norm_users = [
            (store.resolve_email((u or "").strip().lower()) or (u or "").strip().lower())
            for u in users
        ]
        if tuple(sorted(norm_users)) == pair:
            return room_id
    return None


def _display_name_for(email: str) -> str:
    email = (email or "").strip().lower()
    if not email:
        return ""
    user = store.users.get(email) or {}
    username = user.get("username") or (email.split("@")[0] if "@" in email else email) or email
    profile = user.get("profile") or {}
    return profile.get("display_name") or username


def get_existing_conversations(email: str) -> List[dict]:
    """Return a list of existing conversation summaries for the given user.

    Includes the general room and any private rooms the user participates in.
    """
    out = []
    out.append({"id": "general", "type": "group", "name": "General Chat"})
    email_norm = (email or "").strip().lower()
    for room_id, data in store.private_rooms.items():
        users = data.get("users", []) or []
        norm_users = [
            (store.resolve_email((u or "").strip().lower()) or (u or "").strip().lower())
            for u in users
        ]
        if email_norm in norm_users:
            other = next((u for u in norm_users if u != email_norm), None)
            out.append({
                "id": room_id,
                "type": "private",
                "users": norm_users,
                "name": _display_name_for(other) if other else room_id,
                "email": other,
            })
    return out


def get_contacts(exclude_email: str) -> List[dict]:
    """Return user's contacts that appear in existing conversations only.

    This service-level helper still provides raw user entries, but the
    application-level /get-contacts route will only surface contacts that
    the user has actually conversed with (privacy constraint).
    """
    contacts = []
    seen = set()
    for room_id, data in store.private_rooms.items():
        users = data.get("users", []) or []
        norm_users = [
            (store.resolve_email((u or "").strip().lower()) or (u or "").strip().lower())
            for u in users
        ]
        if exclude_email in norm_users:
            for u in norm_users:
                if u == exclude_email or u in seen:
                    continue
                seen.add(u)
                user = store.users.get(u) or {}
                profile = user.get("profile") or {}
                contacts.append({
                    "email": u,
                    "username": user.get("username", u),
                    "display_name": profile.get("display_name") or user.get("username", u),
                    "status": user.get("status"),
                })
    return contacts


def is_user_online(email: str) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    try:
        return any(
            isinstance(info, dict) and (info.get("email") or "").strip().lower() == email
            for info in getattr(store, "active_users", {}).values()
        )
    except Exception:
        return False


def presence_for(email: str) -> Dict[str, Any]:
    email = (email or "").strip().lower()
    online = is_user_online(email)
    user = store.users.get(email) if email in store.users else None
    last_seen = (user or {}).get("last_seen")
    return {"email": email, "online": online, "last_seen": None if online else last_seen}


def search_users(query: str, exclude_email: str, limit: int = 20) -> List[dict]:
    query = (query or "").strip().lower()
    exclude_email = (exclude_email or "").strip().lower()
    if not query or len(query) < 2:
        return []

    results = []
    for email, user in store.users.items():
        email_norm = (email or "").strip().lower()
        if email_norm == exclude_email:
            continue
        if not isinstance(user, dict):
            continue
        if user.get("status") != "approved":
            continue

        username = (user.get("username") or "").lower()
        profile = user.get("profile", {}) or {}
        display_name = (profile.get("display_name") or username).lower()
        phone = str(profile.get("phone") or user.get("phone") or "").strip()
        phone_digits = re.sub(r"\D", "", phone)
        query_digits = re.sub(r"\D", "", query)
        phone_matched = False
        if phone and query in phone.lower():
            phone_matched = True
        elif len(query_digits) >= 3 and query_digits in phone_digits:
            phone_matched = True
        elif len(query_digits) >= 7 and len(phone_digits) >= 7 and query_digits[-7:] == phone_digits[-7:]:
            phone_matched = True

        if not (query in username or query in email_norm or query in display_name or phone_matched):
            continue

        presence = presence_for(email_norm)
        results.append(
            {
                "email": email_norm,
                "username": user.get("username", email_norm),
                "display_name": profile.get("display_name") or user.get("username", email_norm),
                "avatar": profile.get("avatar"),
                "phone": phone,
                "online": presence["online"],
                "last_seen": presence["last_seen"],
            }
        )
        if len(results) >= limit:
            break

    results.sort(key=lambda r: (not (r["username"].lower() == query or r["email"] == query), r["username"].lower()))
    return results


def sanitize(content: str) -> str:
    return sanitize_message(content)
