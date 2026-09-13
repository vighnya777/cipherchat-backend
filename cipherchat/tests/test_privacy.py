"""Privacy: no global online-user dumps; search-only discovery."""

from __future__ import annotations

from cipherchat.chat.services import get_contacts, get_existing_conversations, search_users
from cipherchat.services.security import hash_password
from cipherchat.services.storage import store


def _seed(email, username="user", status="approved"):
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


def test_contacts_empty_without_prior_chat(app):
    _seed("stranger@example.com", "stranger")
    contacts = get_contacts("admin@test.local")
    emails = [c["email"] for c in contacts]
    assert "stranger@example.com" not in emails


def test_search_requires_query(app):
    _seed("rahul@example.com", "rahul")
    assert search_users("", "admin@test.local") == []
    assert search_users("r", "admin@test.local") == []
    hits = search_users("rahul", "admin@test.local")
    assert any(h["email"] == "rahul@example.com" for h in hits)


def test_search_api_auth_required(client):
    resp = client.get("/search-users?q=rahul")
    assert resp.status_code in (401, 302)


def test_search_api_returns_matches(client, app):
    _seed("rahul@example.com", "rahul")
    with client.session_transaction() as s:
        s["authenticated"] = True
        s["user_email"] = "admin@test.local"
    resp = client.get("/search-users?q=rah")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert any(r["email"] == "rahul@example.com" for r in data["results"])


def test_get_contacts_no_global_dump(client, app):
    _seed("a@example.com", "aaa")
    _seed("b@example.com", "bbb")
    with client.session_transaction() as s:
        s["authenticated"] = True
        s["user_email"] = "admin@test.local"
    resp = client.get("/get-contacts")
    data = resp.get_json()
    assert data["success"] is True
    # Without prior DMs, contacts should not list all users
    emails = [c["email"] for c in data.get("contacts", [])]
    assert "a@example.com" not in emails
    assert "b@example.com" not in emails


def test_conversations_include_general(client, app):
    with client.session_transaction() as s:
        s["authenticated"] = True
        s["user_email"] = "admin@test.local"
    resp = client.get("/get-contacts")
    data = resp.get_json()
    ids = [c["id"] for c in data.get("conversations", [])]
    assert "general" in ids


def test_existing_conversations_use_display_name(app):
    _seed("rahul@example.com", "rahul")
    store.users["rahul@example.com"]["profile"]["display_name"] = "Rahul"
    store.private_rooms["dm_test"] = {
        "users": ["admin@test.local", "rahul@example.com"],
        "messages": [],
    }
    conversations = get_existing_conversations("admin@test.local")
    assert any(c["id"] == "dm_test" and c["name"] == "Rahul" for c in conversations)


def test_get_contacts_returns_display_name(app):
    _seed("alice@example.com", "alice")
    store.users["alice@example.com"]["profile"]["display_name"] = "Alice"
    store.private_rooms["dm_test2"] = {
        "users": ["admin@test.local", "alice@example.com"],
        "messages": [],
    }
    contacts = get_contacts("admin@test.local")
    assert any(c["email"] == "alice@example.com" and c["display_name"] == "Alice" for c in contacts)
