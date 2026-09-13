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
    """Dict-like view over backend users — does NOT inherit dict to avoid
    CPython falling back to the empty base dict for .items()/.keys() etc."""

    def __init__(self, store: "Storage"):
        self._store = store

    def _all(self) -> dict:
        try:
            result = self._store.backend.all_users()
            return _safe_dict(result)
        except Exception:
            return {}

    def __getitem__(self, email: str):
        user = self._store.backend.get_user(email)
        if user is None:
            raise KeyError(email)
        return user

    def __setitem__(self, email: str, data: dict) -> None:
        self._store.backend.set_user(email, data)

    def __delitem__(self, email: str) -> None:
        self._store.backend.delete_user(email)

    def __contains__(self, email: object) -> bool:
        if not isinstance(email, str):
            return False
        return self._store.backend.get_user(email) is not None

    def __iter__(self):
        return iter(self._all())

    def __len__(self) -> int:
        return len(self._all())

    def get(self, email: str, default=None):
        user = self._store.backend.get_user(email)
        return user if user is not None else default

    def keys(self):
        return self._all().keys()

    def values(self):
        return self._all().values()

    def items(self):
        return self._all().items()

    def clear(self) -> None:
        for email in list(self.keys()):
            self._store.backend.delete_user(email)

    def pop(self, email: str, *args):
        user = self.get(email)
        if user is None:
            if args:
                return args[0]
            raise KeyError(email)
        self._store.backend.delete_user(email)
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
        return self.backend.get_user(email)

    def set_user(self, email: str, data: dict) -> None:
        email = (email or "").strip().lower()
        self.backend.set_user(email, data)
        username = data.get("username")
        if username:
            key = username.strip().lower()
            self.username_index[key] = email
            self.username_index[username.strip()] = email

    def resolve_email(self, username_or_email: str) -> Optional[str]:
        return self.backend.resolve_email(username_or_email)

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
        ("activity_logs", []),
        ("username_index", {}),
    ):
        if not hasattr(store, _name) or getattr(store, _name) is None:
            setattr(store, _name, _default if _name != "activity_logs" else [])


_repair_store()
