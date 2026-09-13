import os
import sys

import pytest

# Ensure project root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-cipherchat")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("MASTER_PASSWORD", "TestMaster1!")
os.environ.setdefault("SMTP_EMAIL", "")
os.environ.setdefault("SMTP_PASSWORD", "")
os.environ.setdefault("FLASK_DEBUG", "0")


@pytest.fixture()
def app():
    from cipherchat import create_app
    from cipherchat.services.storage import store

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False

    # Reset in-memory store between tests
    store.users.clear()
    store.username_index.clear()
    store.otp_storage.clear()
    store.dynamic_passwords.clear()
    store.rate_limits.clear()
    store.verification_tokens.clear()
    store.reset_tokens.clear()
    store.chat_rooms.clear()
    store.private_rooms.clear()
    store.active_users.clear()
    store.invite_links.clear()
    store.activity_logs.clear()

    # Re-bootstrap admin
    from cipherchat import _ensure_admin
    from cipherchat.config import get_config

    _ensure_admin(get_config(), store)

    yield application


@pytest.fixture()
def client(app):
    return app.test_client()
