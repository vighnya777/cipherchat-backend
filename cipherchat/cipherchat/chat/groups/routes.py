"""REST endpoints for group creation and membership management."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from cipherchat.chat.groups import services as group_svc
from cipherchat.chat.groups.models import GroupError, serialize_group

group_bp = Blueprint("groups", __name__, url_prefix="/groups")


def _require_auth():
    return session.get("authenticated") and session.get("user_email")


def _broadcast(group: dict, event: str = "group_updated", **extra) -> None:
    try:
        from cipherchat.extensions import socketio

        payload = {"group": serialize_group(group), **extra}
        socketio.emit(event, payload, room=group["id"])
        for member_email in group.get("members", []):
            socketio.emit(event, payload, room=f"user_{member_email}")
        removed_email = extra.get("removed_email")
        if removed_email:
            socketio.emit(event, payload, room=f"user_{removed_email}")
    except Exception:
        pass


@group_bp.route("", methods=["POST"])
def create_group():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    members = data.get("members") or []
    if not isinstance(members, list):
        return jsonify({"error": "Invalid members list."}), 400
    try:
        group = group_svc.create_group(
            data.get("name", ""),
            session["user_email"],
            members,
            avatar=data.get("avatar"),
            description=data.get("description"),
            members_can_add=bool(data.get("members_can_add", False)),
        )
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group, event="group_created")
    return jsonify({"success": True, "group": serialize_group(group, session["user_email"])})


@group_bp.route("", methods=["GET"])
def list_my_groups():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    groups = [serialize_group(g, email) for g in group_svc.get_user_groups(email)]
    return jsonify(groups)


@group_bp.route("/<group_id>", methods=["GET"])
def get_group(group_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    group = group_svc.get_group(group_id)
    if not group or email not in group.get("members", []):
        return jsonify({"error": "not found"}), 404
    return jsonify(serialize_group(group, email))


@group_bp.route("/<group_id>", methods=["PATCH"])
def rename_group(group_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        group = group_svc.update_group_info(
            group_id,
            session["user_email"],
            name=data.get("name"),
            description=data.get("description"),
            avatar=data.get("avatar"),
            members_can_add=data.get("members_can_add"),
        )
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group)
    return jsonify({"success": True, "group": serialize_group(group, session["user_email"])})


@group_bp.route("/<group_id>/members", methods=["POST"])
def add_member(group_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        group = group_svc.add_member(group_id, session["user_email"], data.get("email", ""))
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group, event="group_updated")
    return jsonify({"success": True, "group": serialize_group(group, session["user_email"])})


@group_bp.route("/<group_id>/members/<path:target_email>", methods=["DELETE"])
def remove_member(group_id, target_email):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    try:
        group = group_svc.remove_member(group_id, session["user_email"], target_email)
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group, event="group_member_removed", removed_email=target_email.strip().lower())
    return jsonify({"success": True, "group": serialize_group(group, session["user_email"])})


@group_bp.route("/<group_id>/admins", methods=["POST"])
def set_admin(group_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    make_admin = bool(data.get("make_admin", True))
    try:
        group = group_svc.set_admin(group_id, session["user_email"], data.get("email", ""), make_admin)
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group)
    return jsonify({"success": True, "group": serialize_group(group, session["user_email"])})


@group_bp.route("/<group_id>/leave", methods=["POST"])
def leave_group(group_id):
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401
    email = session["user_email"]
    try:
        group = group_svc.remove_member(group_id, email, email)
    except GroupError as exc:
        return jsonify({"error": str(exc)}), exc.status
    _broadcast(group, event="group_member_removed", removed_email=email)
    return jsonify({"success": True})
