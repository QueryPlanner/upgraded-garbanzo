"""Telegram notification service for tool callbacks.

This module provides a singleton service for sending Telegram notifications
when agent tools are invoked. It integrates with the ADK callback system
to provide observability into agent actions.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram import Bot

logger = logging.getLogger(__name__)


class ToolNotificationService:
    """Service for sending tool usage notifications via Telegram.

    This service allows the ADK agent to notify users in real-time
    when tools are being executed, improving observability of agent actions.

    Attributes:
        bot: The Telegram Bot instance for sending messages.
        enabled: Whether notifications are enabled.
    """

    def __init__(self, bot: "Bot | None" = None, enabled: bool = True) -> None:
        """Initialize the notification service.

        Args:
            bot: Optional Telegram Bot instance. Can be set later via set_bot().
            enabled: Whether to send notifications. Defaults to True.
        """
        self._bot: Bot | None = bot
        self._enabled = enabled

    def set_bot(self, bot: "Bot") -> None:
        """Set the Telegram Bot instance.

        Args:
            bot: The Telegram Bot instance for sending messages.
        """
        self._bot = bot
        logger.info("Telegram bot instance set in notification service")

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

    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable notifications.

        Args:
            enabled: Whether to enable notifications.
        """
        self._enabled = enabled
        logger.info(f"Tool notifications {'enabled' if enabled else 'disabled'}")

    async def notify_tool_call(
        self,
        chat_id: str | int,
        tool_name: str,
        args: dict | None = None,
    ) -> None:
        """Send a notification about a tool call.

        Args:
            chat_id: The Telegram chat ID to send the notification to.
            tool_name: The name of the tool being called.
            args: Optional dictionary of tool arguments.
        """
        if not self._enabled:
            return

        if self._bot is None:
            logger.warning("Bot not set, skipping tool notification")
            return

        try:
            # Format the notification message
            message = f"🔧 *Tool Called:* `{tool_name}`"

            if args:
                # Truncate args if too long
                args_str = str(args)
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                message += f"\n📋 *Args:* `{args_str}`"

            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )
            logger.debug(f"Sent tool notification for {tool_name} to {chat_id}")

        except Exception:
            logger.exception(f"Failed to send tool notification to {chat_id}")


# Global notification service instance
_notification_service: ToolNotificationService | None = None


def get_notification_service() -> ToolNotificationService:
    """Get the global notification service instance.

    Returns:
        The global ToolNotificationService instance.
    """
    global _notification_service
    if _notification_service is None:
        _notification_service = ToolNotificationService()
    return _notification_service
