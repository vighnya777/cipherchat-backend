"""Rate limiting helpers for OTP and login protection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable

from cipherchat.config import get_config
from cipherchat.services.storage import store


def is_rate_limited(
    key: str,
    *,
    max_attempts: int | None = None,
    window_hours: int = 1,
) -> bool:
    """Return True if the key has exceeded the allowed attempts in the window."""
    cfg = get_config()
    limit = max_attempts if max_attempts is not None else cfg.OTP_RATE_LIMIT_PER_HOUR
    now = datetime.now()
    window_start = now - timedelta(hours=window_hours)

    store.rate_limits[key] = [ts for ts in store.rate_limits[key] if ts > window_start]
    return len(store.rate_limits[key]) >= limit


def add_rate_limit(key: str) -> None:
    store.rate_limits[key].append(datetime.now())


def clear_rate_limit(key: str) -> None:
    store.rate_limits.pop(key, None)
