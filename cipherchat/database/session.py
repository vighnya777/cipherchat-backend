"""SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from cipherchat.config import get_config

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _normalize_url(url: str) -> str:
    """Accept postgres:// and normalize to postgresql+psycopg2://."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def resolve_database_url() -> str:
    """
    Resolve the active database URL.

    - If DATABASE_URL is set → use it (PostgreSQL in production).
    - Else if USE_SQLALCHEMY → sqlite:///cipherchat_dev.db (DEV/TEST ONLY).
    - Else → empty string (legacy in-memory dict store).
    """
    cfg = get_config()
    if cfg.DATABASE_URL:
        return _normalize_url(cfg.DATABASE_URL)
    if cfg.USE_SQLALCHEMY:
        # Explicit opt-in SQLite for local development / automated tests only.
        return "sqlite:///cipherchat_dev.db"
    return ""


def _ensure_sqlite_parent_dir(url: str) -> None:
    if not url.startswith("sqlite") or ":memory:" in url:
        return
    try:
        db_path = url.replace("sqlite://", "", 1)
        if db_path.startswith("//"):
            db_path = db_path[1:]
        if db_path.startswith("/") and os.name == "nt" and len(db_path) >= 3 and db_path[1] == ":":
            db_path = db_path
        elif db_path.startswith("/") and not db_path.startswith("//"):
            db_path = db_path
        elif db_path.startswith("/"):
            db_path = db_path
        if db_path.startswith("/") or db_path.startswith("\\") or (len(db_path) >= 2 and db_path[1] == ":"):
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
    except Exception:
        pass


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    global _engine
    url = resolve_database_url()
    if not url:
        raise RuntimeError("No DATABASE_URL configured and USE_SQLALCHEMY is not enabled")

    if url.startswith("sqlite"):
        _ensure_sqlite_parent_dir(url)

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args=connect_args,
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = engine
    logger.info("Database engine created for %s", url.split("@")[-1] if "@" in url else url)
    return engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionLocal


def get_session() -> Session:
    return get_session_factory()()


def init_db() -> None:
    """Create all tables (used for tests / first boot). Prefer Alembic in production."""
    from cipherchat.database.models import Base

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        is_sqlite = engine.dialect.name == "sqlite"
        is_pg = engine.dialect.name == "postgresql"

        if "users" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("users")}
            with engine.begin() as conn:
                if "phone" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(32)"))
                if "login_count" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0"))
                if "last_login" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_login TIMESTAMP"))
                if "last_seen" not in cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP"))

        if "messages" in existing_tables:
            cols = {c["name"] for c in inspector.get_columns("messages")}
            with engine.begin() as conn:
                if "soft_deleted" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN soft_deleted BOOLEAN DEFAULT 0" if is_sqlite else "ALTER TABLE messages ADD COLUMN soft_deleted BOOLEAN DEFAULT FALSE"))
                if "pinned" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN pinned BOOLEAN DEFAULT 0" if is_sqlite else "ALTER TABLE messages ADD COLUMN pinned BOOLEAN DEFAULT FALSE"))
                if "edited_at" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN edited_at TIMESTAMP"))
                if "reply_to" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN reply_to JSONB" if is_pg else "ALTER TABLE messages ADD COLUMN reply_to JSON"))
                if "forwarded_from" not in cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN forwarded_from VARCHAR(320)"))
    except Exception as exc:
        logger.warning("Database schema check / auto-migration warning: %s", exc)

    logger.info("Database tables ensured via metadata.create_all")
