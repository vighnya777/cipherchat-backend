"""
CipherChat – application entry point.

All routes, Socket.IO handlers, and business logic live under cipherchat/.
This file only starts the server for backward-compatible deployment commands.
"""

from __future__ import annotations

import argparse
import os

import eventlet

eventlet.monkey_patch()

from cipherchat import create_app
from cipherchat.extensions import socketio

app = create_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the CipherChat development server.")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "26109")),
    )
    args = parser.parse_args()
    print("🔐 CipherChat Server Starting...")
    print("💬 Private messaging: ENABLED")
    print("📦 Modular architecture: cipherchat package")
    socketio.run(
        app,
        host="0.0.0.0",
        port=args.port,
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
