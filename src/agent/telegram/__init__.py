"""Telegram bot integration for the ADK agent.

This module provides a Telegram bot that bridges messages between Telegram
and the ADK agent, allowing users to interact with the agent via Telegram.

Note: The bot module is not imported here to avoid circular imports with agent.py.
Import from agent.telegram.bot directly when needed.
"""

from .litellm_plugin import TelegramLitellmRequestModelPlugin
from .markdown_converter import convert_markdown_to_telegram
from .prefs import (
    TELEGRAM_SESSION_LITELLM_MODEL_KEY,
    TELEGRAM_SESSION_PROVIDER_KEY,
    TELEGRAM_USAGE_COMPLETION_KEY,
    TELEGRAM_USAGE_PROMPT_KEY,
    TELEGRAM_USAGE_TOTAL_KEY,
)

__all__ = [
    "TELEGRAM_SESSION_LITELLM_MODEL_KEY",
    "TELEGRAM_SESSION_PROVIDER_KEY",
    "TELEGRAM_USAGE_COMPLETION_KEY",
    "TELEGRAM_USAGE_PROMPT_KEY",
    "TELEGRAM_USAGE_TOTAL_KEY",
    "TelegramLitellmRequestModelPlugin",
    "convert_markdown_to_telegram",
]
