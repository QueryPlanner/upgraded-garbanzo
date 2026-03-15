"""Scheduler for sending reminders via Telegram.

This module uses APScheduler to periodically check for due reminders
and send them to users via Telegram push messages.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore

from .reminder_storage import Reminder, get_storage

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)

# Check for due reminders every 30 seconds
CHECK_INTERVAL_SECONDS = 30


class ReminderScheduler:
    """Scheduler that sends due reminders via Telegram.

    This class manages an APScheduler instance that periodically checks
    for reminders that are due and sends them to users.

    Attributes:
        bot: The Telegram Bot instance for sending messages.
        scheduler: The APScheduler instance.
        storage: The ReminderStorage instance.
    """

    def __init__(self, bot: "Bot | None" = None) -> None:
        """Initialize the reminder scheduler.

        Args:
            bot: Optional Telegram Bot instance. Can be set later via set_bot().
        """
        self._bot: Bot | None = bot
        self.scheduler = AsyncIOScheduler()
        self.storage = get_storage()
        self._running = False

    def set_bot(self, bot: "Bot") -> None:
        """Set the Telegram Bot instance.

        Args:
            bot: The Telegram Bot instance for sending messages.
        """
        self._bot = bot
        logger.info("Telegram bot instance set in scheduler")

    @property
    def bot(self) -> "Bot":
        """Get the bot instance.

        Returns:
            The Telegram Bot instance.

        Raises:
            RuntimeError: If bot hasn't been set.
        """
        if self._bot is None:
            raise RuntimeError("Bot not set. Call set_bot() first.")
        return self._bot

    async def start(self) -> None:
        """Start the scheduler.

        Initializes storage and starts the periodic reminder check job.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Initialize storage
        await self.storage.initialize()

        # Add the reminder check job
        self.scheduler.add_job(
            self._check_and_send_reminders,
            trigger=IntervalTrigger(seconds=CHECK_INTERVAL_SECONDS),
            id="reminder_check",
            name="Check for due reminders",
            replace_existing=True,
        )

        self.scheduler.start()
        self._running = True
        logger.info(
            f"Reminder scheduler started (checking every {CHECK_INTERVAL_SECONDS}s)"
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        logger.info("Reminder scheduler stopped")

    async def _check_and_send_reminders(self) -> None:
        """Check for due reminders and send them.

        This is the main job that runs periodically. It fetches all
        due reminders and sends them via Telegram.
        """
        try:
            reminders = await self.storage.get_due_reminders()

            if not reminders:
                return

            logger.info(f"Processing {len(reminders)} due reminder(s)")

            for reminder in reminders:
                await self._send_reminder(reminder)

        except Exception:
            logger.exception("Error checking reminders")

    async def _send_reminder(self, reminder: Reminder) -> None:
        """Send a reminder notification to the user.

        Args:
            reminder: The reminder to send.
        """
        if reminder.id is None:
            logger.error("Reminder has no ID, skipping")
            return

        try:
            # Send the reminder message
            await self.bot.send_message(
                chat_id=reminder.user_id,
                text=f"⏰ *Reminder*\n\n{reminder.message}",
                parse_mode="Markdown",
            )

            # Mark as sent
            await self.storage.mark_sent(reminder.id)
            logger.info(f"Sent reminder {reminder.id} to user {reminder.user_id}")

        except Exception:
            logger.exception(
                f"Failed to send reminder {reminder.id} to user {reminder.user_id}"
            )

    async def schedule_reminder(
        self,
        user_id: str,
        message: str,
        trigger_time: datetime,
    ) -> int:
        """Schedule a new reminder.

        Args:
            user_id: The Telegram chat ID of the user.
            message: The reminder message.
            trigger_time: When to send the reminder.

        Returns:
            The ID of the created reminder.
        """
        reminder = Reminder(
            user_id=user_id,
            message=message,
            trigger_time=trigger_time.isoformat(),
            created_at=datetime.now().isoformat(),
        )

        reminder_id = await self.storage.add_reminder(reminder)
        return reminder_id

    async def get_user_reminders(
        self, user_id: str, include_sent: bool = False
    ) -> list[Reminder]:
        """Get all reminders for a user.

        Args:
            user_id: The Telegram chat ID of the user.
            include_sent: Whether to include sent reminders.

        Returns:
            List of the user's reminders.
        """
        return await self.storage.get_user_reminders(user_id, include_sent)

    async def delete_reminder(self, reminder_id: int, user_id: str) -> bool:
        """Delete a reminder.

        Args:
            reminder_id: The ID of the reminder to delete.
            user_id: The user ID (for authorization).

        Returns:
            True if deleted, False otherwise.
        """
        return await self.storage.delete_reminder(reminder_id, user_id)


# Global scheduler instance
_scheduler: ReminderScheduler | None = None


def get_scheduler() -> ReminderScheduler:
    """Get the global scheduler instance.

    Returns:
        The global ReminderScheduler instance.
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = ReminderScheduler()
    return _scheduler
