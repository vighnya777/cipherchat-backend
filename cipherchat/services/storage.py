from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from cipherchat.database.repositories.factory import get_store_backend
from cipherchat.database.repositories.memory import MemoryRepository


def _safe_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "items"):
        try:
            return dict(obj.items())
        except Exception:
            pass
    return {}


class _UsersProxy:
    """Dict-like view over backend users with local reference caching so in-place
    mutations (e.g. store.users[email]['profile'] = ...) are preserved."""

    def __init__(self, store: "Storage"):
        self._store = store
        self._cache: Dict[str, dict] = {}

    def _all(self) -> dict:
        try:
            result = self._store.backend.all_users()
            db_dict = _safe_dict(result)
            for k, v in self._cache.items():
                db_dict[k] = v
            return db_dict
        except Exception:
            return dict(self._cache)

    def __getitem__(self, email: str):
        email_clean = (email or "").strip().lower()
        if email_clean in self._cache:
            return self._cache[email_clean]
        user = self._store.backend.get_user(email_clean)
        if user is None:
            raise KeyError(email)
        self._cache[email_clean] = user
        return user

    def __setitem__(self, email: str, data: dict) -> None:
        email_clean = (email or "").strip().lower()
        self._cache[email_clean] = data
        self._store.backend.set_user(email_clean, data)

    def __delitem__(self, email: str) -> None:
        email_clean = (email or "").strip().lower()
        self._cache.pop(email_clean, None)
        self._store.backend.delete_user(email_clean)

    def __contains__(self, email: object) -> bool:
        if not isinstance(email, str):
            return False
        email_clean = email.strip().lower()
        if email_clean in self._cache:
            return True
        user = self._store.backend.get_user(email_clean)
        if user is not None:
            self._cache[email_clean] = user
            return True
        return False

    def __iter__(self):
        return iter(self._all())

    def __len__(self) -> int:
        return len(self._all())

    def get(self, email: str, default=None):
        email_clean = (email or "").strip().lower()
        if email_clean in self._cache:
            return self._cache[email_clean]
        user = self._store.backend.get_user(email_clean)
        if user is not None:
            self._cache[email_clean] = user
            return user
        return default

    def keys(self):
        return self._all().keys()

    def values(self):
        return self._all().values()

    def items(self):
        return self._all().items()

    def clear(self) -> None:
        self._cache.clear()
        for email in list(self.keys()):
            self._store.backend.delete_user(email)

    def pop(self, email: str, *args):
        email_clean = (email or "").strip().lower()
        user = self._cache.pop(email_clean, None)
        if user is None:
            user = self._store.backend.get_user(email_clean)
        if user is None:
            if args:
                return args[0]
            raise KeyError(email)
        self._store.backend.delete_user(email_clean)
        return user



class _DictProxy:
    def __init__(self, getter, setter, deleter, all_fn=None):
        self._get = getter
        self._set = setter
        self._del = deleter
        self._all = all_fn

    def __getitem__(self, key):
        val = self._get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __setitem__(self, key, value):
        self._set(key, value)

    def __delitem__(self, key):
        self._del(key)

    def __contains__(self, key):
        return self._get(key) is not None

    def get(self, key, default=None):
        val = self._get(key)
        return default if val is None else val

    def pop(self, key, *args):
        val = self._get(key)
        if val is None:
            if args:
                return args[0]
            raise KeyError(key)
        self._del(key)
        return val

    def clear(self):
        if self._all:
            for k in list(self._all().keys()):
                self._del(k)

    def keys(self):
        return self._all().keys() if self._all else {}.keys()

    def items(self):
        return self._all().items() if self._all else {}.items()

    def values(self):
        return self._all().values() if self._all else {}.values()

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(list(self.keys()))


class Storage:
    def __init__(self) -> None:
        self.backend = get_store_backend()

        self.users = _UsersProxy(self)
        self.username_index: Dict[str, str] = {}
        self._sync_username_index()

        self.otp_storage = _DictProxy(
            self.backend.get_otp, self.backend.set_otp, self.backend.delete_otp
        )
        self.dynamic_passwords = _DictProxy(
            self.backend.get_dynamic_password,
            self.backend.set_dynamic_password,
            self.backend.delete_dynamic_password,
        )
        self.verification_tokens = _DictProxy(
            self.backend.get_verification_token,
            self.backend.set_verification_token,
            self.backend.delete_verification_token,
        )
        self.reset_tokens = _DictProxy(
            self.backend.get_reset_token,
            self.backend.set_reset_token,
            self.backend.delete_reset_token,
        )
        self.invite_links = _DictProxy(
            self.backend.get_invite,
            self.backend.set_invite,
            self.backend.delete_invite,
            all_fn=self.backend.all_invites,
        )

        if isinstance(self.backend, MemoryRepository):
            self.chat_rooms = self.backend.chat_rooms
            self.private_rooms = self.backend.private_rooms
            self.room_files = self.backend.room_files
            self.activity_logs = self.backend.activity_logs
            self.username_index = self.backend.username_index
        else:
            self.chat_rooms = defaultdict(list)
            self.private_rooms = {}
            self.room_files = defaultdict(list)
            self.activity_logs: List[dict] = []

        self.rate_limits: Dict[str, list] = defaultdict(list)
        self.active_users: Dict[str, dict] = {}
        self.groups: Dict[str, dict] = {}
        self.message_lifecycle = {
            "retention_days": 30,
            "soft_deleted_messages": set(),
        }

    def _sync_username_index(self) -> None:
        if isinstance(self.backend, MemoryRepository):
            return
        try:
            for email, user in self.backend.all_users().items():
                uname = user.get("username")
                if uname:
                    self.username_index[uname.lower()] = email
        except Exception:
            pass

    def get_user(self, email: str) -> Optional[dict]:
        email_clean = (email or "").strip().lower()
        if email_clean in self.users._cache:
            return self.users._cache[email_clean]
        user = self.backend.get_user(email_clean)
        if user is not None:
            self.users._cache[email_clean] = user
        return user

    def set_user(self, email: str, data: dict) -> None:
        email = (email or "").strip().lower()
        self.users._cache[email] = data
        self.backend.set_user(email, data)
        username = data.get("username")
        if username:
            key = username.strip().lower()
            self.username_index[key] = email
            self.username_index[username.strip()] = email

    def resolve_email(self, username_or_email: str) -> Optional[str]:
        return self.backend.resolve_email(username_or_email)

    def delete_user(self, email: str) -> None:
        email = (email or "").strip().lower()
        self.users.pop(email, None)
        self.backend.delete_user(email)
        for uname, em in list(self.username_index.items()):
            if (em or "").strip().lower() == email:
                self.username_index.pop(uname, None)

    def all_users(self) -> Dict[str, dict]:
        return _safe_dict(self.backend.all_users())

    def reload_backend(self) -> None:
        from cipherchat.database.repositories.factory import reset_store_backend
        reset_store_backend()
        self.__init__()


store = Storage()


def _repair_store() -> None:
    global store
    if not hasattr(store, "set_user"):
        store = Storage()
    for _name, _default in (
        ("active_users", {}),
        ("chat_rooms", {}),
        ("private_rooms", {}),
        ("groups", {}),
        ("activity_logs", []),
        ("username_index", {}),
    ):
        if not hasattr(store, _name) or getattr(store, _name) is None:
            setattr(store, _name, _default if _name != "activity_logs" else [])


_repair_store()
