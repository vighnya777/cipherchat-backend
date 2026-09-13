"""PostgreSQL / SQLAlchemy-backed repository implementation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from cipherchat.database.models import (
    ActivityLog,
    DynamicPassword,
    Invitation,
    MediaFile,
    Message,
    MessageReaction,
    OTPRecord,
    PasswordResetToken,
    Room,
    User,
    VerificationToken,
)
from cipherchat.database.repositories.base import StoreBackend
from cipherchat.database.session import get_session


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class PostgresRepository(StoreBackend):
    def __init__(self, session_factory=None):
        self._sf = session_factory or get_session

    def _session(self) -> Session:
        return self._sf()

    # ---- Users ----
    def get_user(self, email: str) -> Optional[dict]:
        email = (email or "").strip().lower()
        with self._session() as s:
            row = s.scalar(select(User).where(User.email == email))
            return row.to_dict() if row else None

    def set_user(self, email: str, data: dict) -> None:
        email = email.strip().lower()
        with self._session() as s:
            row = s.scalar(select(User).where(User.email == email))
            if row is None:
                row = User(email=email, username=data.get("username") or email.split("@")[0])
                s.add(row)
            for field in (
                "username",
                "phone",
                "password_hash",
                "status",
                "verified",
                "role",
                "permissions",
                "profile",
                "login_count",
            ):
                if field in data:
                    setattr(row, field, data[field])
            # Also extract phone from profile if present
            if not getattr(row, "phone", None):
                prof = data.get("profile") or {}
                if isinstance(prof, dict) and prof.get("phone"):
                    row.phone = str(prof["phone"]).strip()
            if "last_login" in data:
                row.last_login = _parse_dt(data["last_login"])
            if "last_seen" in data:
                row.last_seen = _parse_dt(data["last_seen"])
            s.commit()

    def delete_user(self, email: str) -> None:
        email = email.strip().lower()
        with self._session() as s:
            s.execute(delete(User).where(User.email == email))
            s.commit()

    def all_users(self) -> Dict[str, dict]:
        with self._session() as s:
            rows = s.scalars(select(User)).all()
            return {r.email: r.to_dict() for r in rows}

    def resolve_email(self, username_or_email: str) -> Optional[str]:
        value = (username_or_email or "").strip().lower()
        if not value:
            return None
        with self._session() as s:
            by_email = s.scalar(select(User).where(User.email == value))
            if by_email:
                return by_email.email
            by_user = s.scalar(select(User).where(User.username == value))
            return by_user.email if by_user else None

    # ---- OTP ----
    def get_otp(self, email: str) -> Optional[dict]:
        with self._session() as s:
            row = s.scalar(select(OTPRecord).where(OTPRecord.email == email))
            if not row:
                return None
            return {"otp": row.otp, "expires": row.expires_at, "attempts": row.attempts}

    def set_otp(self, email: str, data: dict) -> None:
        with self._session() as s:
            row = s.scalar(select(OTPRecord).where(OTPRecord.email == email))
            if row is None:
                row = OTPRecord(email=email, otp=data["otp"], expires_at=data["expires"], attempts=data.get("attempts", 0))
                s.add(row)
            else:
                row.otp = data["otp"]
                row.expires_at = data["expires"]
                row.attempts = data.get("attempts", 0)
            s.commit()

    def delete_otp(self, email: str) -> None:
        with self._session() as s:
            s.execute(delete(OTPRecord).where(OTPRecord.email == email))
            s.commit()

    # ---- Dynamic password ----
    def get_dynamic_password(self, email: str) -> Optional[dict]:
        with self._session() as s:
            row = s.scalar(select(DynamicPassword).where(DynamicPassword.email == email))
            if not row:
                return None
            return {"password": row.password, "expires": row.expires_at}

    def set_dynamic_password(self, email: str, data: dict) -> None:
        with self._session() as s:
            row = s.scalar(select(DynamicPassword).where(DynamicPassword.email == email))
            if row is None:
                s.add(DynamicPassword(email=email, password=data["password"], expires_at=data["expires"]))
            else:
                row.password = data["password"]
                row.expires_at = data["expires"]
            s.commit()

    def delete_dynamic_password(self, email: str) -> None:
        with self._session() as s:
            s.execute(delete(DynamicPassword).where(DynamicPassword.email == email))
            s.commit()

    # ---- Tokens ----
    def get_verification_token(self, token: str) -> Optional[dict]:
        with self._session() as s:
            row = s.scalar(select(VerificationToken).where(VerificationToken.token == token))
            if not row:
                return None
            return {"email": row.email, "expires": row.expires_at}

    def set_verification_token(self, token: str, data: dict) -> None:
        with self._session() as s:
            s.execute(delete(VerificationToken).where(VerificationToken.token == token))
            s.add(VerificationToken(token=token, email=data["email"], expires_at=data["expires"]))
            s.commit()

    def delete_verification_token(self, token: str) -> None:
        with self._session() as s:
            s.execute(delete(VerificationToken).where(VerificationToken.token == token))
            s.commit()

    def get_reset_token(self, token: str) -> Optional[dict]:
        with self._session() as s:
            row = s.scalar(select(PasswordResetToken).where(PasswordResetToken.token == token))
            if not row:
                return None
            return {"email": row.email, "expires": row.expires_at}

    def set_reset_token(self, token: str, data: dict) -> None:
        with self._session() as s:
            s.execute(delete(PasswordResetToken).where(PasswordResetToken.token == token))
            s.add(PasswordResetToken(token=token, email=data["email"], expires_at=data["expires"]))
            s.commit()

    def delete_reset_token(self, token: str) -> None:
        with self._session() as s:
            s.execute(delete(PasswordResetToken).where(PasswordResetToken.token == token))
            s.commit()

    # ---- Messages / rooms ----
    def ensure_room(self, room_key: str, room_type: str = "group", created_by: str = None) -> None:
        with self._session() as s:
            existing = s.scalar(select(Room).where(Room.room_key == room_key))
            if not existing:
                s.add(Room(room_key=room_key, room_type=room_type, created_by=created_by, name=room_key))
                s.commit()

    def delete_room(self, room_key: str) -> bool:
        with self._session() as s:
            room = s.scalar(select(Room).where(Room.room_key == room_key))
            # Soft-delete the room's messages (same convention get_messages() already
            # relies on via Message.soft_deleted) rather than hard-deleting message
            # history outright.
            s.execute(
                Message.__table__.update()
                .where(Message.room_key == room_key)
                .values(soft_deleted=True)
            )
            if room:
                # RoomMember rows cascade via ondelete="CASCADE" on the FK.
                s.delete(room)
            s.commit()
            return room is not None

    def append_message(self, room_key: str, message: dict, is_private: bool = False) -> dict:
        self.ensure_room(room_key, "dm" if is_private or room_key.startswith("dm_") else "group")
        mid = message.get("message_id") or message.get("id") or __import__("uuid").uuid4().hex
        with self._session() as s:
            row = Message(
                message_id=mid,
                room_key=room_key,
                sender_email=message.get("email") or message.get("sender_email", ""),
                body=message.get("message") or message.get("body") or "",
                attachment=message.get("attachment"),
                reply_to=message.get("reply_to"),
                forwarded_from=message.get("forwarded_from"),
                pinned=bool(message.get("pinned", False)),
            )
            s.add(row)
            s.commit()
            message["message_id"] = mid
            message["id"] = mid
            return message

    def get_messages(self, room_key: str, limit: int = 100) -> List[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(Message)
                .where(Message.room_key == room_key, Message.soft_deleted.is_(False))
                .order_by(Message.created_at.desc())
                .limit(limit)
            ).all()
            result = []
            for r in reversed(rows):
                reactions = s.scalars(
                    select(MessageReaction).where(MessageReaction.message_id == r.message_id)
                ).all()
                reaction_map: Dict[str, list] = {}
                for rx in reactions:
                    reaction_map.setdefault(rx.emoji, []).append(rx.user_email)
                result.append(
                    {
                        "message_id": r.message_id,
                        "email": r.sender_email,
                        "message": r.body,
                        "room": r.room_key,
                        "timestamp": r.created_at.strftime("%H:%M:%S") if r.created_at else "",
                        "attachment": r.attachment,
                        "reply_to": r.reply_to,
                        "forwarded_from": r.forwarded_from,
                        "pinned": bool(r.pinned),
                        "edited_at": r.edited_at.isoformat() if r.edited_at else None,
                        "reactions": reaction_map,
                    }
                )
            return result

    def edit_message(self, message_id: str, new_body: str) -> bool:
        with self._session() as s:
            row = s.scalar(select(Message).where(Message.message_id == message_id))
            if row:
                row.body = new_body
                row.edited_at = datetime.utcnow()
                s.commit()
                return True
            return False

    def pin_message(self, message_id: str, pinned: bool = True) -> bool:
        with self._session() as s:
            row = s.scalar(select(Message).where(Message.message_id == message_id))
            if row:
                row.pinned = pinned
                s.commit()
                return True
            return False

    def delete_message(self, message_id: str) -> bool:
        with self._session() as s:
            row = s.scalar(select(Message).where(Message.message_id == message_id))
            if row:
                row.soft_deleted = True
                s.commit()
                return True
            return False


    def set_reaction(self, message_id: str, emoji: str, user_email: str, add: bool = True) -> dict:
        with self._session() as s:
            existing = s.scalar(
                select(MessageReaction).where(
                    MessageReaction.message_id == message_id,
                    MessageReaction.emoji == emoji,
                    MessageReaction.user_email == user_email,
                )
            )
            if add and not existing:
                s.add(MessageReaction(message_id=message_id, emoji=emoji, user_email=user_email))
            elif not add and existing:
                s.delete(existing)
            s.commit()
            all_rx = s.scalars(
                select(MessageReaction).where(MessageReaction.message_id == message_id)
            ).all()
            reaction_map: Dict[str, list] = {}
            for rx in all_rx:
                reaction_map.setdefault(rx.emoji, []).append(rx.user_email)
            return reaction_map

    # ---- Invitations ----
    def get_invite(self, code: str) -> Optional[dict]:
        with self._session() as s:
            row = s.scalar(select(Invitation).where(Invitation.code == code))
            if not row:
                return None
            return {
                "room": row.room_key,
                "created_by": row.created_by,
                "expires": row.expires_at,
                "max_uses": row.max_uses,
                "used_count": row.used_count,
                "users": row.used_by or [],
            }

    def set_invite(self, code: str, data: dict) -> None:
        with self._session() as s:
            row = s.scalar(select(Invitation).where(Invitation.code == code))
            if row is None:
                row = Invitation(
                    code=code,
                    room_key=data.get("room") or data.get("room_key", "general"),
                    created_by=data["created_by"],
                    max_uses=data.get("max_uses", 5),
                    used_count=data.get("used_count", 0),
                    used_by=data.get("users") or data.get("used_by") or [],
                    expires_at=data["expires"],
                )
                s.add(row)
            else:
                row.used_count = data.get("used_count", row.used_count)
                row.used_by = data.get("users") or data.get("used_by") or row.used_by
            s.commit()

    def delete_invite(self, code: str) -> None:
        with self._session() as s:
            s.execute(delete(Invitation).where(Invitation.code == code))
            s.commit()

    def all_invites(self) -> Dict[str, dict]:
        with self._session() as s:
            rows = s.scalars(select(Invitation)).all()
            return {
                r.code: {
                    "room": r.room_key,
                    "created_by": r.created_by,
                    "expires": r.expires_at,
                    "max_uses": r.max_uses,
                    "used_count": r.used_count,
                    "users": r.used_by or [],
                }
                for r in rows
            }

    # ---- Media ----
    def add_media(self, room_key: str, meta: dict) -> None:
        with self._session() as s:
            s.add(
                MediaFile(
                    room_key=room_key,
                    url=meta.get("url", ""),
                    filename=meta.get("name") or meta.get("filename", ""),
                    media_type=meta.get("type") or meta.get("media_type", "document"),
                    uploaded_by=meta.get("uploaded_by", ""),
                )
            )
            s.commit()

    def list_media(self, room_key: str) -> List[dict]:
        with self._session() as s:
            rows = s.scalars(select(MediaFile).where(MediaFile.room_key == room_key)).all()
            return [
                {
                    "url": r.url,
                    "name": r.filename,
                    "type": r.media_type,
                    "uploaded_by": r.uploaded_by,
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    # ---- Activity ----
    def add_activity(self, entry: dict) -> None:
        with self._session() as s:
            s.add(
                ActivityLog(
                    email=entry.get("email", ""),
                    action=entry.get("action", ""),
                    details=entry.get("details"),
                    ip=entry.get("ip"),
                    user_agent=entry.get("user_agent"),
                )
            )
            s.commit()

    def list_activity(self, limit: int = 100) -> List[dict]:
        with self._session() as s:
            rows = s.scalars(
                select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "email": r.email,
                    "action": r.action,
                    "timestamp": r.created_at.isoformat() if r.created_at else None,
                    "ip": r.ip,
                    "user_agent": r.user_agent,
                    "details": r.details,
                }
                for r in reversed(rows)
            ]

    def clear_activity(self) -> int:
        with self._session() as s:
            count = s.scalar(select(ActivityLog.id))  # cheap existence
            result = s.execute(delete(ActivityLog))
            s.commit()
            return result.rowcount or 0
