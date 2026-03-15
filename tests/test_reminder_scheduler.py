"""Unit tests for reminder scheduler."""

import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.reminder_scheduler import ReminderScheduler
from agent.reminder_storage import ReminderStorage


@pytest.fixture
def isolated_db_path() -> Generator[Path]:
    """Create a temporary database for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


class TestReminderScheduler:
    """Tests for ReminderScheduler class."""

    def test_scheduler_initialization(self) -> None:
        """Test scheduler initialization."""
        scheduler = ReminderScheduler()
        assert scheduler._bot is None
        assert scheduler._running is False

    def test_set_bot(self) -> None:
        """Test setting bot instance."""
        scheduler = ReminderScheduler()
        mock_bot = MagicMock()
        scheduler.set_bot(mock_bot)
        assert scheduler._bot == mock_bot

    def test_bot_property_raises_without_bot(self) -> None:
        """Test that accessing bot without setting raises error."""
        scheduler = ReminderScheduler()
        with pytest.raises(RuntimeError, match="Bot not set"):
            _ = scheduler.bot

    @pytest.mark.asyncio
    async def test_start_starts_scheduler(self) -> None:
        """Test that start initializes and starts the scheduler."""
        scheduler = ReminderScheduler()

        await scheduler.start()
        assert scheduler._running is True

        # Cleanup
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_stops_scheduler(self) -> None:
        """Test that stop stops the scheduler."""
        scheduler = ReminderScheduler()
        await scheduler.start()
        await scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        """Test that calling start twice is safe."""
        scheduler = ReminderScheduler()

        await scheduler.start()
        await scheduler.start()  # Should not raise

        assert scheduler._running is True
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_schedule_reminder(self, isolated_db_path: Path) -> None:
        """Test scheduling a reminder."""
        storage = ReminderStorage(db_path=isolated_db_path)
        scheduler = ReminderScheduler()
        scheduler.storage = storage

        trigger_time = datetime.now() + timedelta(hours=1)
        reminder_id = await scheduler.schedule_reminder(
            user_id="test_user",
            message="Test message",
            trigger_time=trigger_time,
        )

        assert reminder_id > 0

        # Cleanup
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_get_user_reminders(self, isolated_db_path: Path) -> None:
        """Test getting user reminders."""
        storage = ReminderStorage(db_path=isolated_db_path)
        scheduler = ReminderScheduler()
        scheduler.storage = storage

        # Schedule a reminder
        trigger_time = datetime.now() + timedelta(hours=1)
        await scheduler.schedule_reminder(
            user_id="test_user",
            message="Test message",
            trigger_time=trigger_time,
        )

        # Get reminders
        reminders = await scheduler.get_user_reminders("test_user")
        assert len(reminders) == 1
        assert reminders[0].message == "Test message"

        # Cleanup
        await scheduler.stop()
