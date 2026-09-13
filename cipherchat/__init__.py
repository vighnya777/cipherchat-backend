"""
CipherChat – Secure. Private. Intelligent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

__version__ = "1.1.0"


def create_app(config_object=None):
    """Application factory – owns initialization and blueprint registration."""
    from flask import Flask, request

    from cipherchat.config import get_config
    from cipherchat.extensions import socketio
    from cipherchat.services.security import apply_browser_security_headers
    from cipherchat.services.storage import store

    cfg = config_object or get_config()

    # Resolve template/static relative to project root
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )

    app.config["SECRET_KEY"] = cfg.SECRET_KEY
    app.config["ADMIN_EMAIL"] = cfg.ADMIN_EMAIL
    app.config["SESSION_COOKIE_HTTPONLY"] = cfg.SESSION_COOKIE_HTTPONLY
    app.config["SESSION_COOKIE_SAMESITE"] = cfg.SESSION_COOKIE_SAMESITE
    app.config["SESSION_COOKIE_SECURE"] = cfg.SESSION_COOKIE_SECURE
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        hours=cfg.PERMANENT_SESSION_LIFETIME_HOURS
    )
    app.config["UPLOAD_FOLDER"] = cfg.UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_CONTENT_LENGTH
    app.config["BASE_URL"] = cfg.BASE_URL

    os.makedirs(cfg.UPLOAD_FOLDER, exist_ok=True)

    # Initialize SQLAlchemy tables when persistence is enabled
    if cfg.DATABASE_URL or cfg.USE_SQLALCHEMY:
        from cipherchat.database.session import init_db

        init_db()

    logging.basicConfig(
        filename="securechat.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    )

    socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet", manage_session=True)

    @app.after_request
    def _security_headers(response):
        return apply_browser_security_headers(response, request.is_secure)

    @app.errorhandler(400)
    def bad_request(e):
        from flask import jsonify, request, render_template
        if request.path.startswith("/admin/api") or request.is_json:
            return jsonify({"error": "bad request"}), 400
        return render_template("error/404.html"), 400

    @app.errorhandler(401)
    def unauthorized(e):
        from flask import jsonify, request, redirect, url_for
        if request.path.startswith("/admin/api") or request.is_json or request.path.startswith("/upload"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def forbidden(e):
        from flask import jsonify, request, render_template
        if request.path.startswith("/admin/api") or request.is_json:
            return jsonify({"error": "forbidden"}), 403
        return render_template("error/404.html"), 403

    @app.errorhandler(404)
    def page_not_found(e):
        from flask import render_template
        return render_template("error/404.html"), 404

    @app.errorhandler(413)
    def too_large(e):
        from flask import jsonify
        return jsonify({"error": "file too large"}), 413

    @app.errorhandler(500)
    def server_error(e):
        import logging
        logging.getLogger(__name__).exception("Unhandled server error")
        from flask import jsonify, request, render_template
        if request.path.startswith("/admin/api") or request.is_json:
            return jsonify({"error": "internal error"}), 500
        return render_template("error/404.html"), 500

    # Bootstrap admin
    _ensure_admin(cfg, store)

    # Blueprints
    from cipherchat.auth.routes import auth_bp
    from cipherchat.chat.routes import chat_bp
    from cipherchat.chat.groups import group_bp
    from cipherchat.admin.routes import admin_bp
    from cipherchat.media.routes import media_bp
    from cipherchat.api.auth_routes import api_auth_bp
    from cipherchat.api.chat_routes import api_chat_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(group_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(api_auth_bp)
    app.register_blueprint(api_chat_bp)

    # Socket.IO handlers
    import cipherchat.chat.events  # noqa: F401

    return app


def _ensure_admin(cfg, store) -> None:
    admin_email = (getattr(cfg, "ADMIN_EMAIL", None) or "admin@cipherchat.local").strip().lower()
    existing_by_email = store.users.get(admin_email)
    existing_email_for_admin = store.resolve_email("admin")
    existing_by_username = store.users.get(existing_email_for_admin) if existing_email_for_admin else None

    if existing_by_email:
        data = dict(existing_by_email)
        data.update(
            {
                "username": "admin",
                "status": "approved",
                "verified": True,
                "role": "admin",
                "permissions": ["all"],
            }
        )
        store.set_user(admin_email, data)
        store.username_index["admin"] = admin_email
        return

    if existing_by_username and existing_email_for_admin:
        data = dict(existing_by_username)
        data.update(
            {
                "status": "approved",
                "verified": True,
                "role": "admin",
                "permissions": ["all"],
            }
        )
        store.set_user(existing_email_for_admin, data)
        store.username_index["admin"] = existing_email_for_admin
        return

    store.set_user(
        admin_email,
        {
            "username": "admin",
            "status": "approved",
            "verified": True,
            "role": "admin",
            "created_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "profile": {"avatar": None, "bio": "System Administrator"},
            "password_hash": None,
            "login_count": 0,
            "last_login": datetime.now().isoformat(),
            "permissions": ["all"],
        },
    )
    store.username_index["admin"] = admin_email
    print("✅ Admin user initialized")

