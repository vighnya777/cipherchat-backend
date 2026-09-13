"""Chat domain services."""

from __future__ import annotations

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
        # Prefer resolved email if a username was supplied
        resolved = store.resolve_email((u or "").strip().lower())
        return (resolved or (u or "").strip().lower())

    a = _norm(user_a)
    b = _norm(user_b)
    if not a or not b:
        raise ValueError("Both participants must be valid users/emails")

    pair = tuple(sorted([a, b]))

    # Scan existing private rooms for a matching normalized participant pair.
    # While scanning, ensure stored user lists are normalized and merge
    # any accidental duplicate rooms for the same pair into a single canonical room.
    canonical_room = None
    rooms_to_remove = []
    for room_id, data in list(store.private_rooms.items()):
        users = data.get("users", []) or []
        # normalize stored users for comparison
        norm_users = [_norm(u) for u in users]
        # update stored users if they differ
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
                # merge this duplicate room into the canonical one
                try:
                    canonical = store.private_rooms.get(canonical_room, {})
                    dup = store.private_rooms.get(room_id, {})
                    # preserve messages, keeping original order
                    canonical_msgs = canonical.setdefault("messages", [])
                    dup_msgs = dup.get("messages", [])
                    if dup_msgs:
                        canonical_msgs.extend(dup_msgs)
                        canonical["messages"] = canonical_msgs
                    # earliest created_at wins
                    ca = canonical.get("created_at")
                    da = dup.get("created_at")
                    if da and (not ca or da < ca):
                        canonical["created_at"] = da
                    store.private_rooms[canonical_room] = canonical
                    rooms_to_remove.append(room_id)
                except Exception:
                    pass

    # Remove merged duplicates
    for rid in rooms_to_remove:
        try:
            store.private_rooms.pop(rid, None)
        except Exception:
            pass

    if canonical_room:
        return canonical_room

    # No existing room found; create a new canonical private room
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


def is_user_online(email: str) -> bool:
    """Server-side authoritative presence check.

    A user counts as online while at least one authenticated Socket.IO
    connection (tab/device) for them is registered in store.active_users.
    """
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
    """Return the presence payload for a single user: online flag + last_seen.

    Presence is intentionally kept separate from the user's existence/profile
    data — an offline user is still a fully valid, discoverable account.
    """
    email = (email or "").strip().lower()
    online = is_user_online(email)
    user = store.users.get(email) if email in store.users else None
    last_seen = (user or {}).get("last_seen")
    return {"email": email, "online": online, "last_seen": None if online else last_seen}


def search_users(query: str, exclude_email: str, limit: int = 20) -> List[dict]:
    """Search registered users by username or display name.

    Offline users are fully searchable — presence never affects whether an
    account is discoverable, only what status badge is shown next to it.
    """
    query = (query or "").strip().lower()
    exclude_email = (exclude_email or "").strip().lower()
    if not query:
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
        display_name = (user.get("profile", {}) or {}).get("display_name", "") or username
        if query not in username and query not in email_norm and query not in display_name.lower():
            continue
        presence = presence_for(email_norm)
        profile = user.get("profile", {}) or {}
        results.append(
            {
                "email": email_norm,
                "username": user.get("username", email_norm),
                "display_name": profile.get("display_name") or user.get("username", email_norm),
                "avatar": profile.get("avatar"),
                "online": presence["online"],
                "last_seen": presence["last_seen"],
            }
        )
        if len(results) >= limit:
            break

    # Exact username/email matches first, then alphabetical.
    results.sort(key=lambda r: (not (r["username"].lower() == query or r["email"] == query), r["username"].lower()))
    return results


def get_contacts(exclude_email: str) -> List[dict]:
    contacts = []
    for email, user in store.users.items():
        if email == exclude_email:
            continue
        if user.get("status") != "approved":
            continue
        contacts.append(
            {
                "email": email,
                "username": user.get("username", email),
                "status": user.get("status"),
            }
        )
    return contacts


def sanitize(content: str) -> str:
    return sanitize_message(content)
