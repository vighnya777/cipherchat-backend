"""Socket.IO access-control helpers for group rooms.

Group chat reuses the same ``send_message`` / ``join_room`` / history
pipeline as every other room in cipherchat/chat/events.py — the only thing
that differs is that a "grp_" room is membership-gated. This module is
imported from chat/events.py to keep that check in one place.
"""

from __future__ import annotations

from cipherchat.chat.groups import services as group_svc
from cipherchat.chat.groups.models import is_group_room


def can_access_room(room: str, email: str) -> bool:
    if not is_group_room(room):
        return True
    return group_svc.is_member(room, email)
