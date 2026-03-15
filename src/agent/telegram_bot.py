"""Telegram bot runner for the ADK agent.

This script starts a Telegram bot that connects to your ADK agent,
allowing users to interact with the agent through Telegram messages.

Setup Instructions:
1. Create a bot via @BotFather on Telegram and get your bot token
2. Set TELEGRAM_BOT_TOKEN environment variable
3. Run: uv run telegram-bot

Usage:
    - Send any message to interact with the agent
    - Use /clear to start a new conversation
    - Use /help to see available commands
"""

import logging
import os
import sys

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables from .env file
load_dotenv()

from .agent import root_agent  # noqa: E402
from .telegram_handler import (  # noqa: E402
    clear_session,
    initialize_runner,
    process_message,
)

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
        "/clear - Start a fresh conversation"
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
        "/clear - Clear conversation history and start fresh"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /clear command to reset conversation."""
    if not update.message or not update.effective_user:
        return

    user_id = str(update.effective_user.id)
    await clear_session(user_id=user_id)
    await update.message.reply_text(
        "🔄 Conversation cleared! Starting fresh.",
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

    # Send typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        # Process message through ADK agent
        response = await process_message(
            user_id=user_id,
            message=user_message,
        )

        # Split long messages if needed (Telegram has 4096 char limit)
        if len(response) <= MAX_MESSAGE_LENGTH:
            await update.message.reply_text(response)
        else:
            # Split into chunks
            chunks = [
                response[i : i + MAX_MESSAGE_LENGTH]
                for i in range(0, len(response), MAX_MESSAGE_LENGTH)
            ]
            for chunk in chunks:
                await update.message.reply_text(chunk)

    except Exception:
        logger.exception(f"Error processing message for user {user_id}")
        await update.message.reply_text(
            "❌ Sorry, an error occurred while processing your message. "
            "Please try again later."
        )


def main() -> None:
    """Run the Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is required")
        sys.exit(1)

    # Initialize the ADK runner with the root agent
    initialize_runner(agent=root_agent, app_name="telegram-adk-bot")

    # Create the Telegram Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))

    # Add message handler for text messages
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    # Start the bot
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
