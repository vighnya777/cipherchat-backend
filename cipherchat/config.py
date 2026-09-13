"""
CipherChat configuration.
All secrets and environment-driven settings live here.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """Central configuration object used by the application factory."""

    def __init__(self):
        # Core
        self.SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_urlsafe(48)
        self.FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"
        self.BASE_URL = os.getenv("BASE_URL", "http://localhost:5000").rstrip("/")

        # Admin bootstrap
        self.ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@cipherchat.local").strip().lower()
        self.MASTER_PASSWORD = os.getenv("MASTER_PASSWORD", "")

        # Session / cookies
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").lower() == "true"
        self.PERMANENT_SESSION_LIFETIME_HOURS = 12

        # Email
        self.SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        self.SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

        # Socket.IO CORS
        self.SOCKET_CORS_ORIGINS = [
            o.strip().rstrip("/")
            for o in os.getenv("SOCKET_CORS_ORIGINS", "").split(",")
            if o.strip()
        ]

        # Uploads
        self.UPLOAD_FOLDER = str(BASE_DIR / "uploads")
        self.MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
        self.ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
        self.ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "webm", "mkv"}
        self.ALLOWED_DOCUMENT_EXTENSIONS = {
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "zip", "rar", "7z"
        }
        self.ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "ogg", "m4a"}

        # Security / rate limits
        self.OTP_MAX_ATTEMPTS = 5
        self.OTP_EXPIRY_MINUTES = 10
        self.OTP_RATE_LIMIT_PER_HOUR = 5
        self.LOGIN_RATE_LIMIT_PER_HOUR = 10
        self.DYNAMIC_PASSWORD_EXPIRY_MINUTES = 15
        self.PASSWORD_MIN_LENGTH = 8
        self.INVITE_DEFAULT_MAX_USES = 5
        self.INVITE_DEFAULT_EXPIRY_HOURS = 24
        self.MESSAGE_RETENTION_DAYS = 30

        # Testing toggle — turn the built-in "General Chat" room on/off from the backend
        self.GENERAL_CHAT_ENABLED = os.getenv("GENERAL_CHAT_ENABLED", "1").lower() in ("1", "true", "yes")

        # Password hashing preference (argon2 preferred, bcrypt fallback)
        self.PREFER_ARGON2 = True

        # Database – production requires PostgreSQL (postgresql+psycopg2://...)
        # SQLite is allowed ONLY for development/testing when DATABASE_URL is unset
        # or explicitly set to a sqlite:/// path.
        self.DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
        # When empty: use in-memory store (legacy) unless USE_SQLALCHEMY_MEMORY=1
        self.USE_SQLALCHEMY = bool(self.DATABASE_URL) or os.getenv("USE_SQLALCHEMY", "").lower() in ("1", "true", "yes")

        # OAuth – never hard-code secrets; leave empty to disable provider buttons
        self.GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
        self.GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()
        self.GOOGLE_REDIRECT_URI = (os.getenv("GOOGLE_REDIRECT_URI") or "").strip()
        self.GITHUB_CLIENT_ID = (os.getenv("GITHUB_CLIENT_ID") or "").strip()
        self.GITHUB_CLIENT_SECRET = (os.getenv("GITHUB_CLIENT_SECRET") or "").strip()
        self.GITHUB_REDIRECT_URI = (os.getenv("GITHUB_REDIRECT_URI") or "").strip()


def get_config() -> Config:
    return Config()
