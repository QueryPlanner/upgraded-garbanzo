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

import asyncio
import contextlib
import html
import logging
import os
import re
import sys

from dotenv import load_dotenv
from openinference.instrumentation.google_adk import GoogleADKInstrumentor
from telegram import Bot, BotCommand, InputFile, Update
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

from ..utils.app_timezone import format_stored_instant_for_display
from ..utils.observability import configure_otel_resource, setup_logging

# Load environment variables from .env file
load_dotenv()

from ..agent import app  # noqa: E402
from ..reminders import get_scheduler  # noqa: E402
from ..telegram_prefs import (  # noqa: E402
    TELEGRAM_SESSION_LITELLM_MODEL_KEY,
    TELEGRAM_SESSION_PROVIDER_KEY,
    TELEGRAM_USAGE_COMPLETION_KEY,
    TELEGRAM_USAGE_PROMPT_KEY,
    TELEGRAM_USAGE_TOTAL_KEY,
)
from ..utils.session import create_session_service_for_runner  # noqa: E402
from ..utils.telegram_outbox import PendingTelegramFile  # noqa: E402
from .handler import (  # noqa: E402
    _read_litellm_model_from_state,
    get_handler,
    initialize_runner,
    process_message,
    reset_session,
)
from .model_settings import (  # noqa: E402
    default_root_model,
    format_flat_model_menu,
    infer_provider_from_model_id,
    resolve_flat_menu_index,
    resolve_model_freeform,
)
from .notifications import get_notification_service  # noqa: E402
from .session_state import merge_session_state_delta  # noqa: E402

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Bot configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_MESSAGE_LENGTH = 4096  # Telegram's message limit
TELEGRAM_DOCUMENT_CAPTION_MAX = 1024
TELEGRAM_MAX_CONCURRENT_UPDATES = 32
_TELEGRAM_OBSERVABILITY_INITIALIZED = False


def _initialize_observability() -> None:
    """Initialize OpenTelemetry and logging for the Telegram entrypoint.

    The FastAPI server already performs this setup at import time. The Telegram
    bot has a separate process entrypoint, so it needs to bootstrap the same
    observability stack before the first ADK invocation starts.
    """
    global _TELEGRAM_OBSERVABILITY_INITIALIZED

    if _TELEGRAM_OBSERVABILITY_INITIALIZED:
        return

    configured_agent_name = os.getenv("AGENT_NAME")
    if configured_agent_name is None:
        agent_name = app.name
    else:
        stripped_agent_name = configured_agent_name.strip()
        agent_name = stripped_agent_name if stripped_agent_name else app.name

    configured_log_level = os.getenv("LOG_LEVEL", "INFO")
    log_level = configured_log_level.strip() if configured_log_level else "INFO"

    configure_otel_resource(agent_name=agent_name)
    GoogleADKInstrumentor().instrument()
    setup_logging(log_level=log_level)

    _TELEGRAM_OBSERVABILITY_INITIALIZED = True
    logger.info("Telegram observability initialized for agent %s", agent_name)


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
        "/model - List models or pick by number (e.g. /model 3)\n"
        "/tokens - Show session token usage\n"
        "/reminders - List your scheduled reminders\n\n"
        "*Reminders:* Ask me to remind you about things!\n"
        'Examples: "Remind me in 30 minutes to take a break" or '
        '"Remind me every Monday at 8:30 to plan the week"'
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
        "/model - Numbered list; set with /model N or a full model id\n"
        "/tokens - Cumulative tokens for this chat session\n"
        "/reminders - List your scheduled reminders\n\n"
        "*Reminders:*\n"
        "You can ask me to set reminders like:\n"
        '• "Remind me to call mom in 30 minutes"\n'
        '• "Remind me about the meeting at 3pm today"\n'
        '• "Remind me tomorrow at 9am to check emails"\n'
        '• "Remind me every 15 minutes to stretch"\n'
        '• "Remind me every Monday at 8:30 to plan the week"'
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


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List or set the LiteLLM model for this chat (session-scoped)."""
    if not update.message or not update.effective_user:
        return

    handler = get_handler()
    if handler is None:
        await update.message.reply_text(
            "❌ Bot is not fully initialized. Try again later."
        )
        return

    user_id = str(update.effective_user.id)
    session = await handler.runner.session_service.get_session(
        app_name=handler.app_name,
        user_id=user_id,
        session_id=user_id,
    )
    state = dict(session.state) if session is not None else {}

    args = context.args or []
    if not args:
        override = _read_litellm_model_from_state(state)
        active = override if override is not None else default_root_model()
        body = (
            f"*Active model:* `{active}`\n"
            f"*Env default:* `{default_root_model()}`\n\n"
            "*Models (reply with `/model N` or a full id):*\n"
            f"{format_flat_model_menu()}\n\n"
            "_Short ids like `z-ai/glm-4.7` also work._"
        )
        await update.message.reply_text(body, parse_mode=ParseMode.MARKDOWN)
        return

    arg = " ".join(args).strip()
    if arg.isdigit():
        full_id, error_message = resolve_flat_menu_index(int(arg))
    else:
        full_id, error_message = resolve_model_freeform(arg)
    if error_message is not None or full_id is None:
        await update.message.reply_text(f"❌ {error_message or 'Invalid model.'}")
        return

    state_delta: dict[str, str] = {TELEGRAM_SESSION_LITELLM_MODEL_KEY: full_id}
    inferred = infer_provider_from_model_id(full_id)
    if inferred is not None:
        state_delta[TELEGRAM_SESSION_PROVIDER_KEY] = inferred

    await merge_session_state_delta(
        handler.runner.session_service,
        app_name=handler.app_name,
        user_id=user_id,
        session_id=user_id,
        state_delta=state_delta,
    )

    await update.message.reply_text(
        f"✅ Model set to `{full_id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show cumulative token usage for this chat session (when the API reports it)."""
    if not update.message or not update.effective_user:
        return

    handler = get_handler()
    if handler is None:
        await update.message.reply_text(
            "❌ Bot is not fully initialized. Try again later."
        )
        return

    user_id = str(update.effective_user.id)
    session = await handler.runner.session_service.get_session(
        app_name=handler.app_name,
        user_id=user_id,
        session_id=user_id,
    )
    state = dict(session.state) if session is not None else {}

    def _as_int(key: str) -> int:
        raw = state.get(key)
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    prompt_n = _as_int(TELEGRAM_USAGE_PROMPT_KEY)
    completion_n = _as_int(TELEGRAM_USAGE_COMPLETION_KEY)
    total_n = _as_int(TELEGRAM_USAGE_TOTAL_KEY)
    override = _read_litellm_model_from_state(state)
    active_model = override if override is not None else default_root_model()

    lines = [
        "📊 *Session token usage*",
        "_Totals accrue per LLM turn when the provider returns usage metadata._",
        "",
        f"Prompt tokens: *{prompt_n}*",
        f"Completion tokens: *{completion_n}*",
        f"Total (as reported): *{total_n}*",
        "",
        f"Active model: `{active_model}`",
        "",
        "Use `/reset` to clear the chat and these counters.",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


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
            time_str = format_stored_instant_for_display(r.trigger_time)
            msg_preview = r.message[:40] + "..." if len(r.message) > 40 else r.message
            reminder_kind = "Recurring" if r.is_recurring else "One-time"
            reminder_lines = [f"• *#{r.id}* - {reminder_kind}"]
            reminder_lines.append(f"  Next: {time_str}")
            if r.recurrence_text:
                reminder_lines.append(f"  Repeats: {r.recurrence_text}")
            reminder_lines.append(f"  _{msg_preview}_")
            lines.append("\n".join(reminder_lines))

        lines.append('\nTo cancel, say: "Cancel reminder #N"')
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception:
        logger.exception("Failed to list reminders")
        await update.message.reply_text(
            "❌ Failed to retrieve reminders. Please try again later."
        )


async def _send_queued_telegram_documents(
    bot: Bot,
    chat_id: int,
    documents: tuple[PendingTelegramFile, ...],
) -> None:
    """Send files queued by agent tools; remove staging files after each attempt."""
    for doc in documents:
        try:
            caption = doc.caption
            if caption is not None and len(caption) > TELEGRAM_DOCUMENT_CAPTION_MAX:
                caption = caption[: TELEGRAM_DOCUMENT_CAPTION_MAX - 1] + "…"
            # PTB: str is treated as *file body* (UTF-8), not a path — open the file.
            with doc.path.open("rb") as upload_fh:
                document = InputFile(
                    upload_fh,
                    filename=doc.filename or doc.path.name,
                )
            await bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption,
            )
        except TelegramError:
            logger.warning(
                "Failed to send Telegram document to chat_id=%s path=%s",
                chat_id,
                doc.path,
                exc_info=True,
            )
        finally:
            doc.path.unlink(missing_ok=True)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages and forward to the ADK agent."""
    if not update.message or not update.message.text:
        return

    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    user_message = update.message.text

    logger.info(f"Message from {user_id}: {user_message[:50]}...")

    chat_id = update.effective_chat.id

    # Typing indicator: do not await before ADK work. A slow Telegram API
    # would otherwise add full round-trip latency before session/LLM pipeline.
    async def _send_typing_indicator() -> None:
        try:
            await context.bot.send_chat_action(
                chat_id=chat_id,
                action="typing",
            )
        except (TimedOut, NetworkError):
            logger.warning(f"Failed to send typing indicator for user {user_id}")
        except Exception:
            logger.exception("Unexpected error sending typing indicator")

    asyncio.create_task(_send_typing_indicator())

    try:

        async def _send_live_text_chunk(chunk_text: str) -> None:
            """Forward visible model text to Telegram as it arrives."""
            if not chunk_text.strip():
                return
            assert update.message is not None  # noqa: S101
            await _send_agent_text(update.message, chunk_text)

        # Process message through ADK agent
        reply = await process_message(
            user_id=user_id,
            message=user_message,
            on_text_chunk=_send_live_text_chunk,
        )

        if reply.superseded:
            logger.info("Skipping superseded Telegram reply for user %s", user_id)
            return

        response_text = reply.text
        has_text = bool(response_text and response_text.strip())
        if not has_text and not reply.streamed_text and not reply.documents:
            logger.warning(f"Agent returned empty response for user {user_id}")
            await update.message.reply_text(
                "🤔 I'm not sure how to respond to that. Could you rephrase?"
            )
            return

        if has_text and not reply.streamed_text:
            await _send_agent_text(update.message, response_text)

        await _send_queued_telegram_documents(
            bot=context.bot,
            chat_id=chat_id,
            documents=reply.documents,
        )

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


async def _send_agent_text(message: Message, response_text: str) -> None:
    """Render markdown-like agent text and send it to Telegram."""
    telegram_response = _render_markdown_as_html(response_text)

    if len(telegram_response) <= MAX_MESSAGE_LENGTH:
        await _send_validated_chunk(
            message=message,
            chunk=telegram_response,
            fallback_text=response_text,
        )
        return

    await _send_long_message(message, telegram_response)


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
        text: The text to send (already converted to Telegram HTML).
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
            # Send current chunk (validated)
            await _send_validated_chunk(message, current_chunk.strip())
            current_chunk = paragraph
        elif current_chunk:
            current_chunk += "\n\n" + paragraph
        else:
            current_chunk = paragraph

    # Send remaining content
    if current_chunk:
        if len(current_chunk) <= MAX_MESSAGE_LENGTH:
            await _send_validated_chunk(message, current_chunk.strip())
        else:
            # Fallback: split at single newlines or character boundaries
            await _split_and_send(message, current_chunk)


def _render_html_as_plain_text(text: str) -> str:
    """Convert simple Telegram HTML into readable plain text."""
    plain_text = re.sub(r"<a\s+href=\"([^\"]+)\">([^<]+)</a>", r"\2 (\1)", text)
    plain_text = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote)>", "", plain_text)
    plain_text = plain_text.replace("&lt;", "<")
    plain_text = plain_text.replace("&gt;", ">")
    plain_text = plain_text.replace("&amp;", "&")
    plain_text = plain_text.replace("&quot;", '"')

    return plain_text


def _split_markdown_to_segments(text: str) -> list[tuple[str, ...]]:
    """Split markdown into ordered segments so code/links never cross format spans.

    Each segment is ``("text", str)``, ``("code_inline", inner)``,
    ``("code_block", inner)``, or ``("link", display, url)`` (three-tuple).
    """
    segments: list[tuple[str, ...]] = []
    buf: list[str] = []
    i = 0
    n = len(text)

    def flush_text() -> None:
        if buf:
            segments.append(("text", "".join(buf)))
            buf.clear()

    while i < n:
        if text.startswith("```", i):
            flush_text()
            i += 3
            fence_open = i - 3
            lang_match = re.match(r"([a-zA-Z0-9_-]{0,32})\s*\n", text[i:])
            if lang_match:
                i += lang_match.end()
            close = text.find("```", i)
            if close == -1:
                buf.append(text[fence_open:])
                break
            segments.append(("code_block", text[i:close]))
            i = close + 3
            continue

        if text[i] == "`":
            flush_text()
            close = text.find("`", i + 1)
            if close == -1:
                buf.append(text[i])
                i += 1
                continue
            segments.append(("code_inline", text[i + 1 : close]))
            i = close + 1
            continue

        if text[i] == "[":
            link_match = re.match(r"\[([^\]]*)\]\(([^)]*)\)", text[i:])
            if link_match:
                flush_text()
                segments.append(
                    ("link", link_match.group(1), link_match.group(2)),
                )
                i += link_match.end()
                continue

        buf.append(text[i])
        i += 1

    flush_text()
    return segments


def _apply_markdown_inline_to_escaped_html(escaped_text: str) -> str:
    """Apply bold/italic/underline/strike/header patterns to already-escaped HTML."""
    result = escaped_text
    result = re.sub(
        r"(?m)^#{1,6}\s*(.+)$",
        lambda match: f"<b>{match.group(1).strip()}</b>",
        result,
    )
    result = re.sub(r"(?<!\*)\*\*([^*]+)\*\*(?!\*)", r"<b>\1</b>", result)
    result = re.sub(r"(?<!_)__([^_]+)__(?!_)", r"<u>\1</u>", result)
    result = re.sub(r"~~([^~]+)~~", r"<s>\1</s>", result)
    result = re.sub(
        r"(?<!\*)\*(?!\*)([^*]+)(?<!\*)\*(?!\*)",
        r"<i>\1</i>",
        result,
    )
    result = re.sub(
        r"(?<!_)_(?!_)([^_]+)(?<!_)_(?!_)",
        r"<i>\1</i>",
        result,
    )
    return result


def _telegram_html_tag_stack_valid(fragment: str) -> bool:
    """Return True if Telegram HTML tags are properly nested and closed."""
    tag_pattern = re.compile(
        r"<(/?)(b|strong|i|em|u|s|strike|del|code|pre|a)\b[^>]*>",
        re.IGNORECASE,
    )
    stack: list[str] = []

    def normalize(name: str) -> str:
        aliases = {"strong": "b", "em": "i", "strike": "s", "del": "s"}
        return aliases.get(name.lower(), name.lower())

    pos = 0
    while pos < len(fragment):
        match = tag_pattern.search(fragment, pos)
        if not match:
            break
        is_close = match.group(1) == "/"
        raw_name = match.group(2)
        name = normalize(raw_name)
        if name == "a":
            if is_close:
                if not stack or stack[-1] != "a":
                    return False
                stack.pop()
            else:
                stack.append("a")
        elif is_close:
            if not stack or stack[-1] != name:
                return False
            stack.pop()
        else:
            stack.append(name)
        pos = match.end()

    return len(stack) == 0


def _render_markdown_as_html(text: str) -> str:
    """Convert common markdown patterns into Telegram-safe HTML.

    Code spans and fenced blocks are parsed before bold/italic so underscores
    and asterisks inside code do not produce crossed ``<i>``/``<code>`` tags.
    """
    if not text:
        return text

    parts: list[str] = []
    for segment in _split_markdown_to_segments(text):
        match segment:
            case ("text", body):
                escaped = html.escape(body)
                parts.append(_apply_markdown_inline_to_escaped_html(escaped))
            case ("code_inline", inner):
                parts.append(f"<code>{html.escape(inner)}</code>")
            case ("code_block", inner):
                parts.append(f"<pre>{html.escape(inner)}</pre>")
            case ("link", display, url):
                safe_href = html.escape(url, quote=True)
                parts.append(
                    f'<a href="{safe_href}">{html.escape(display)}</a>',
                )
            case _:
                parts.append(html.escape(str(segment)))

    rendered = "".join(parts).strip()
    if not _telegram_html_tag_stack_valid(rendered):
        return html.escape(text)
    return rendered


async def _send_validated_chunk(
    message: Message,
    chunk: str,
    fallback_text: str | None = None,
) -> None:
    """Send a chunk using Telegram HTML with a plain-text fallback.

    Args:
        message: The Telegram message object to reply to.
        chunk: The text chunk to send.
        fallback_text: Original markdown version to send if HTML fails.
    """
    if fallback_text is not None:
        plain_text = fallback_text
    else:
        plain_text = _render_html_as_plain_text(chunk)

    try:
        await message.reply_text(chunk, parse_mode=ParseMode.HTML)
        return
    except TelegramError:
        logger.warning(
            "Telegram rejected HTML chunk, retrying without formatting",
            exc_info=True,
        )

    await message.reply_text(plain_text)


async def _split_and_send(message: Message, text: str) -> None:
    """Fallback splitter for text that can't be split at paragraph boundaries.

    Args:
        message: The Telegram message object to reply to.
        text: Text to send (may exceed limit, already in Telegram format).
    """
    remaining = text

    while remaining:  # pragma: no branch
        if len(remaining) <= MAX_MESSAGE_LENGTH:
            await _send_validated_chunk(message, remaining.strip())
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
            await _send_validated_chunk(message, chunk)
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

    # Initialize the ADK runner with the App (includes GlobalInstructionPlugin)
    initialize_runner(
        app=app,
        session_service=session_service,
    )

    # Create the Telegram Application
    application = (
        Application.builder()
        .token(token)
        .concurrent_updates(TELEGRAM_MAX_CONCURRENT_UPDATES)
        .post_init(_set_bot_commands)
        .build()
    )

    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reset", reset_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
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
        BotCommand("model", "List models or set by number"),
        BotCommand("tokens", "Session token usage"),
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

    _initialize_observability()
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
