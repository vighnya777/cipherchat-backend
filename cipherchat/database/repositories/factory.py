"""Select Memory or Postgres repository based on configuration."""

from __future__ import annotations

import logging

from cipherchat.config import get_config
from cipherchat.database.repositories.base import StoreBackend
from cipherchat.database.repositories.memory import MemoryRepository

logger = logging.getLogger(__name__)

_backend: StoreBackend | None = None


def get_store_backend(force_reload: bool = False) -> StoreBackend:
    global _backend
    if _backend is not None and not force_reload:
        return _backend

    cfg = get_config()
    if cfg.DATABASE_URL or cfg.USE_SQLALCHEMY:
        from cipherchat.database.repositories.postgres import PostgresRepository
        from cipherchat.database.session import init_db

        init_db()
        _backend = PostgresRepository()
        logger.info("Using PostgresRepository (SQLAlchemy persistence)")
    else:
        _backend = MemoryRepository()
        logger.info("Using MemoryRepository (in-memory MVP store)")
    return _backend


def reset_store_backend() -> None:
    """Test helper – force next get_store_backend() to rebuild."""
    global _backend
    _backend = None
