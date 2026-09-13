"""In-memory StoreBackend – preserves legacy MVP behavior."""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict, List, Optional

from cipherchat.database.repositories.base import DuplicateUserError, StoreBackend


class MemoryRepository(StoreBackend):
    def __init__(self):
        self.users: Dict[str, dict] = {}
        self.username_index: Dict[str, str] = {}
        # Guards the check-then-insert in create_user() so two concurrent
        # registrations for the same email/username can't both succeed.
        self._create_lock = threading.Lock()
        self.otp: Dict[str, dict] = {}
        self.dynamic_passwords: Dict[str, dict] = {}
        self.verification_tokens: Dict[str, dict] = {}
        self.reset_tokens: Dict[str, dict] = {}
        self.chat_rooms: Dict[str, list] = defaultdict(list)
        self.private_rooms: Dict[str, dict] = {}
        self.invite_links: Dict[str, dict] = {}
        self.room_files: Dict[str, list] = defaultdict(list)
        self.activity_logs: List[dict] = []

    def get_user(self, email: str) -> Optional[dict]:
        return self.users.get((email or "").strip().lower())

    def set_user(self, email: str, data: dict) -> None:
        key = email.lower().strip()
        self.users[key] = data
        username = data.get("username")
        if username:
            self.username_index[username.lower()] = key

    def create_user(self, email: str, data: dict) -> None:
        key = (email or "").lower().strip()
        username = (data.get("username") or "").strip()
        username_key = username.lower()
        with self._create_lock:
            if key in self.users:
                raise DuplicateUserError("email")
            if username_key and username_key in self.username_index:
                raise DuplicateUserError("username")
            self.users[key] = data
            if username:
                self.username_index[username_key] = key

    def delete_user(self, email: str) -> None:
        key = email.lower().strip()
        user = self.users.pop(key, None)
        if user and user.get("username"):
            self.username_index.pop(user["username"].lower(), None)

    def all_users(self) -> Dict[str, dict]:
        return self.users

    def resolve_email(self, username_or_email: str) -> Optional[str]:
        value = (username_or_email or "").strip().lower()
        if not value:
            return None
        if value in self.users:
            return value
        return self.username_index.get(value)

    def get_otp(self, email: str) -> Optional[dict]:
        return self.otp.get(email)

    def set_otp(self, email: str, data: dict) -> None:
        self.otp[email] = data

    def delete_otp(self, email: str) -> None:
        self.otp.pop(email, None)

    def get_dynamic_password(self, email: str) -> Optional[dict]:
        return self.dynamic_passwords.get(email)

    def set_dynamic_password(self, email: str, data: dict) -> None:
        self.dynamic_passwords[email] = data

    def delete_dynamic_password(self, email: str) -> None:
        self.dynamic_passwords.pop(email, None)

    def get_verification_token(self, token: str) -> Optional[dict]:
        return self.verification_tokens.get(token)

    def set_verification_token(self, token: str, data: dict) -> None:
        self.verification_tokens[token] = data

    def delete_verification_token(self, token: str) -> None:
        self.verification_tokens.pop(token, None)

    def delete_verification_tokens_for_email(self, email: str) -> None:
        stale = [t for t, data in self.verification_tokens.items() if data.get("email") == email]
        for t in stale:
            self.verification_tokens.pop(t, None)

    def get_reset_token(self, token: str) -> Optional[dict]:
        return self.reset_tokens.get(token)

    def set_reset_token(self, token: str, data: dict) -> None:
        self.reset_tokens[token] = data

    def delete_reset_token(self, token: str) -> None:
        self.reset_tokens.pop(token, None)

    def ensure_room(self, room_key: str, room_type: str = "group", created_by: str = None) -> None:
        if room_type == "dm" or room_key.startswith("dm_"):
            self.private_rooms.setdefault(room_key, {"users": [], "messages": []})
        else:
            self.chat_rooms.setdefault(room_key, [])

    def append_message(self, room_key: str, message: dict, is_private: bool = False) -> dict:
        self.ensure_room(room_key, "dm" if is_private or room_key.startswith("dm_") else "group")
        if is_private or room_key.startswith("dm_"):
            self.private_rooms[room_key]["messages"].append(message)
        else:
            self.chat_rooms[room_key].append(message)
            self.chat_rooms[room_key] = self.chat_rooms[room_key][-100:]
        return message

    def get_messages(self, room_key: str, limit: int = 100) -> List[dict]:
        if room_key.startswith("dm_"):
            msgs = self.private_rooms.get(room_key, {}).get("messages", [])
        else:
            msgs = self.chat_rooms.get(room_key, [])
        return msgs[-limit:]

    def set_reaction(self, message_id: str, emoji: str, user_email: str, add: bool = True) -> dict:
        # search all rooms
        containers = list(self.chat_rooms.values())
        containers += [r.get("messages", []) for r in self.private_rooms.values()]
        for messages in containers:
            for msg in messages:
                if msg.get("message_id") == message_id:
                    reactions = msg.setdefault("reactions", {})
                    users = set(reactions.get(emoji, []))
                    if add:
                        users.add(user_email)
                    else:
                        users.discard(user_email)
                    reactions[emoji] = list(users)
                    return reactions
        return {}

    def get_invite(self, code: str) -> Optional[dict]:
        return self.invite_links.get(code)

    def set_invite(self, code: str, data: dict) -> None:
        self.invite_links[code] = data

    def delete_invite(self, code: str) -> None:
        self.invite_links.pop(code, None)

    def all_invites(self) -> Dict[str, dict]:
        return self.invite_links

    def add_media(self, room_key: str, meta: dict) -> None:
        self.room_files[room_key].append(meta)

    def list_media(self, room_key: str) -> List[dict]:
        return self.room_files.get(room_key, [])

    def add_activity(self, entry: dict) -> None:
        self.activity_logs.append(entry)

    def list_activity(self, limit: int = 100) -> List[dict]:
        return self.activity_logs[-limit:]

    def clear_activity(self) -> int:
        n = len(self.activity_logs)
        self.activity_logs.clear()
        return n
