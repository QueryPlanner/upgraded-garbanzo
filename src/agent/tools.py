"""Custom tools for the LLM agent."""

import logging
from datetime import UTC, datetime
from typing import Any

import dateparser
from google.adk.tools import ToolContext

from .reminders import Reminder, get_scheduler

logger = logging.getLogger(__name__)


def example_tool(
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Example tool that logs a success message.

    This is a placeholder example tool. Replace with actual implementation.

    Args:
        tool_context: ADK ToolContext with access to session state

    Returns:
        A dictionary with status and message about the logging operation.
    """
    # TODO: add tool logic

    # Log the session state keys
    logger.info(f"Session state keys: {tool_context.state.to_dict().keys()}")

    message = "Successfully used example_tool."
    logger.info(message)
    return {"status": "success", "message": message}


async def schedule_reminder(
    tool_context: ToolContext,
    message: str,
    reminder_datetime: str,
) -> dict[str, Any]:
    """Schedule a reminder to be sent at a specific time.

    The reminder will be sent as a Telegram message to the user.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        message: The reminder message to send (max 500 characters).
        reminder_datetime: When to send the reminder. Use format:
            "YYYY-MM-DD HH:MM" (e.g., "2026-03-15 14:30")
            or relative time like "in 30 minutes", "tomorrow at 9am",
            "in 2 hours", "at 5pm today".

    Returns:
        A dictionary with status, reminder_id, and confirmation message.
    """
    # Get user_id from tool context (check both direct property and state)
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    if not user_id:
        logger.error("No user_id in tool context")
        return {
            "status": "error",
            "message": "Cannot schedule reminder: user not identified.",
        }

    # Parse the datetime
    try:
        trigger_time = _parse_reminder_datetime(reminder_datetime)
    except ValueError as e:
        logger.warning(f"Failed to parse datetime '{reminder_datetime}': {e}")
        return {
            "status": "error",
            "message": "Could not understand the time format. "
            "Please use a format like '2026-03-15 14:30' or "
            "'in 30 minutes', 'tomorrow at 9am'.",
        }

    # Validate message length
    if len(message) > 500:
        return {
            "status": "error",
            "message": "Reminder message too long (max 500 characters).",
        }

    # Check if time is in the past
    if trigger_time <= datetime.now(UTC):
        return {
            "status": "error",
            "message": "The reminder time must be in the future.",
        }

    # Schedule the reminder
    try:
        scheduler = get_scheduler()
        reminder_id = await scheduler.schedule_reminder(
            user_id=user_id,
            message=message,
            trigger_time=trigger_time,
        )

        formatted_time = trigger_time.strftime("%Y-%m-%d %H:%M")
        logger.info(
            f"Scheduled reminder {reminder_id} for user {user_id} at {formatted_time}"
        )

        return {
            "status": "success",
            "reminder_id": reminder_id,
            "message": f"Reminder scheduled for {formatted_time}. "
            f"I'll send you: '{message[:50]}{'...' if len(message) > 50 else ''}'",
        }
    except Exception as e:
        logger.exception("Failed to schedule reminder")
        return {
            "status": "error",
            "message": f"Failed to schedule reminder: {e}",
        }


async def list_reminders(
    tool_context: ToolContext,
    include_sent: bool = False,
) -> dict[str, Any]:
    """List all scheduled reminders for the user.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        include_sent: Whether to include already-sent reminders.

    Returns:
        A dictionary with status and list of reminders.
    """
    # Get user_id from tool context (check both direct property and state)
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot list reminders: user not identified.",
        }

    try:
        scheduler = get_scheduler()
        reminders = await scheduler.get_user_reminders(user_id, include_sent)

        if not reminders:
            return {
                "status": "success",
                "reminders": [],
                "message": "You have no scheduled reminders.",
            }

        # Format reminders for display
        formatted = [_format_reminder(r) for r in reminders]
        return {
            "status": "success",
            "reminders": formatted,
            "count": len(reminders),
            "message": f"You have {len(reminders)} reminder(s) scheduled.",
        }
    except Exception as e:
        logger.exception("Failed to list reminders")
        return {
            "status": "error",
            "message": f"Failed to list reminders: {e}",
        }


async def cancel_reminder(
    tool_context: ToolContext,
    reminder_id: int,
) -> dict[str, Any]:
    """Cancel a scheduled reminder.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        reminder_id: The ID of the reminder to cancel.

    Returns:
        A dictionary with status and confirmation message.
    """
    # Get user_id from tool context (check both direct property and state)
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot cancel reminder: user not identified.",
        }

    try:
        scheduler = get_scheduler()
        deleted = await scheduler.delete_reminder(reminder_id, user_id)

        if deleted:
            return {
                "status": "success",
                "message": f"Reminder {reminder_id} cancelled.",
            }
        else:
            return {
                "status": "error",
                "message": f"Reminder {reminder_id} not found "
                "or you don't have permission to cancel it.",
            }
    except Exception as e:
        logger.exception("Failed to cancel reminder")
        return {
            "status": "error",
            "message": f"Failed to cancel reminder: {e}",
        }


def _parse_reminder_datetime(datetime_str: str) -> datetime:
    """Parse a datetime string into a timezone-aware UTC datetime object.

    Uses dateparser for robust natural language parsing. Supports:
    - Absolute: "2026-03-15 14:30", "March 15, 2026 at 2pm"
    - Relative: "in 30 minutes", "tomorrow at 9am", "in 2 hours"
    - Natural language: "next Monday at 5pm", "at 5pm today"

    Args:
        datetime_str: The datetime string to parse.

    Returns:
        A timezone-aware datetime object in UTC.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    parsed_time = dateparser.parse(
        datetime_str,
        settings={"PREFER_DATES_FROM": "future", "TO_TIMEZONE": "UTC"},
    )
    if not parsed_time:
        raise ValueError(f"Could not parse datetime: {datetime_str}")

    # Ensure the datetime is timezone-aware in UTC
    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=UTC)
    else:
        # Convert to UTC if it has a different timezone
        parsed_time = parsed_time.astimezone(UTC)

    return parsed_time


def _format_reminder(reminder: Reminder) -> dict[str, Any]:
    """Format a reminder for display."""
    trigger_dt = datetime.fromisoformat(reminder.trigger_time)
    return {
        "id": reminder.id,
        "message": reminder.message,
        "trigger_time": trigger_dt.strftime("%Y-%m-%d %H:%M"),
        "is_sent": reminder.is_sent,
    }
