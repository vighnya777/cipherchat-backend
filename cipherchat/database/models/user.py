from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cipherchat.database.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    permissions: Mapped[Any] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=list)
    profile: Mapped[Any] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "phone": self.phone or (self.profile or {}).get("phone"),
            "password_hash": self.password_hash,
            "status": self.status,
            "verified": self.verified,
            "role": self.role,
            "permissions": self.permissions or [],
            "profile": self.profile or {},
            "login_count": self.login_count or 0,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
