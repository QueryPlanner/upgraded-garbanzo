"""Telegram bot integration for the ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.
"""

from .bot import create_application, main, run_bot
from .handler import TelegramHandler, initialize_runner, process_message, reset_session
from .notifications import ToolNotificationService, get_notification_service

__all__ = [
    "TelegramHandler",
    "ToolNotificationService",
    "create_application",
    "get_notification_service",
    "initialize_runner",
    "main",
    "process_message",
    "reset_session",
    "run_bot",
]
