"""Unit tests for reminder scheduler."""

import tempfile
from collections.abc import AsyncGenerator, Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.reminders.scheduler import ReminderScheduler
from agent.reminders.storage import Reminder, ReminderStorage


@pytest.fixture
def isolated_db_path() -> Generator[Path]:
    """Create a temporary database file for each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
async def isolated_storage(isolated_db_path: Path) -> AsyncGenerator[ReminderStorage]:
    """ReminderStorage backed by a temp file; closes connection on teardown."""
    storage = ReminderStorage(db_path=isolated_db_path)
    yield storage
    await storage.close()


class TestReminderScheduler:
    """Tests for ReminderScheduler class."""

    def test_scheduler_initialization(self) -> None:
        """Test scheduler initialization."""
        scheduler = ReminderScheduler()
        assert scheduler._bot is None
        assert scheduler._handler is None
        assert scheduler._running is False

    def test_set_bot(self) -> None:
        """Test setting bot instance."""
        scheduler = ReminderScheduler()
        mock_bot = MagicMock()
        scheduler.set_bot(mock_bot)
        assert scheduler._bot == mock_bot

    def test_set_handler(self) -> None:
        """Test setting TelegramHandler instance."""
        scheduler = ReminderScheduler()
        mock_handler = MagicMock()
        scheduler.set_handler(mock_handler)
        assert scheduler._handler == mock_handler

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
    async def test_schedule_reminder(self, isolated_storage: ReminderStorage) -> None:
        """Test scheduling a reminder."""
        scheduler = ReminderScheduler()
        scheduler.storage = isolated_storage

        trigger_time = datetime.now(UTC) + timedelta(hours=1)
        reminder_id = await scheduler.schedule_reminder(
            user_id="test_user",
            message="Test message",
            trigger_time=trigger_time,
        )

        assert reminder_id > 0
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_get_user_reminders(self, isolated_storage: ReminderStorage) -> None:
        """Test getting user reminders."""
        scheduler = ReminderScheduler()
        scheduler.storage = isolated_storage

        trigger_time = datetime.now(UTC) + timedelta(hours=1)
        await scheduler.schedule_reminder(
            user_id="test_user",
            message="Test message",
            trigger_time=trigger_time,
        )

        reminders = await scheduler.get_user_reminders("test_user")
        assert len(reminders) == 1
        assert reminders[0].message == "Test message"

        await scheduler.stop()


class TestAgentAwareReminders:
    """Tests for agent-aware reminder processing."""

    @pytest.mark.asyncio
    async def test_send_reminder_uses_handler_when_set(
        self, isolated_storage: ReminderStorage
    ) -> None:
        """Test that reminder is processed through handler when set."""
        scheduler = ReminderScheduler()
        scheduler.storage = isolated_storage

        # Set up mocks
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        scheduler.set_bot(mock_bot)

        mock_handler = MagicMock()
        mock_handler.process_reminder = AsyncMock(
            return_value="Hey! Don't forget about lunch! Want me to order something?"
        )
        scheduler.set_handler(mock_handler)

        # Create a reminder
        trigger_time = datetime.now(UTC) - timedelta(minutes=1)
        reminder = Reminder(
            id=1,
            user_id="test_user",
            message="lunch",
            trigger_time=trigger_time.isoformat(),
            is_sent=False,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Send the reminder
        await scheduler._send_reminder(reminder)

        # Verify handler was called
        mock_handler.process_reminder.assert_called_once()
        call_kwargs = mock_handler.process_reminder.call_args[1]
        assert call_kwargs["user_id"] == "test_user"
        assert call_kwargs["reminder_message"] == "lunch"

        # Verify bot sent the agent's response
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert "Hey! Don't forget about lunch!" in call_args[1]["text"]

    @pytest.mark.asyncio
    async def test_send_reminder_fallback_without_handler(
        self, isolated_storage: ReminderStorage
    ) -> None:
        """Test that reminder falls back to simple message without handler."""
        scheduler = ReminderScheduler()
        scheduler.storage = isolated_storage

        # Set up only the bot (no handler)
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        scheduler.set_bot(mock_bot)

        # Create a reminder
        trigger_time = datetime.now(UTC) - timedelta(minutes=1)
        reminder = Reminder(
            id=2,
            user_id="test_user",
            message="simple reminder",
            trigger_time=trigger_time.isoformat(),
            is_sent=False,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Send the reminder
        await scheduler._send_reminder(reminder)

        # Verify bot sent simple message (with Markdown)
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert "⏰ *Reminder*" in call_args[1]["text"]
        assert "simple reminder" in call_args[1]["text"]
        assert call_args[1]["parse_mode"] == "Markdown"

    @pytest.mark.asyncio
    async def test_send_reminder_handles_handler_exception(
        self, isolated_storage: ReminderStorage
    ) -> None:
        """Test handler exception is caught and reminder is not sent."""
        scheduler = ReminderScheduler()
        scheduler.storage = isolated_storage

        # Set up mocks
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()
        scheduler.set_bot(mock_bot)

        mock_handler = MagicMock()
        mock_handler.process_reminder = AsyncMock(side_effect=Exception("Agent error"))
        scheduler.set_handler(mock_handler)

        # Create a reminder
        trigger_time = datetime.now(UTC) - timedelta(minutes=1)
        reminder = Reminder(
            id=3,
            user_id="test_user",
            message="fallback test",
            trigger_time=trigger_time.isoformat(),
            is_sent=False,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Send the reminder - should handle exception
        await scheduler._send_reminder(reminder)

        # Handler was attempted but failed, message should not be sent
        mock_handler.process_reminder.assert_called_once()
        # Bot.send_message should not be called since exception was raised
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_reminder_skips_reminder_without_id(self) -> None:
        """Test that reminders without ID are skipped."""
        scheduler = ReminderScheduler()

        # Create a reminder without ID
        reminder = Reminder(
            user_id="test_user",
            message="no id",
            trigger_time=datetime.now(UTC).isoformat(),
            is_sent=False,
            created_at=datetime.now(UTC).isoformat(),
        )

        # Should return early without error
        await scheduler._send_reminder(reminder)
