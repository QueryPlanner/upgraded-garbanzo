"""Postgres-mode tests for ReminderStorage (mocked asyncpg pool)."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.reminders.storage import Reminder, ReminderStorage


def _make_pool() -> AsyncMock:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    acq_cm = MagicMock()
    acq_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acq_cm.__aexit__ = AsyncMock(return_value=None)
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acq_cm)
    pool.fetchval = AsyncMock(return_value=42)
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock()
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


def _pg_row() -> dict[str, object]:
    return {
        "id": 9,
        "user_id": "u1",
        "message": "hello",
        "trigger_time": "2020-01-01T00:00:00+00:00",
        "is_sent": False,
        "created_at": "2020-01-01T00:00:00+00:00",
    }


@pytest.fixture
def mock_pool() -> AsyncMock:
    pool = _make_pool()
    pool.fetchval = AsyncMock(return_value=42)
    pool.fetch = AsyncMock(return_value=[_pg_row()])
    pool.fetchrow = AsyncMock(return_value=_pg_row())
    return pool


@pytest.mark.asyncio
async def test_reminder_storage_postgres_add_and_fetch(
    mock_pool: AsyncMock,
) -> None:
    async def fake_pool() -> AsyncMock:
        return mock_pool

    with (
        patch(
            "agent.reminders.storage.postgres_dsn_from_environment",
            return_value="postgresql://localhost/db",
        ),
        patch("agent.reminders.storage.get_shared_app_pool", side_effect=fake_pool),
    ):
        storage = ReminderStorage()
        await storage.initialize()
        reminder = Reminder(
            user_id="u1",
            message="m",
            trigger_time="2030-01-01T00:00:00",
            created_at=datetime.now().isoformat(),
        )
        rid = await storage.add_reminder(reminder)
        assert rid == 42
        mock_pool.fetchval.assert_awaited()

        due = await storage.get_due_reminders()
        assert len(due) == 1
        assert due[0].id == 9

        await storage.mark_sent(9)
        mock_pool.execute.assert_awaited()

        listed = await storage.get_user_reminders("u1", include_sent=False)
        assert len(listed) == 1

        mock_pool.fetchrow = AsyncMock(return_value=None)
        deleted = await storage.delete_reminder(1, "u1")
        assert deleted is False


@pytest.mark.asyncio
async def test_reminder_storage_postgres_delete_success(
    mock_pool: AsyncMock,
) -> None:
    async def fake_pool() -> AsyncMock:
        return mock_pool

    mock_pool.fetchrow = AsyncMock(return_value={"id": 1})
    with (
        patch(
            "agent.reminders.storage.postgres_dsn_from_environment",
            return_value="postgresql://localhost/db",
        ),
        patch("agent.reminders.storage.get_shared_app_pool", side_effect=fake_pool),
    ):
        storage = ReminderStorage()
        await storage.initialize()
        assert await storage.delete_reminder(1, "u1") is True
