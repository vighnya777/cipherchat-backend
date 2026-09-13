from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cipherchat.database.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    room_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachment: Mapped[Any] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    soft_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (
        UniqueConstraint("message_id", "emoji", "user_email", name="uq_reaction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("messages.message_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    emoji: Mapped[str] = mapped_column(String(32), nullable=False)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
