"""Database persistence tests (SQLAlchemy – SQLite for CI, PostgreSQL when DATABASE_URL set)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

# Force SQLAlchemy for these tests
os.environ["USE_SQLALCHEMY"] = "1"
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/cipherchat_pytest.db")
os.environ.setdefault("SECRET_KEY", "test-secret-db")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("MASTER_PASSWORD", "TestMaster1!")


@pytest.fixture()
def db_backend():
    from cipherchat.database.repositories.factory import get_store_backend, reset_store_backend
    from cipherchat.database.session import get_engine, init_db
    from cipherchat.database.models import Base
    from cipherchat.config import get_config

    # Clear cached engine
    get_engine.cache_clear()
    reset_store_backend()

    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    backend = get_store_backend(force_reload=True)
    yield backend

    Base.metadata.drop_all(bind=engine)
    reset_store_backend()
    get_engine.cache_clear()


def test_user_create_and_get(db_backend):
    db_backend.set_user(
        "alice@example.com",
        {
            "username": "alice",
            "status": "approved",
            "verified": True,
            "role": "user",
            "password_hash": "argon2:fake",
            "permissions": [],
            "profile": {},
            "login_count": 0,
        },
    )
    user = db_backend.get_user("alice@example.com")
    assert user is not None
    assert user["username"] == "alice"
    assert user["status"] == "approved"
    assert db_backend.resolve_email("alice") == "alice@example.com"


def test_user_unique_email(db_backend):
    data = {
        "username": "bob",
        "status": "pending",
        "verified": False,
        "role": "user",
        "permissions": [],
        "profile": {},
        "login_count": 0,
    }
    db_backend.set_user("bob@example.com", data)
    # Updating same email is fine
    data["username"] = "bobby"
    db_backend.set_user("bob@example.com", data)
    assert db_backend.get_user("bob@example.com")["username"] == "bobby"


def test_otp_lifecycle(db_backend):
    expires = datetime.utcnow() + timedelta(minutes=5)
    db_backend.set_otp("u@example.com", {"otp": "123456", "expires": expires, "attempts": 0})
    rec = db_backend.get_otp("u@example.com")
    assert rec["otp"] == "123456"
    db_backend.delete_otp("u@example.com")
    assert db_backend.get_otp("u@example.com") is None


def test_message_persistence(db_backend):
    msg = {
        "message_id": "mid1",
        "email": "alice@example.com",
        "message": "hello world",
        "room": "general",
    }
    db_backend.append_message("general", msg, is_private=False)
    messages = db_backend.get_messages("general")
    assert len(messages) >= 1
    assert messages[-1]["message"] == "hello world"
    assert messages[-1]["email"] == "alice@example.com"


def test_private_message(db_backend):
    room = "dm_ab12"
    db_backend.append_message(
        room,
        {"message_id": "p1", "email": "a@x.com", "message": "private hi"},
        is_private=True,
    )
    msgs = db_backend.get_messages(room)
    assert len(msgs) == 1
    assert msgs[0]["message"] == "private hi"


def test_invitation(db_backend):
    expires = datetime.utcnow() + timedelta(hours=24)
    db_backend.set_invite(
        "INVITE1",
        {
            "room": "general",
            "created_by": "admin@test.local",
            "expires": expires,
            "max_uses": 5,
            "used_count": 0,
            "users": [],
        },
    )
    inv = db_backend.get_invite("INVITE1")
    assert inv["room"] == "general"
    inv["used_count"] = 1
    db_backend.set_invite("INVITE1", inv)
    assert db_backend.get_invite("INVITE1")["used_count"] == 1
    db_backend.delete_invite("INVITE1")
    assert db_backend.get_invite("INVITE1") is None


def test_reaction(db_backend):
    db_backend.append_message(
        "general",
        {"message_id": "rx1", "email": "a@x.com", "message": "react me"},
    )
    reactions = db_backend.set_reaction("rx1", "👍", "a@x.com", add=True)
    assert "👍" in reactions
    assert "a@x.com" in reactions["👍"]
    reactions = db_backend.set_reaction("rx1", "👍", "a@x.com", add=False)
    assert reactions.get("👍", []) == []


def test_media_metadata(db_backend):
    db_backend.add_media(
        "general",
        {
            "url": "/uploads/x.png",
            "name": "x.png",
            "type": "image",
            "uploaded_by": "a@x.com",
        },
    )
    files = db_backend.list_media("general")
    assert len(files) == 1
    assert files[0]["type"] == "image"


def test_activity_log(db_backend):
    db_backend.add_activity(
        {"email": "a@x.com", "action": "login_success", "ip": "127.0.0.1", "user_agent": "test"}
    )
    logs = db_backend.list_activity(10)
    assert any(l["action"] == "login_success" for l in logs)
    n = db_backend.clear_activity()
    assert n >= 1
    assert db_backend.list_activity() == []


def test_bcrypt_to_argon2_upgrade():
    from cipherchat.services.security import hash_password, verify_password, needs_rehash, upgrade_password_hash_if_needed
    import bcrypt

    # Simulate legacy bcrypt hash (with prefix)
    raw = bcrypt.hashpw(b"OldPass1", bcrypt.gensalt()).decode()
    legacy = "bcrypt:" + raw
    assert verify_password("OldPass1", legacy)
    assert needs_rehash(legacy)
    upgraded = upgrade_password_hash_if_needed("OldPass1", legacy)
    assert upgraded is not None
    assert upgraded.startswith("argon2:")
    assert verify_password("OldPass1", upgraded)
    assert not needs_rehash(upgraded)


def test_password_reset_token(db_backend):
    expires = datetime.utcnow() + timedelta(hours=1)
    db_backend.set_reset_token("tok123", {"email": "a@x.com", "expires": expires})
    assert db_backend.get_reset_token("tok123")["email"] == "a@x.com"
    db_backend.delete_reset_token("tok123")
    assert db_backend.get_reset_token("tok123") is None


def test_verification_token(db_backend):
    expires = datetime.utcnow() + timedelta(hours=24)
    db_backend.set_verification_token("vtok", {"email": "b@x.com", "expires": expires})
    assert db_backend.get_verification_token("vtok")["email"] == "b@x.com"


def test_admin_approve_and_reject_persistence(db_backend):
    from cipherchat.admin.services import approve_user, reject_user, update_user_data
    from cipherchat.services.storage import store

    # Seed pending user
    store.set_user(
        "pending_user@example.com",
        {
            "username": "pending_user",
            "status": "pending",
            "verified": False,
            "role": "user",
            "permissions": [],
            "profile": {},
            "login_count": 0,
        },
    )

    # Approve
    ok = approve_user("pending_user@example.com")
    assert ok is True

    # Directly check backend database row to prove persistence
    user = db_backend.get_user("pending_user@example.com")
    assert user is not None
    assert user["status"] == "approved"
    assert user["verified"] is True

    # Reject
    ok = reject_user("pending_user@example.com")
    assert ok is True
    user = db_backend.get_user("pending_user@example.com")
    assert user["status"] == "rejected"

    # Update role
    ok = update_user_data("pending_user@example.com", {"role": "moderator"})
    assert ok is True
    user = db_backend.get_user("pending_user@example.com")
    assert user["role"] == "moderator"
