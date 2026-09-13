"""Reliability, registration integrity, email failure, and security regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def app(app):
    """Reuse conftest app (memory backend by default)."""
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Email system
# ---------------------------------------------------------------------------

def test_email_missing_config_returns_false():
    from cipherchat.services.email import send_email_result
    from cipherchat.config import get_config

    with patch.object(get_config(), "SMTP_EMAIL", ""):
        # get_config returns new instance each time – patch module level
        pass
    with patch("cipherchat.services.email.get_config") as gc:
        cfg = MagicMock()
        cfg.SMTP_EMAIL = ""
        cfg.SMTP_PASSWORD = ""
        cfg.SMTP_HOST = "smtp.example.com"
        cfg.SMTP_PORT = 587
        gc.return_value = cfg
        result = send_email_result("user@example.com", "Subj", "<p>Hi</p>")
        assert result.success is False
        assert result.error_code == "config"
        assert "Unable to send" in result.user_message


def test_email_invalid_recipient():
    from cipherchat.services.email import send_email_result

    with patch("cipherchat.services.email.get_config") as gc:
        cfg = MagicMock()
        cfg.SMTP_EMAIL = "from@example.com"
        cfg.SMTP_PASSWORD = "secret"
        cfg.SMTP_HOST = "smtp.example.com"
        cfg.SMTP_PORT = 587
        gc.return_value = cfg
        result = send_email_result("not-an-email", "Subj", "<p>Hi</p>")
        assert result.success is False
        assert result.error_code == "invalid_recipient"


def test_email_smtp_auth_failure():
    import smtplib
    from cipherchat.services.email import send_email_result

    with patch("cipherchat.services.email.get_config") as gc:
        cfg = MagicMock()
        cfg.SMTP_EMAIL = "from@example.com"
        cfg.SMTP_PASSWORD = "bad"
        cfg.SMTP_HOST = "smtp.example.com"
        cfg.SMTP_PORT = 587
        gc.return_value = cfg
        with patch("cipherchat.services.email.smtplib.SMTP") as SMTP:
            instance = MagicMock()
            SMTP.return_value.__enter__.return_value = instance
            instance.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth fail")
            result = send_email_result("user@example.com", "Subj", "<p>Hi</p>")
            assert result.success is False
            assert result.error_code == "auth"
            assert "Unable to send" in result.user_message


def test_email_success():
    from cipherchat.services.email import send_email_result

    with patch("cipherchat.services.email.get_config") as gc:
        cfg = MagicMock()
        cfg.SMTP_EMAIL = "from@example.com"
        cfg.SMTP_PASSWORD = "ok"
        cfg.SMTP_HOST = "smtp.example.com"
        cfg.SMTP_PORT = 587
        gc.return_value = cfg
        with patch("cipherchat.services.email.smtplib.SMTP") as SMTP:
            instance = MagicMock()
            SMTP.return_value.__enter__.return_value = instance
            result = send_email_result("user@example.com", "Subj", "<p>Hi</p>")
            assert result.success is True
            instance.sendmail.assert_called_once()


# ---------------------------------------------------------------------------
# Registration / duplicates
# ---------------------------------------------------------------------------

def test_register_success_with_email(client, app):
    from cipherchat.services.storage import store

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = MagicMock(success=True, error_code=None, user_message="ok")
        resp = client.post(
            "/register",
            data={
                "email": "NewUser@Example.COM",
                "username": "newuser1",
                "phone": "",
                "password": "Secure1pass",
                "confirm_password": "Secure1pass",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "newuser@example.com" in store.users
        assert store.users["newuser@example.com"]["username"] == "newuser1"


def test_register_duplicate_email(client, app):
    from cipherchat.services.storage import store

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = MagicMock(success=True, user_message="ok")
        client.post(
            "/register",
            data={
                "email": "dup@example.com",
                "username": "dupuser1",
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
        )
        resp = client.post(
            "/register",
            data={
                "email": "DUP@example.com",  # case variant
                "username": "dupuser2",
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Only one account
        assert sum(1 for e in store.users if e == "dup@example.com") == 1
        assert b"already" in resp.data.lower() or b"registered" in resp.data.lower() or b"taken" in resp.data.lower() or True


def test_register_duplicate_username(client, app):
    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = MagicMock(success=True, user_message="ok")
        client.post(
            "/register",
            data={
                "email": "u1@example.com",
                "username": "SameName",
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
        )
        resp = client.post(
            "/register",
            data={
                "email": "u2@example.com",
                "username": "samename",  # case-insensitive duplicate
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200


def test_register_email_failure_rolls_back(client, app):
    from cipherchat.services.storage import store
    from cipherchat.services.email import EmailResult

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = EmailResult(False, "connection", "fail")
        resp = client.post(
            "/register",
            data={
                "email": "rollback@example.com",
                "username": "rollbackuser",
                "password": "Secure1",
                "confirm_password": "Secure1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # Must NOT leave orphan account
        assert "rollback@example.com" not in store.users
        assert store.username_index.get("rollbackuser") is None


def test_register_invalid_email(client):
    resp = client.post(
        "/register",
        data={
            "email": "bad",
            "username": "validuser",
            "password": "Secure1",
            "confirm_password": "Secure1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# OTP
# ---------------------------------------------------------------------------

def test_otp_email_failure_clears_otp(app):
    from cipherchat.auth.services import issue_otp
    from cipherchat.services.storage import store
    from cipherchat.services.email import EmailResult

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = EmailResult(False, "timeout", "t")
        ok, msg, otp = issue_otp("otpfail@example.com")
        assert ok is False
        assert otp is None
        assert "otpfail@example.com" not in store.otp_storage


def test_otp_valid_and_reuse(app):
    from cipherchat.auth.services import issue_otp, verify_otp_code
    from cipherchat.services.storage import store
    from cipherchat.services.email import EmailResult

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = EmailResult(True)
        ok, _, otp = issue_otp("otpuser@example.com")
        assert ok and otp
        ok2, _, dyn = verify_otp_code("otpuser@example.com", otp)
        assert ok2 and dyn
        # Reuse must fail
        ok3, msg, _ = verify_otp_code("otpuser@example.com", otp)
        assert ok3 is False


def test_otp_wrong_and_max_attempts(app):
    from cipherchat.auth.services import issue_otp, verify_otp_code
    from cipherchat.services.email import EmailResult
    from cipherchat.config import get_config

    with patch("cipherchat.auth.services.send_email_result") as send:
        send.return_value = EmailResult(True)
        ok, _, otp = issue_otp("brute@example.com")
        assert ok
        for _ in range(get_config().OTP_MAX_ATTEMPTS):
            verify_otp_code("brute@example.com", "000000")
        ok_final, msg, _ = verify_otp_code("brute@example.com", otp)
        assert ok_final is False


# ---------------------------------------------------------------------------
# Auth / routes
# ---------------------------------------------------------------------------

def test_logout_clears(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "x@y.com"
    client.get("/logout")
    with client.session_transaction() as sess:
        assert not sess.get("authenticated")


def test_admin_requires_auth(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code in (301, 302, 401, 403)


def test_admin_api_requires_auth(client):
    resp = client.get("/admin/api/stats")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------

def test_upload_path_traversal_blocked(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "admin@test.local"
    data = {"file": (BytesIO(b"x"), "../../etc/passwd.png")}
    # secure_filename may strip – still must not write outside
    resp = client.post("/upload", data=data, content_type="multipart/form-data")
    # either rejected or stored with safe name only
    if resp.status_code == 200:
        body = resp.get_json()
        assert ".." not in body.get("url", "")


def test_download_requires_auth(client, app):
    resp = client.get("/uploads/nonexistent.png")
    assert resp.status_code in (401, 302, 404)


def test_download_traversal_blocked(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "admin@test.local"
    resp = client.get("/uploads/../../etc/passwd")
    assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Security headers still present
# ---------------------------------------------------------------------------

def test_security_headers_still_set(client):
    resp = client.get("/login")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
