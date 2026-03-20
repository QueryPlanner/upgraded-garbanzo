"""Shared asyncpg pool for agent-owned tables (reminders, fitness).

Uses DATABASE_URL (via SessionConfig) when it points at Postgres so app data
persists with the same database as ADK sessions.
"""

import asyncio
import logging
import os

import asyncpg  # type: ignore[import-untyped]
from pydantic import ValidationError

from .config import SessionConfig

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


def postgres_dsn_from_environment() -> str | None:
    """Resolve a Postgres DSN from the current process environment.

    Returns:
        Normalized asyncpg DSN, or None if not configured for Postgres.
    """
    try:
        cfg = SessionConfig.model_validate(os.environ)
    except ValidationError:
        return None
    return cfg.effective_asyncpg_dsn


async def get_shared_app_pool() -> asyncpg.Pool | None:
    """Return a process-wide pool for agent tables, or None if using SQLite only.

    The pool is created lazily on first use when DATABASE_URL targets Postgres.
    """
    dsn = postgres_dsn_from_environment()
    if not dsn:
        return None

    global _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                dsn,
                min_size=1,
                max_size=10,
                command_timeout=120,
            )
            logger.info("Connected agent app tables pool to Postgres")
        return _pool


async def close_shared_app_pool() -> None:
    """Close the shared pool (primarily for tests)."""
    global _pool
    async with _pool_lock:
        if _pool is not None:
            await _pool.close()
            _pool = None
