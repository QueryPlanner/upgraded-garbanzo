"""Miscellaneous tools for the ADK agent."""

import logging
from datetime import datetime
from typing import Any

from google.adk.tools import ToolContext

from ..utils.app_timezone import get_app_timezone

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


def get_current_datetime(tool_context: ToolContext) -> dict[str, Any]:
    """Return the current date and time in the app timezone, to the second.

    Call this before scheduling relative reminders (e.g. \"in 10 minutes\") so the
    model uses the same \"now\" as the server. Default timezone is India Standard
    Time (Asia/Kolkata); override with AGENT_TIMEZONE.

    Args:
        tool_context: ADK ToolContext (unused; required for tool signature).

    Returns:
        ISO timestamp with offset, split date/time fields, and weekday.
    """
    _ = tool_context
    tz = get_app_timezone()
    now = datetime.now(tz)
    tz_name = tz.key
    return {
        "timezone": tz_name,
        "iso_datetime": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "hint": (
            "Use this clock for reminders. Pass iso_datetime to schedule_reminder, "
            "or a relative phrase like 'in 7 minutes' (this timezone)."
        ),
    }


__all__ = ["example_tool", "get_current_datetime"]
