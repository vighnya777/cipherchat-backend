"""Group domain services — create, membership, and role management."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from cipherchat.chat.groups.models import GroupError
from cipherchat.services.storage import store

if not hasattr(store, "groups"):
    store.groups = {}


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _resolve_user_identifier(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = _norm(value)
    if not value:
        return None
    if value in store.users:
        return value
    return store.username_index.get(value)


def create_group(name: str, owner: str, member_emails: Optional[List[str]] = None) -> dict:
    name = (name or "").strip()[:80]
    if not name:
        raise GroupError("Group name is required.")
    owner = _norm(owner)
    if owner not in store.users:
        raise GroupError("Owner account not found.", 404)

    members = {owner}
    for raw in member_emails or []:
        resolved = _resolve_user_identifier(raw)
        if resolved and resolved in store.users:
            members.add(resolved)

    group_id = f"grp_{uuid.uuid4().hex[:12]}"
    group = {
        "id": group_id,
        "name": name,
        "avatar": None,
        "owner": owner,
        "admins": [owner],
        "members": sorted(members),
        "created_at": datetime.now().isoformat(),
    }
    store.groups[group_id] = group
    return group


def get_group(group_id: str) -> Optional[dict]:
    return store.groups.get(group_id)


def require_group(group_id: str) -> dict:
    group = store.groups.get(group_id)
    if not group:
        raise GroupError("Group not found.", 404)
    return group


def get_user_groups(email: str) -> List[dict]:
    email = _norm(email)
    return [g for g in store.groups.values() if email in g.get("members", [])]


def is_member(group_id: str, email: str) -> bool:
    group = store.groups.get(group_id)
    return bool(group and _norm(email) in group.get("members", []))


def is_admin(group_id: str, email: str) -> bool:
    group = store.groups.get(group_id)
    return bool(group and _norm(email) in group.get("admins", []))


def rename_group(group_id: str, actor: str, new_name: str) -> dict:
    group = require_group(group_id)
    if not is_admin(group_id, actor):
        raise GroupError("Only group admins can rename the group.", 403)
    new_name = (new_name or "").strip()[:80]
    if not new_name:
        raise GroupError("Group name is required.")
    group["name"] = new_name
    return group


def add_member(group_id: str, actor: str, target: str) -> dict:
    group = require_group(group_id)
    if not is_admin(group_id, actor):
        raise GroupError("Only group admins can add members.", 403)
    target = _resolve_user_identifier(target)
    if not target or target not in store.users:
        raise GroupError("User not found.", 404)
    if target in group["members"]:
        raise GroupError("User is already in this group.", 409)
    group["members"] = sorted(set(group["members"]) | {target})
    return group


def remove_member(group_id: str, actor: str, target: str) -> dict:
    group = require_group(group_id)
    actor = _norm(actor)
    target = _norm(target)
    is_self_leave = actor == target
    if not is_self_leave and not is_admin(group_id, actor):
        raise GroupError("Only group admins can remove members.", 403)
    if target not in group["members"]:
        raise GroupError("User is not a member of this group.", 404)
    if target == group["owner"] and not is_self_leave:
        raise GroupError("The group owner cannot be removed.", 403)
    group["members"] = [m for m in group["members"] if m != target]
    group["admins"] = [a for a in group["admins"] if a != target]
    if not group["members"]:
        store.groups.pop(group_id, None)
        return group
    if target == group["owner"] and group["members"]:
        # Ownership passes to the longest-standing admin, or the first member.
        next_owner = next(iter(group["admins"]), group["members"][0])
        group["owner"] = next_owner
        if next_owner not in group["admins"]:
            group["admins"].append(next_owner)
    return group


def set_admin(group_id: str, actor: str, target: str, make_admin: bool) -> dict:
    group = require_group(group_id)
    if not is_admin(group_id, actor):
        raise GroupError("Only group admins can manage roles.", 403)
    target = _resolve_user_identifier(target)
    if not target or target not in group["members"]:
        raise GroupError("User is not a member of this group.", 404)
    if target == group["owner"] and not make_admin:
        raise GroupError("The group owner must stay an admin.", 403)
    admins = set(group["admins"])
    if make_admin:
        admins.add(target)
    else:
        admins.discard(target)
    group["admins"] = sorted(admins)
    return group
