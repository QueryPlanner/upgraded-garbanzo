"""Tests for shared Postgres pool helper."""

from unittest.mock import AsyncMock, patch

import pytest

from agent.utils.pg_app_pool import (
    close_shared_app_pool,
    get_shared_app_pool,
    postgres_dsn_from_environment,
)


def _mock_pg_pool() -> AsyncMock:
    pool = AsyncMock()
    pool.close = AsyncMock(return_value=None)
    return pool


@pytest.mark.asyncio
async def test_postgres_dsn_from_environment_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert postgres_dsn_from_environment() is None


@pytest.mark.asyncio
async def test_postgres_dsn_from_environment_postgresql_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/mydb")
    assert postgres_dsn_from_environment() == "postgresql://user:pass@host:5432/mydb"


@pytest.mark.asyncio
async def test_get_shared_app_pool_returns_none_without_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    await close_shared_app_pool()
    assert await get_shared_app_pool() is None


@pytest.mark.asyncio
async def test_get_shared_app_pool_creates_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/appdb")
    await close_shared_app_pool()
    mock_pool = _mock_pg_pool()
    with patch(
        "agent.utils.pg_app_pool.asyncpg.create_pool", new_callable=AsyncMock
    ) as cp:
        cp.return_value = mock_pool
        first = await get_shared_app_pool()
        second = await get_shared_app_pool()
    assert first is mock_pool is second
    assert cp.await_count == 1
    await close_shared_app_pool()


@pytest.mark.asyncio
async def test_close_shared_app_pool_closes_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/appdb2")
    await close_shared_app_pool()
    mock_pool = _mock_pg_pool()
    with patch(
        "agent.utils.pg_app_pool.asyncpg.create_pool", new_callable=AsyncMock
    ) as cp:
        cp.return_value = mock_pool
        await get_shared_app_pool()
        await close_shared_app_pool()
    mock_pool.close.assert_awaited_once()
    await close_shared_app_pool()
