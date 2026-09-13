"""SQLAlchemy engine and session factory."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

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


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    global _engine
    url = resolve_database_url()
    if not url:
        raise RuntimeError("No DATABASE_URL configured and USE_SQLALCHEMY is not enabled")

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
    logger.info("Database tables ensured via metadata.create_all")
