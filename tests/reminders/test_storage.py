"""Unit tests for reminder storage."""

import tempfile
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path

import pytest

from agent.reminders.storage import Reminder, ReminderStorage


@pytest.fixture
async def storage() -> AsyncGenerator[ReminderStorage]:
    """Create a temporary storage for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    storage = ReminderStorage(db_path=db_path)
    await storage.initialize()
    yield storage

    await storage.close()
    db_path.unlink(missing_ok=True)


class TestReminderModel:
    """Tests for Reminder Pydantic model."""

    def test_reminder_creation(self) -> None:
        """Test creating a reminder."""
        reminder = Reminder(
            user_id="test_user",
            message="Test message",
            trigger_time="2026-03-15T14:30:00",
            created_at="2026-03-15T10:00:00",
        )
        assert reminder.user_id == "test_user"
        assert reminder.message == "Test message"
        assert reminder.is_sent is False

    def test_reminder_with_id(self) -> None:
        """Test reminder with ID."""
        reminder = Reminder(
            id=1,
            user_id="test_user",
            message="Test message",
            trigger_time="2026-03-15T14:30:00",
            created_at="2026-03-15T10:00:00",
        )
        assert reminder.id == 1


class TestReminderStorage:
    """Tests for ReminderStorage class."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, storage: ReminderStorage) -> None:
        """Test that initialize creates the database tables."""
        assert storage._conn is not None
        assert storage.db_path.exists()

    @pytest.mark.asyncio
    async def test_add_reminder(self, storage: ReminderStorage) -> None:
        """Test adding a reminder."""
        reminder = Reminder(
            user_id="user1",
            message="Test reminder",
            trigger_time="2026-03-15T14:30:00",
            created_at=datetime.now().isoformat(),
        )

        reminder_id = await storage.add_reminder(reminder)
        assert reminder_id > 0

    @pytest.mark.asyncio
    async def test_get_due_reminders(self, storage: ReminderStorage) -> None:
        """Test getting due reminders."""
        # Add a reminder in the past
        past_reminder = Reminder(
            user_id="user1",
            message="Past reminder",
            trigger_time="2020-01-01T10:00:00",
            created_at=datetime.now().isoformat(),
        )
        await storage.add_reminder(past_reminder)

        # Add a reminder in the future
        future_reminder = Reminder(
            user_id="user1",
            message="Future reminder",
            trigger_time="2030-01-01T10:00:00",
            created_at=datetime.now().isoformat(),
        )
        await storage.add_reminder(future_reminder)

        # Get due reminders
        due = await storage.get_due_reminders()
        assert len(due) == 1
        assert due[0].message == "Past reminder"

    @pytest.mark.asyncio
    async def test_mark_sent(self, storage: ReminderStorage) -> None:
        """Test marking a reminder as sent."""
        reminder = Reminder(
            user_id="user1",
            message="Test reminder",
            trigger_time="2020-01-01T10:00:00",
            created_at=datetime.now().isoformat(),
        )
        reminder_id = await storage.add_reminder(reminder)

        await storage.mark_sent(reminder_id)

        # Verify it's no longer in due reminders
        due = await storage.get_due_reminders()
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_get_user_reminders(self, storage: ReminderStorage) -> None:
        """Test getting reminders for a specific user."""
        # Add reminders for two users
        reminder1 = Reminder(
            user_id="user1",
            message="User 1 reminder",
            trigger_time="2026-03-15T14:30:00",
            created_at=datetime.now().isoformat(),
        )
        reminder2 = Reminder(
            user_id="user2",
            message="User 2 reminder",
            trigger_time="2026-03-15T15:30:00",
            created_at=datetime.now().isoformat(),
        )
        await storage.add_reminder(reminder1)
        await storage.add_reminder(reminder2)

        # Get user1's reminders
        user1_reminders = await storage.get_user_reminders("user1")
        assert len(user1_reminders) == 1
        assert user1_reminders[0].message == "User 1 reminder"

    @pytest.mark.asyncio
    async def test_delete_reminder(self, storage: ReminderStorage) -> None:
        """Test deleting a reminder."""
        reminder = Reminder(
            user_id="user1",
            message="Test reminder",
            trigger_time="2026-03-15T14:30:00",
            created_at=datetime.now().isoformat(),
        )
        reminder_id = await storage.add_reminder(reminder)

        # Delete the reminder
        deleted = await storage.delete_reminder(reminder_id, "user1")
        assert deleted is True

        # Verify it's gone
        reminders = await storage.get_user_reminders("user1")
        assert len(reminders) == 0

    @pytest.mark.asyncio
    async def test_delete_reminder_wrong_user(self, storage: ReminderStorage) -> None:
        """Test that user can't delete another user's reminder."""
        reminder = Reminder(
            user_id="user1",
            message="Test reminder",
            trigger_time="2026-03-15T14:30:00",
            created_at=datetime.now().isoformat(),
        )
        reminder_id = await storage.add_reminder(reminder)

        # Try to delete as wrong user
        deleted = await storage.delete_reminder(reminder_id, "user2")
        assert deleted is False

        # Verify it still exists
        reminders = await storage.get_user_reminders("user1")
        assert len(reminders) == 1
