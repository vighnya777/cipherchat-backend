# Deployment Guide

The existing Procfile runs `python3 app.py`, but the current in-memory session, chat, and token stores make it unsuitable for horizontal scaling or serverless deployment.

Before production deployment:

1. Configure HTTPS and set `SESSION_COOKIE_SECURE=true`.
2. Set all required environment variables through the deployment platform's secret store.
3. Move application state to PostgreSQL and Redis.
4. Configure Socket.IO sticky sessions or a shared message queue.
5. Store uploads in private object storage and authorize downloads.
6. Set `FLASK_DEBUG=0` and provide explicit `SOCKET_CORS_ORIGINS`.
