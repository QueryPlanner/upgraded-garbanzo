"""Telegram bot runner for the ADK agent.

This script starts a Telegram bot that connects to your ADK agent,
allowing users to interact with the agent through Telegram messages.

Setup Instructions:
1. Create a bot via @BotFather on Telegram and get your bot token
2. Set TELEGRAM_BOT_TOKEN environment variable
3. Run: uv run telegram-bot

Usage:
    - Send any message to interact with the agent
    - Use /reset to start a new conversation
    - Use /help to see available commands
"""

import contextlib
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram._message import Message
from telegram.constants import ParseMode
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables from .env file
load_dotenv()

from ..agent import root_agent  # noqa: E402
from ..reminders import get_scheduler  # noqa: E402
from ..utils.session import create_session_service_for_runner  # noqa: E402
from .handler import (  # noqa: E402
    get_handler,
    initialize_runner,
    process_message,
    reset_session,
)
from .markdown_converter import convert_markdown_to_telegram  # noqa: E402
from .notifications import get_notification_service  # noqa: E402

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_MESSAGE_LENGTH = 4096  # Telegram's message limit


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not update.message:
        return

    welcome_message = (
        "🤖 *Welcome to the ADK Agent Bot!*\n\n"
        "I'm an AI assistant powered by Google ADK. "
        "Send me any message and I'll help you!\n\n"
        "Commands:\n"
        "/start - Show this welcome message\n"
        "/help - Get help\n"
        "/reset - Clear conversation and start fresh\n"
        "/reminders - List your scheduled reminders\n\n"
        "*Reminders:* Ask me to remind you about things!\n"
        'Example: "Remind me in 30 minutes to take a break"'
    )
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    if not update.message:
        return

    help_text = (
        "🤖 *ADK Agent Bot Help*\n\n"
        "*How to use:*\n"
        "• Just send me a message and I'll respond\n"
        "• I remember our conversation context\n\n"
        "*Commands:*\n"
        "/start - Restart the bot\n"
        "/help - Show this help message\n"
        "/reset - Clear conversation and start fresh\n"
        "/reminders - List your scheduled reminders\n\n"
        "*Reminders:*\n"
        "You can ask me to set reminders like:\n"
        '• "Remind me to call mom in 30 minutes"\n'
        '• "Remind me about the meeting at 3pm today"\n'
        '• "Remind me tomorrow at 9am to check emails"'
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /reset command to reset session and start fresh."""
    if not update.message or not update.effective_user:
        return

    user_id = str(update.effective_user.id)
    success = await reset_session(user_id=user_id)
    if success:
        await update.message.reply_text(
            "✅ Session reset! A new conversation session has been created.",
        )
    else:
        await update.message.reply_text(
            "❌ Failed to reset session. Please try again.",
        )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /reminders command to list user's reminders."""
    if not update.message or not update.effective_user:
        return

    user_id = str(update.effective_user.id)
    scheduler = get_scheduler()

    try:
        reminders = await scheduler.get_user_reminders(user_id, include_sent=False)

        if not reminders:
            await update.message.reply_text(
                "📭 You have no scheduled reminders.\n\n"
                'Try saying: "Remind me in 30 minutes to take a break"'
            )
            return

        # Format reminders list
        lines = ["⏰ *Your Scheduled Reminders:*\n"]
        for r in reminders:
            trigger_dt = datetime.fromisoformat(r.trigger_time)
            time_str = trigger_dt.strftime("%Y-%m-%d %H:%M")
            msg_preview = r.message[:40] + "..." if len(r.message) > 40 else r.message
            lines.append(f"• *#{r.id}* - {time_str}\n  _{msg_preview}_")

        lines.append('\nTo cancel, say: "Cancel reminder #N"')
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        logger.exception("Failed to list reminders")
        await update.message.reply_text(
            "❌ Failed to retrieve reminders. Please try again later."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages and forward to the ADK agent."""
    if not update.message or not update.message.text:
        return

    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    user_message = update.message.text

    logger.info(f"Message from {user_id}: {user_message[:50]}...")

    # Send typing indicator (best effort - don't fail if this times out)
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action="typing",
        )
    except (TimedOut, NetworkError):
        logger.warning(f"Failed to send typing indicator for user {user_id}")

    try:
        # Process message through ADK agent
        response = await process_message(
            user_id=user_id,
            message=user_message,
        )

        # Handle empty responses
        if not response or not response.strip():
            logger.warning(f"Agent returned empty response for user {user_id}")
            await update.message.reply_text(
                "🤔 I'm not sure how to respond to that. Could you rephrase?"
            )
            return

        # Convert markdown to Telegram MARKDOWN_V2 format
        telegram_response = convert_markdown_to_telegram(response)

        # Split long messages if needed (Telegram has 4096 char limit)
        if len(telegram_response) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(
                telegram_response, parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # Split into chunks at natural boundaries when possible
            await _send_long_message(update.message, telegram_response)

    except TelegramError as e:
        logger.error(f"Telegram API error for user {user_id}: {e}")
        await update.message.reply_text(
            "❌ Sorry, there was a problem sending the response. "
            "Please try again later."
        )
    except Exception:
        # Catch-all for unexpected errors, but let critical exceptions propagate
        logger.exception(f"Error processing message for user {user_id}")
        await update.message.reply_text(
            "❌ Sorry, an error occurred while processing your message. "
            "Please try again later."
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler for unhandled exceptions."""
    error = context.error

    if isinstance(error, TimedOut):
        logger.warning("Telegram API timeout - network may be slow")
        if isinstance(update, Update) and update.message:
            with contextlib.suppress(Exception):
                await update.message.reply_text(
                    "⏳ The request timed out. Please try again."
                )
    elif isinstance(error, NetworkError):
        logger.error(f"Network error: {error}")
    else:
        logger.exception(f"Unhandled error: {error}")


async def _send_long_message(message: Message, text: str) -> None:
    """Send a long message by splitting it at natural boundaries.

    This function attempts to split messages at paragraph breaks, newlines,
    or sentence boundaries to preserve formatting and readability.

    Args:
        message: The Telegram message object to reply to.
        text: The text to send (already converted to Telegram format).
    """
    # Try to split at paragraph breaks first (double newlines)
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for paragraph in paragraphs:
        # Check if adding this paragraph would exceed the limit
        if (
            current_chunk
            and len(current_chunk) + 2 + len(paragraph) > MAX_MESSAGE_LENGTH
        ):
            # Send current chunk
            await message.reply_text(
                current_chunk.strip(), parse_mode=ParseMode.MARKDOWN_V2
            )
            current_chunk = paragraph
        elif current_chunk:
            current_chunk += "\n\n" + paragraph
        else:
            current_chunk = paragraph

    # Send remaining content
    if current_chunk:
        if len(current_chunk) <= MAX_MESSAGE_LENGTH:
            await message.reply_text(
                current_chunk.strip(), parse_mode=ParseMode.MARKDOWN_V2
            )
        else:
            # Fallback: split at single newlines or character boundaries
            await _split_and_send(message, current_chunk)


async def _split_and_send(message: Message, text: str) -> None:
    """Fallback splitter for text that can't be split at paragraph boundaries.

    Args:
        message: The Telegram message object to reply to.
        text: Text to send (may exceed limit, already in Telegram format).
    """
    remaining = text

    while remaining:  # pragma: no branch
        if len(remaining) <= MAX_MESSAGE_LENGTH:
            await message.reply_text(
                remaining.strip(), parse_mode=ParseMode.MARKDOWN_V2
            )
            break

        # Try to find a good split point
        split_point = MAX_MESSAGE_LENGTH

        # Look for newline near the limit
        newline_pos = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if newline_pos > MAX_MESSAGE_LENGTH // 2:
            split_point = newline_pos + 1
        else:
            # Look for space near the limit
            space_pos = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
            if space_pos > MAX_MESSAGE_LENGTH // 2:
                split_point = space_pos + 1

        chunk = remaining[:split_point].strip()
        if chunk:
            await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)
        remaining = remaining[split_point:]


def create_application(token: str) -> Application:
    """Create and configure the Telegram Application.

    Args:
        token: The Telegram bot token.

    Returns:
        Configured Application instance with handlers registered.
    """
    # Create session service (uses DATABASE_URL when set for persistence)
    session_service = create_session_service_for_runner()

    # Initialize the ADK runner with the root agent
    initialize_runner(
        agent=root_agent,
        app_name="telegram-adk-bot",
        session_service=session_service,
    )

    # Create the Telegram Application
    application = (
        Application.builder().token(token).post_init(_set_bot_commands).build()
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("reminders", reminders_command))

    # Add message handler for text messages
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Add global error handler
    application.add_error_handler(error_handler)

    return application


async def _set_bot_commands(application: Application) -> None:
    """Set bot commands for the Telegram command menu and start scheduler.

    This registers the available commands with Telegram so users see
    a popup menu when they type '/' in the chat. Also initializes the
    reminder scheduler and notification service with the bot instance.

    Args:
        application: The Telegram Application instance.
    """
    commands = [
        BotCommand("start", "Show welcome message"),
        BotCommand("help", "Display help information"),
        BotCommand("reset", "Clear conversation and start fresh"),
        BotCommand("reminders", "List your scheduled reminders"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram")

    # Initialize and start the reminder scheduler
    scheduler = get_scheduler()
    scheduler.set_bot(application.bot)

    # Set the TelegramHandler for agent-aware reminders
    handler = get_handler()
    if handler is not None:
        scheduler.set_handler(handler)
        logger.info("Agent-aware reminders enabled")
    else:
        logger.warning(
            "TelegramHandler not initialized, reminders will use simple format"
        )

    await scheduler.start()
    logger.info("Reminder scheduler started")

    # Initialize the tool notification service
    notification_service = get_notification_service()
    notification_service.set_bot(application.bot)
    logger.info("Tool notification service initialized")


def run_bot(token: str | None) -> int:
    """Run the Telegram bot and return exit code.

    Args:
        token: The Telegram bot token, or None if not configured.

    Returns:
        0 on success, 1 on error (missing token).
    """
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is required")
        return 1

    application = create_application(token)

    # Start the bot
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


def main() -> None:
    """Run the Telegram bot."""
    exit_code = run_bot(TELEGRAM_BOT_TOKEN)
    if exit_code != 0:
        sys.exit(exit_code)


if __name__ == "__main__":  # pragma: no cover
    main()
