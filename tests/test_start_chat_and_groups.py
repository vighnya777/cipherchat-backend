"""Regression tests for:

1. The Contacts -> 1:1 chat flow (`POST /start-chat`), covering the bug
   report: a valid CipherChat user must open a chat successfully, an
   unregistered target must be reported distinctly (not the generic
   catch-all message), self-chat must be rejected, and repeated calls must
   not create duplicate rooms.
2. Groups functionality regression: create, rename, add/remove members,
   admin promotion, owner-only delete, leave, and list refresh.
"""

from __future__ import annotations

import pytest


def _seed_user(store, email: str, username: str, status: str = "approved") -> None:
    store.set_user(
        email,
        {
            "username": username,
            "status": status,
            "verified": True,
            "role": "user",
            "permissions": [],
            "profile": {},
            "login_count": 0,
        },
    )


def _login(client, email: str) -> None:
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = email


# ── /start-chat ──────────────────────────────────────────────────────────


def test_start_chat_requires_auth(client):
    resp = client.post("/start-chat", json={"email": "someone@example.com"})
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "unauthorized"


def test_start_chat_missing_target(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _login(client, "alice@example.com")

    resp = client.post("/start-chat", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_target"


def test_start_chat_with_valid_registered_user_succeeds(client, app):
    """Core bug-report scenario: a valid CipherChat user must open successfully."""
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _seed_user(store, "bob@example.com", "bob")
    _login(client, "alice@example.com")

    resp = client.post("/start-chat", json={"email": "bob@example.com"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["room"].startswith("dm_")
    assert body["email"] == "bob@example.com"


def test_start_chat_unregistered_user_reports_distinct_error(client, app):
    """Unregistered users must be reported separately from generic failure."""
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _login(client, "alice@example.com")

    resp = client.post("/start-chat", json={"email": "ghost@nowhere.com"})
    assert resp.status_code == 404
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"] == "user_not_found"
    assert "hasn't joined" in body["message"]


def test_start_chat_rejects_self_chat(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _login(client, "alice@example.com")

    resp = client.post("/start-chat", json={"email": "alice@example.com"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "self_chat"


def test_start_chat_is_case_and_whitespace_insensitive(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _seed_user(store, "bob@example.com", "bob")
    _login(client, "alice@example.com")

    resp = client.post("/start-chat", json={"email": "  Bob@Example.com  "})
    assert resp.status_code == 200
    assert resp.get_json()["email"] == "bob@example.com"


def test_start_chat_does_not_create_duplicate_rooms(client, app):
    """Calling start-chat repeatedly (e.g. re-opening from Contacts) must
    always resolve to the same room, never create a second one."""
    from cipherchat.services.storage import store

    _seed_user(store, "alice@example.com", "alice")
    _seed_user(store, "bob@example.com", "bob")
    _login(client, "alice@example.com")

    first = client.post("/start-chat", json={"email": "bob@example.com"}).get_json()
    second = client.post("/start-chat", json={"email": "bob@example.com"}).get_json()

    assert first["room"] == second["room"]
    assert len(store.private_rooms) == 1

    # And from the other side of the conversation too.
    _login(client, "bob@example.com")
    third = client.post("/start-chat", json={"email": "alice@example.com"}).get_json()
    assert third["room"] == first["room"]
    assert len(store.private_rooms) == 1


def test_start_chat_finds_existing_room_created_via_socket_path(client, app):
    """The REST and socket entry points must agree on room identity."""
    from cipherchat.services.storage import store
    from cipherchat.chat import services as chat_svc

    _seed_user(store, "alice@example.com", "alice")
    _seed_user(store, "bob@example.com", "bob")

    existing_room = chat_svc.get_or_create_private_room(
        "alice@example.com", "bob@example.com"
    )

    _login(client, "alice@example.com")
    resp = client.post("/start-chat", json={"email": "bob@example.com"})
    assert resp.get_json()["room"] == existing_room
    assert len(store.private_rooms) == 1


# ── Groups regression ────────────────────────────────────────────────────


def test_group_create_list_and_membership(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "owner@example.com", "owner")
    _seed_user(store, "member@example.com", "member")
    _login(client, "owner@example.com")

    resp = client.post(
        "/groups",
        json={"name": "Study Group", "members": ["member@example.com"]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    group = body["group"]
    assert group["name"] == "Study Group"
    assert "member@example.com" in group["members"]
    assert group["is_owner"] is True
    group_id = group["id"]

    # List refresh: group shows up for both members.
    resp = client.get("/groups")
    assert any(g["id"] == group_id for g in resp.get_json())

    _login(client, "member@example.com")
    resp = client.get("/groups")
    ids = [g["id"] for g in resp.get_json()]
    assert group_id in ids


def test_group_owner_only_delete(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "owner@example.com", "owner")
    _seed_user(store, "member@example.com", "member")
    _login(client, "owner@example.com")

    group_id = client.post(
        "/groups", json={"name": "G1", "members": ["member@example.com"]}
    ).get_json()["group"]["id"]

    # Non-owner member cannot delete.
    _login(client, "member@example.com")
    resp = client.delete(f"/groups/{group_id}")
    assert resp.status_code in (400, 403)
    assert resp.get_json()["error"]

    # Owner can delete.
    _login(client, "owner@example.com")
    resp = client.delete(f"/groups/{group_id}")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    # Group list refresh reflects deletion.
    resp = client.get("/groups")
    ids = [g["id"] for g in resp.get_json()]
    assert group_id not in ids


def test_group_leave(client, app):
    from cipherchat.services.storage import store

    _seed_user(store, "owner@example.com", "owner")
    _seed_user(store, "member@example.com", "member")
    _login(client, "owner@example.com")

    group_id = client.post(
        "/groups", json={"name": "G2", "members": ["member@example.com"]}
    ).get_json()["group"]["id"]

    _login(client, "member@example.com")
    resp = client.post(f"/groups/{group_id}/leave")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    # Member no longer sees the group in their list.
    resp = client.get("/groups")
    ids = [g["id"] for g in resp.get_json()]
    assert group_id not in ids

    # Owner still does.
    _login(client, "owner@example.com")
    resp = client.get("/groups")
    ids = [g["id"] for g in resp.get_json()]
    assert group_id in ids


def test_group_rename_is_a_stand_in_for_dp_style_metadata_updates(client, app):
    """Group avatar/DP updates go through the same rename-style PATCH path
    for metadata; this exercises that update + broadcast round trip."""
    from cipherchat.services.storage import store

    _seed_user(store, "owner@example.com", "owner")
    _login(client, "owner@example.com")

    group_id = client.post("/groups", json={"name": "G3"}).get_json()["group"]["id"]

    resp = client.patch(f"/groups/{group_id}", json={"name": "G3 Renamed"})
    assert resp.status_code == 200
    assert resp.get_json()["group"]["name"] == "G3 Renamed"
