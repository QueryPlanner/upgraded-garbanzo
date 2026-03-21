"""Scheduler for sending reminders via Telegram.

This module uses APScheduler to periodically check for due reminders
and sends them to users via Telegram. Reminders are processed through
the ADK agent for personalized, context-aware responses.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore

from ..utils.app_timezone import get_app_timezone, now_utc, utc_iso_seconds
from .recurrence import get_next_trigger_time
from .storage import Reminder, get_storage

if TYPE_CHECKING:
    from telegram import Bot

    from ..telegram.handler import TelegramHandler

logger = logging.getLogger(__name__)

# Check for due reminders every 30 seconds
CHECK_INTERVAL_SECONDS = 30


class ReminderScheduler:
    """Scheduler that sends due reminders via Telegram.

    This class manages an APScheduler instance that periodically checks
    for reminders that are due and sends them to users. When a TelegramHandler
    is configured, reminders are processed through the ADK agent for
    personalized, context-aware responses.

    Attributes:
        bot: The Telegram Bot instance for sending messages.
        handler: The TelegramHandler for agent-aware reminder processing.
        scheduler: The APScheduler instance.
        storage: The ReminderStorage instance.
    """

    def __init__(self, bot: "Bot | None" = None) -> None:
        """Initialize the reminder scheduler.

        Args:
            bot: Optional Telegram Bot instance. Can be set later via set_bot().
        """
        self._bot: Bot | None = bot
        self._handler: TelegramHandler | None = None
        self.scheduler = AsyncIOScheduler(timezone=str(get_app_timezone()))
        self.storage = get_storage()
        self._running = False

    def set_bot(self, bot: "Bot") -> None:
        """Set the Telegram Bot instance.

        Args:
            bot: The Telegram Bot instance for sending messages.
        """
        self._bot = bot
        logger.info("Telegram bot instance set in scheduler")

    def set_handler(self, handler: "TelegramHandler") -> None:
        """Set the TelegramHandler for agent-aware reminder processing.

        When a handler is set, reminders will be processed through the ADK
        agent, allowing for personalized, context-aware responses instead
        of simple hardcoded notifications.

        Args:
            handler: The TelegramHandler instance for processing reminders.
        """
        self._handler = handler
        logger.info("TelegramHandler set in scheduler for agent-aware reminders")

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

        If a TelegramHandler is configured, the reminder is processed through
        the ADK agent for a personalized, context-aware response. Otherwise,
        falls back to a simple hardcoded message.

        Args:
            reminder: The reminder to send.
        """
        if reminder.id is None:
            logger.error("Reminder has no ID, skipping")
            return

        try:
            # Parse the scheduled time from the reminder
            raw_ts = reminder.trigger_time.replace("Z", "+00:00")
            scheduled_time = datetime.fromisoformat(raw_ts)
            if scheduled_time.tzinfo is None:
                scheduled_time = scheduled_time.replace(tzinfo=UTC)

            # Check if we have a handler for agent-aware reminders
            if self._handler is not None:
                # Process through the agent for personalized response
                logger.info(
                    f"Processing reminder {reminder.id} through agent for "
                    f"user {reminder.user_id}"
                )
                response = await self._handler.process_reminder(
                    user_id=reminder.user_id,
                    reminder_message=reminder.message,
                    scheduled_time=scheduled_time,
                )

                # Send the agent's response via Telegram
                await self.bot.send_message(
                    chat_id=reminder.user_id,
                    text=response,
                    parse_mode="Markdown",
                )
            else:
                # Fallback to simple hardcoded message
                await self.bot.send_message(
                    chat_id=reminder.user_id,
                    text=f"⏰ *Reminder*\n\n{reminder.message}",
                    parse_mode="Markdown",
                )

            # Mark as sent
            await self._complete_reminder_delivery(reminder)
            logger.info(f"Sent reminder {reminder.id} to user {reminder.user_id}")

        except Exception:
            logger.exception(
                f"Failed to send reminder {reminder.id} to user {reminder.user_id}"
            )

    async def _complete_reminder_delivery(self, reminder: Reminder) -> None:
        """Finalize a delivery by marking one-shot reminders sent or rescheduling."""
        if reminder.id is None:
            raise ValueError("Reminder must have an ID before completion")

        if not reminder.is_recurring:
            await self.storage.mark_sent(reminder.id)
            return

        timezone_name = reminder.timezone_name or str(get_app_timezone())
        current_trigger_time = _parse_stored_trigger_time(reminder.trigger_time)
        next_reference_time = current_trigger_time + timedelta(seconds=1)
        next_trigger_time = get_next_trigger_time(
            reminder.recurrence_rule or "",
            timezone_name,
            reference_time=next_reference_time,
        )
        await self.storage.reschedule_reminder(
            reminder.id,
            utc_iso_seconds(next_trigger_time),
        )

    async def schedule_reminder(
        self,
        user_id: str,
        message: str,
        trigger_time: datetime,
        recurrence_rule: str | None = None,
        recurrence_text: str | None = None,
        timezone_name: str | None = None,
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
            trigger_time=utc_iso_seconds(trigger_time),
            recurrence_rule=recurrence_rule,
            recurrence_text=recurrence_text,
            timezone_name=timezone_name,
            created_at=now_utc().isoformat(timespec="seconds"),
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


def _parse_stored_trigger_time(trigger_time: str) -> datetime:
    """Parse an ISO timestamp stored in reminder persistence."""
    normalized_trigger_time = trigger_time.replace("Z", "+00:00")
    parsed_trigger_time = datetime.fromisoformat(normalized_trigger_time)
    if parsed_trigger_time.tzinfo is None:
        return parsed_trigger_time.replace(tzinfo=UTC)
    return parsed_trigger_time.astimezone(UTC)
