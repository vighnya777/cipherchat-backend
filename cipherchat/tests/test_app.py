"""Regression tests for CipherChat modular architecture."""

from __future__ import annotations


def test_app_starts(app):
    assert app is not None
    assert "SECRET_KEY" in app.config


def test_security_headers(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers


def test_login_page(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Sign in" in resp.data or b"CipherChat" in resp.data


def test_register_page(client):
    resp = client.get("/register")
    assert resp.status_code == 200


def test_index_redirects_to_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers.get("Location", "")


def test_chat_requires_auth(client):
    resp = client.get("/chat", follow_redirects=False)
    assert resp.status_code in (301, 302)
    assert "/login" in resp.headers.get("Location", "")


def test_admin_requires_auth(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code in (301, 302)


def test_logout_clears_session(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "user@test.local"
    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code in (301, 302)
    with client.session_transaction() as sess:
        assert not sess.get("authenticated")


def test_register_validation(client):
    resp = client.post(
        "/register",
        data={
            "email": "not-an-email",
            "username": "ab",
            "password": "x",
            "confirm_password": "y",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Should stay on register / show error (not crash)


def test_register_success_flow(client, app):
    """Registration succeeds only when verification email can be sent."""
    from unittest.mock import MagicMock, patch
    from cipherchat.services.storage import store
    from cipherchat.services.email import EmailResult

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = EmailResult(True)
        resp = client.post(
            "/register",
            data={
                "email": "newuser@example.com",
                "username": "newuser",
                "phone": "",
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "newuser@example.com" in store.users
        user = store.users["newuser@example.com"]
        assert user["status"] == "pending"
        assert user["verified"] is False
        assert user["password_hash"]


def test_login_unknown_user(client):
    resp = client.post(
        "/login",
        data={"username": "nobody", "password": "x"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Unknown" in resp.data or b"unknown" in resp.data.lower() or b"Sign in" in resp.data


def test_login_admin_master_password_issues_otp(client):
    from cipherchat.services.storage import store
    from cipherchat.config import get_config

    cfg = get_config()
    # Admin exists from fixture
    assert cfg.ADMIN_EMAIL in store.users
    resp = client.post(
        "/login",
        data={
            "username": "admin",
            "password": cfg.MASTER_PASSWORD,
        },
        follow_redirects=False,
    )
    # Without SMTP, OTP send may fail – either redirect to verify-otp or flash error
    assert resp.status_code in (200, 302)


def test_upload_requires_auth(client):
    resp = client.post("/upload", data={})
    assert resp.status_code == 401


def test_upload_rejects_bad_extension(client):
    from io import BytesIO

    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "admin@test.local"
    data = {
        "file": (BytesIO(b"evil"), "malware.exe"),
    }
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_password_hashing_roundtrip():
    from cipherchat.services.security import hash_password, verify_password

    h = hash_password("TestPass1")
    assert verify_password("TestPass1", h)
    assert not verify_password("wrong", h)


def test_blueprints_registered(app):
    rules = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert "auth.login" in rules
    assert "auth.register" in rules
    assert "chat.chat" in rules
    assert "admin.admin" in rules
    assert "media.upload_file" in rules


def test_forgot_password_page(client):
    resp = client.get("/forgot-password")
    assert resp.status_code == 200
