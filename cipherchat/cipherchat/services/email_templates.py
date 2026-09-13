"""
Email HTML builders.

Templates live in templates/emails/*.html and are rendered via Flask/Jinja.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from flask import current_app, has_app_context, render_template
from jinja2 import Environment, FileSystemLoader, select_autoescape
import os


def _templates_dir() -> str:
    # Project root / templates
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(here, "templates")


def _render(template_name: str, **context: Any) -> str:
    """
    Render an email template.

    Uses Flask's render_template when an app context is active;
    otherwise falls back to a standalone Jinja environment (tests / CLI).
    """
    # Prefer path relative to templates/ for Flask
    flask_name = f"emails/{template_name}"
    if has_app_context():
        return render_template(flask_name, **context)

    env = Environment(
        loader=FileSystemLoader(_templates_dir()),
        autoescape=select_autoescape(["html", "xml"]),
    )
    return env.get_template(flask_name).render(**context)


def create_otp_email(
    otp: str,
    username: str = "there",
    app_name: str = "CipherChat",
    expiry_minutes: int = 10,
) -> str:
    return _render(
        "otp.html",
        otp=otp,
        username=username or "there",
        app_name=app_name or "CipherChat",
        expiry_minutes=expiry_minutes,
        year=datetime.now().year,
    )


def create_invite_email(
    invite_url: str,
    room_name: str,
    created_by: str,
    expires_in: str = "24 hours",
) -> str:
    return _render(
        "invite.html",
        invite_url=invite_url,
        room_name=room_name,
        created_by=created_by,
        expires_in=expires_in,
    )


def create_admin_notification_email(
    user_email: str, login_time: str, user_info: Optional[Dict] = None
) -> str:
    user_info = user_info or {}
    return _render(
        "admin_login.html",
        user_email=user_email,
        login_time=login_time,
        user_info=user_info,
    )


def create_user_notification_email(
    user_email: str, login_time: str, user_info: Optional[Dict] = None
) -> str:
    user_info = user_info or {}
    return _render(
        "user_login.html",
        user_email=user_email,
        login_time=login_time,
        user_info=user_info,
    )


def create_verification_email(verify_url: str, username: str, email: str) -> str:
    return _render(
        "verification.html",
        verify_url=verify_url,
        username=username,
        email=email,
        registered_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


def create_welcome_email(email: str, username: str) -> str:
    return _render("welcome.html", email=email, username=username)


def create_password_reset_email(reset_url: str, email: str) -> str:
    return _render("password_reset.html", reset_url=reset_url, email=email)


def create_password_reset_success_email() -> str:
    return _render("password_reset_success.html")
