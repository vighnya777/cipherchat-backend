"""Telegram-style group chats: creation, membership, and admin roles.

This subpackage is self-contained:
  - models.py    group schema + serialization
  - services.py  in-memory group CRUD / membership / role logic
  - routes.py    REST blueprint (mounted at /groups)
  - events.py    Socket.IO room-access checks for group rooms
"""

from cipherchat.chat.groups.routes import group_bp

__all__ = ["group_bp"]
