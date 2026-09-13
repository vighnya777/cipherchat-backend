"""Chat connection, contacts, and private-room identity tests."""

from __future__ import annotations

from cipherchat.chat.services import get_contacts, get_or_create_private_room, private_room_id
from cipherchat.services.security import hash_password
from cipherchat.services.storage import store


def _seed(email, username, status="approved"):
    store.set_user(
        email,
        {
            "username": username,
            "status": status,
            "verified": True,
            "role": "user",
            "password_hash": hash_password("Secure1"),
            "profile": {},
            "login_count": 0,
            "permissions": [],
        },
    )


def test_private_room_deterministic():
    a, b = "alice@example.com", "bob@example.com"
    r1 = get_or_create_private_room(a, b)
    r2 = get_or_create_private_room(b, a)
    assert r1 == r2
    assert r1 == private_room_id(a, b)
    assert r1.startswith("dm_")


def test_contacts_dedupe(app):
    _seed("c1@example.com", "Charlie")
    # duplicate key variants should not create two contacts
    store.username_index["Charlie"] = "c1@example.com"
    store.username_index["charlie"] = "c1@example.com"
    contacts = get_contacts("admin@test.local")
    emails = [c["email"] for c in contacts]
    assert emails.count("c1@example.com") <= 1
    assert all(c["email"] == c["email"].lower() for c in contacts)


def test_get_contacts_api_shape(client, app):
    _seed("z@example.com", "Zed")
    with client.session_transaction() as s:
        s["authenticated"] = True
        s["user_email"] = "admin@test.local"
    resp = client.get("/get-contacts")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("success") is True
    assert isinstance(data.get("contacts"), list)


def test_chat_requires_auth(client):
    resp = client.get("/chat", follow_redirects=False)
    assert resp.status_code in (301, 302, 401)


def test_chat_page_when_authenticated(client, app):
    with client.session_transaction() as s:
        s["authenticated"] = True
        s["user_email"] = "admin@test.local"
        s["username"] = "admin"
    resp = client.get("/chat")
    assert resp.status_code == 200
    assert b"connStatusBar" in resp.data or b"Connecting" in resp.data
    assert b"connection_ack" in resp.data or b"socket" in resp.data
