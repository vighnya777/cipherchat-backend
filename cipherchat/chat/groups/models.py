"""Group data schema.

Groups are stored in-memory on the shared ``store`` object (same pattern the
rest of CipherChat uses for active sessions / room state). A group looks
like:

    {
        "id": "grp_<hex>",
        "name": str,
        "avatar": str | None,
        "owner": str,           # email, always kept in "admins" and "members"
        "admins": [str, ...],   # emails with management rights
        "members": [str, ...],  # all emails in the group
        "created_at": iso8601 str,
    }
"""

from __future__ import annotations

GROUP_ROOM_PREFIX = "grp_"


def is_group_room(room: str) -> bool:
    return bool(room) and room.startswith(GROUP_ROOM_PREFIX)


def group_room_id(group_id: str) -> str:
    return group_id if is_group_room(group_id) else f"{GROUP_ROOM_PREFIX}{group_id}"


class GroupError(Exception):
    """Raised for any group operation that should surface as an API error."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def serialize_group(group: dict, viewer_email: str | None = None) -> dict:
    """Shape a group dict for API/socket responses."""
    if not group:
        return {}
    data = {
        "id": group["id"],
        "name": group["name"],
        "avatar": group.get("avatar"),
        "owner": group["owner"],
        "admins": list(group.get("admins", [])),
        "members": list(group.get("members", [])),
        "member_count": len(group.get("members", [])),
        "created_at": group.get("created_at"),
    }
    if viewer_email:
        data["is_admin"] = viewer_email in data["admins"]
        data["is_owner"] = viewer_email == data["owner"]
    return data
