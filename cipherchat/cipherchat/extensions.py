"""Shared Flask extensions – initialized by the application factory."""

from __future__ import annotations

from flask_socketio import SocketIO

# cors_allowed_origins="*" is OK for local/dev; init_app will re-bind to the app.
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="eventlet",
    logger=False,
    engineio_logger=False,
)
