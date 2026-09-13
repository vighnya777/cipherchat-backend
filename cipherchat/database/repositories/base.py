"""Abstract store backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class StoreBackend(ABC):
    """Contract used by the application store facade."""

    # Users
    @abstractmethod
    def get_user(self, email: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_user(self, email: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_user(self, email: str) -> None:
        ...

    @abstractmethod
    def all_users(self) -> Dict[str, dict]:
        ...

    @abstractmethod
    def resolve_email(self, username_or_email: str) -> Optional[str]:
        ...

    # OTP
    @abstractmethod
    def get_otp(self, email: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_otp(self, email: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_otp(self, email: str) -> None:
        ...

    # Dynamic password
    @abstractmethod
    def get_dynamic_password(self, email: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_dynamic_password(self, email: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_dynamic_password(self, email: str) -> None:
        ...

    # Tokens
    @abstractmethod
    def get_verification_token(self, token: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_verification_token(self, token: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_verification_token(self, token: str) -> None:
        ...

    @abstractmethod
    def get_reset_token(self, token: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_reset_token(self, token: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_reset_token(self, token: str) -> None:
        ...

    # Messages / rooms
    @abstractmethod
    def append_message(self, room_key: str, message: dict, is_private: bool = False) -> dict:
        ...

    @abstractmethod
    def get_messages(self, room_key: str, limit: int = 100) -> List[dict]:
        ...

    @abstractmethod
    def ensure_room(self, room_key: str, room_type: str = "group", created_by: str = None) -> None:
        ...

    def edit_message(self, message_id: str, new_body: str) -> bool:
        return False

    def delete_message(self, message_id: str) -> bool:
        return False

    def pin_message(self, message_id: str, pinned: bool = True) -> bool:
        return False

    # Invitations
    @abstractmethod
    def get_invite(self, code: str) -> Optional[dict]:
        ...

    @abstractmethod
    def set_invite(self, code: str, data: dict) -> None:
        ...

    @abstractmethod
    def delete_invite(self, code: str) -> None:
        ...

    @abstractmethod
    def all_invites(self) -> Dict[str, dict]:
        ...

    # Media
    @abstractmethod
    def add_media(self, room_key: str, meta: dict) -> None:
        ...

    @abstractmethod
    def list_media(self, room_key: str) -> List[dict]:
        ...

    # Activity
    @abstractmethod
    def add_activity(self, entry: dict) -> None:
        ...

    @abstractmethod
    def list_activity(self, limit: int = 100) -> List[dict]:
        ...

    @abstractmethod
    def clear_activity(self) -> int:
        ...

    # Reactions
    @abstractmethod
    def set_reaction(self, message_id: str, emoji: str, user_email: str, add: bool = True) -> dict:
        ...
