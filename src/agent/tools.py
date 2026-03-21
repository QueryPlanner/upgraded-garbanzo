"""Custom tools for the LLM agent."""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dateparser
from google.adk.tools import ToolContext

from .fitness import (
    CalorieEntry,
    ExerciseType,
    MealType,
    WorkoutEntry,
    get_fitness_storage,
)
from .reminders import Reminder, get_scheduler
from .reminders.recurrence import (
    RecurringSchedule,
    get_next_trigger_time,
    validate_cron_expression,
)
from .utils.app_timezone import (
    format_stored_instant_for_display,
    get_app_timezone,
    naive_local_now,
    now_utc,
    utc_iso_seconds,
)

logger = logging.getLogger(__name__)

SUPPORTED_RECURRENCE_MESSAGE = (
    "Recurring reminders must use a 5-field cron expression in the app "
    "timezone, for example '* * * * *' for every minute, "
    "'*/15 * * * *' for every 15 minutes, or '30 8 * * 1' for Mondays "
    "at 08:30."
)


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


async def schedule_reminder(
    tool_context: ToolContext,
    message: str,
    reminder_datetime: str | None = None,
    recurrence: str | None = None,
) -> dict[str, Any]:
    """Schedule a reminder to be sent at a specific time.

    The reminder will be delivered through the agent as a Telegram message.
    The stored message is shown back to the agent when the reminder fires, so
    ``message`` should be a self-contained instruction for what the user should
    receive at delivery time. If the reminder should produce fresh generated
    content, describe that outcome directly in ``message`` instead of writing
    scheduling meta text.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        message: Self-contained delivery instruction for the future reminder
            (max 500 characters). The fired reminder passes it back through the
            agent to generate the final user-facing message.
        reminder_datetime: For one-time reminders, when to fire in the app
            local timezone (default IST / Asia/Kolkata; set AGENT_TIMEZONE to
            change). Use wall-clock strings such as '2026-03-15 14:30', the
            ``iso_datetime`` from ``get_current_datetime``, or relative phrases
            like 'in 30 minutes' or 'tomorrow at 9am'.
        recurrence: Optional recurring schedule as a 5-field cron expression in
            the app timezone. Translate user cadence into cron before calling
            this tool. Examples: '* * * * *', '*/15 * * * *', '30 8 * * 1'.

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

    try:
        reminder_schedule = _build_reminder_schedule(
            reminder_datetime=reminder_datetime,
            recurrence=recurrence,
        )
    except ValueError as e:
        logger.warning(
            "Failed to parse reminder schedule (datetime=%r recurrence=%r): %s",
            reminder_datetime,
            recurrence,
            e,
        )
        error_message = str(e)
        if not recurrence:
            error_message = (
                "Could not understand the time. Use IST/local wall time, e.g. "
                "'2026-03-15 14:30', get_current_datetime's iso_datetime, or "
                "'in 30 minutes' / 'tomorrow at 9am'."
            )
        return {
            "status": "error",
            "message": error_message,
        }

    # Validate message length
    if len(message) > 500:
        return {
            "status": "error",
            "message": "Reminder message too long (max 500 characters).",
        }

    if reminder_schedule["trigger_time"] <= now_utc():
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
            trigger_time=reminder_schedule["trigger_time"],
            recurrence_rule=reminder_schedule["recurrence_rule"],
            recurrence_text=reminder_schedule["recurrence_text"],
            timezone_name=reminder_schedule["timezone_name"],
        )

        display_time = format_stored_instant_for_display(
            utc_iso_seconds(reminder_schedule["trigger_time"])
        )
        logger.info(
            "Scheduled reminder %s for user %s at %s (stored as UTC)",
            reminder_id,
            user_id,
            utc_iso_seconds(reminder_schedule["trigger_time"]),
        )

        confirmation_prefix = "Recurring reminder scheduled"
        if reminder_schedule["recurrence_rule"] is None:
            confirmation_prefix = "Reminder scheduled"

        recurrence_suffix = ""
        if reminder_schedule["recurrence_text"]:
            recurrence_suffix = f" ({reminder_schedule['recurrence_text']})"

        return {
            "status": "success",
            "reminder_id": reminder_id,
            "message": f"{confirmation_prefix}{recurrence_suffix}. Next send: "
            f"{display_time}. "
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
    """Parse natural-language or absolute datetimes in the app timezone, return UTC.

    Relative phrases (e.g. \"in 5 minutes\") use the server's wall clock in the app
    timezone (default Asia/Kolkata) so they match user expectations.

    Returns:
        Timezone-aware UTC datetime for storage and comparison.
    """
    tz = get_app_timezone()
    tz_name = tz.key
    parsed_time = dateparser.parse(
        datetime_str,
        settings={
            "PREFER_DATES_FROM": "future",
            "TIMEZONE": tz_name,
            "TO_TIMEZONE": tz_name,
            "RELATIVE_BASE": naive_local_now(),
        },
    )
    if not parsed_time:
        raise ValueError(f"Could not parse datetime: {datetime_str}")

    if parsed_time.tzinfo is None:
        parsed_time = parsed_time.replace(tzinfo=tz)
    else:
        parsed_time = parsed_time.astimezone(tz)

    return parsed_time.astimezone(UTC)


def _format_reminder(reminder: Reminder) -> dict[str, Any]:
    """Format a reminder for display (trigger time in app timezone, with seconds)."""
    next_trigger_time = format_stored_instant_for_display(reminder.trigger_time)
    return {
        "id": reminder.id,
        "message": reminder.message,
        "trigger_time": next_trigger_time,
        "next_trigger_time": next_trigger_time,
        "is_sent": reminder.is_sent,
        "is_recurring": reminder.is_recurring,
        "schedule_type": "recurring" if reminder.is_recurring else "one_time",
        "recurrence": reminder.recurrence_text,
    }


def _build_reminder_schedule(
    reminder_datetime: str | None,
    recurrence: str | None,
) -> dict[str, Any]:
    """Build the normalized schedule for one-shot or recurring reminders."""
    normalized_recurrence = (recurrence or "").strip()
    if not normalized_recurrence:
        if not reminder_datetime:
            raise ValueError(
                "One-time reminders need reminder_datetime. Use a time like "
                "'2026-03-15 14:30', 'in 30 minutes', or 'tomorrow at 9am'."
            )

        return {
            "trigger_time": _parse_reminder_datetime(reminder_datetime),
            "recurrence_rule": None,
            "recurrence_text": None,
            "timezone_name": None,
        }

    if reminder_datetime:
        raise ValueError(
            "Recurring reminders use recurrence only. Omit reminder_datetime "
            "and pass a 5-field cron expression. " + SUPPORTED_RECURRENCE_MESSAGE
        )

    recurring_schedule = _parse_recurring_schedule(normalized_recurrence)
    next_trigger_time = get_next_trigger_time(
        recurring_schedule.cron_expression,
        recurring_schedule.timezone_name,
    )

    return {
        "trigger_time": next_trigger_time,
        "recurrence_rule": recurring_schedule.cron_expression,
        "recurrence_text": recurring_schedule.description,
        "timezone_name": recurring_schedule.timezone_name,
    }


def _parse_recurring_schedule(recurrence: str) -> RecurringSchedule:
    """Validate a cron-style recurring schedule for reminder storage."""
    timezone_name = get_app_timezone().key
    normalized_recurrence = " ".join(recurrence.strip().split())
    try:
        cron_expression = validate_cron_expression(normalized_recurrence, timezone_name)
    except ValueError as error:
        raise ValueError(
            "Could not understand the recurring schedule. "
            + SUPPORTED_RECURRENCE_MESSAGE
        ) from error

    return RecurringSchedule(
        cron_expression=cron_expression,
        description=f"cron: {cron_expression}",
        timezone_name=timezone_name,
    )


# ============================================================================
# FITNESS TOOLS
# ============================================================================


def _get_user_id(tool_context: ToolContext) -> str | None:
    """Extract user_id from tool context."""
    user_id = getattr(tool_context, "user_id", None) or tool_context.state.get(
        "user_id"
    )
    return str(user_id) if user_id is not None else None


def _get_today_date() -> str:
    """Get today's date in YYYY-MM-DD format (app timezone, default IST)."""
    return datetime.now(get_app_timezone()).strftime("%Y-%m-%d")


async def add_calories(
    tool_context: ToolContext,
    food_item: str,
    calories: int,
    meal_type: str = "snack",
    protein: float | None = None,
    carbs: float | None = None,
    fat: float | None = None,
    date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Log a food entry with calorie and macro information.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        food_item: Description of the food consumed.
        calories: Number of calories. (Estimate if not provided)
        meal_type: Type of meal (breakfast, lunch, dinner, snack).
        protein: Grams of protein (optional). (Estimate if not provided)
        carbs: Grams of carbohydrates (optional). (Estimate if not provided)
        fat: Grams of fat (optional). (Estimate if not provided)
        date: Date in YYYY-MM-DD format (default: today).
        notes: Additional notes (optional).

    Returns:
        A dictionary with status, entry_id, and confirmation message.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot log calories: user not identified.",
        }

    try:
        # Validate and convert meal_type
        meal_type_enum = MealType(meal_type.lower())
    except ValueError:
        valid_types = "breakfast, lunch, dinner, or snack"
        return {
            "status": "error",
            "message": f"Invalid meal type '{meal_type}'. Use: {valid_types}.",
        }

    entry = CalorieEntry(
        user_id=user_id,
        date=date or _get_today_date(),
        food_item=food_item,
        calories=calories,
        protein=protein,
        carbs=carbs,
        fat=fat,
        meal_type=meal_type_enum,
        notes=notes,
        created_at=datetime.now(get_app_timezone()).isoformat(timespec="seconds"),
    )

    try:
        storage = get_fitness_storage()
        entry_id = await storage.add_calorie_entry(entry)
        logger.info(f"Added calorie entry {entry_id} for user {user_id}")

        return {
            "status": "success",
            "entry_id": entry_id,
            "message": f"Logged {food_item}: {calories} cal ({meal_type_enum.value})",
        }
    except Exception as e:
        logger.exception("Failed to add calorie entry")
        return {"status": "error", "message": f"Failed to log calories: {e}"}


async def list_calories(
    tool_context: ToolContext,
    start_date: str | None = None,
    end_date: str | None = None,
    meal_type: str | None = None,
) -> dict[str, Any]:
    """List calorie entries for a date range.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        start_date: Start date in YYYY-MM-DD format (optional).
        end_date: End date in YYYY-MM-DD format (optional).
        meal_type: Filter by meal type (optional).

    Returns:
        A dictionary with status and list of calorie entries.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot list calories: user not identified.",
        }

    try:
        storage = get_fitness_storage()
        entries = await storage.get_calorie_entries(user_id, start_date, end_date)

        # Filter by meal type if specified
        if meal_type:
            entries = [e for e in entries if e.meal_type.value == meal_type.lower()]

        if not entries:
            return {
                "status": "success",
                "entries": [],
                "count": 0,
                "total_calories": 0,
                "message": "No calorie entries found.",
            }

        formatted = [
            {
                "id": e.id,
                "date": e.date,
                "food_item": e.food_item,
                "calories": e.calories,
                "protein": e.protein,
                "carbs": e.carbs,
                "fat": e.fat,
                "meal_type": e.meal_type.value,
                "notes": e.notes,
            }
            for e in entries
        ]

        total_cal = sum(e.calories for e in entries)
        return {
            "status": "success",
            "entries": formatted,
            "count": len(entries),
            "total_calories": total_cal,
            "message": f"Found {len(entries)} entries totaling {total_cal} calories.",
        }
    except Exception as e:
        logger.exception("Failed to list calories")
        return {"status": "error", "message": f"Failed to list calories: {e}"}


async def get_calorie_stats(
    tool_context: ToolContext,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get calorie statistics including daily averages and totals.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        start_date: Start date in YYYY-MM-DD format (optional).
        end_date: End date in YYYY-MM-DD format (optional).

    Returns:
        A dictionary with status and calorie statistics.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {"status": "error", "message": "Cannot get stats: user not identified."}

    try:
        storage = get_fitness_storage()
        stats = await storage.get_calorie_stats(user_id, start_date, end_date)
        stats["status"] = "success"
        return stats
    except Exception as e:
        logger.exception("Failed to get calorie stats")
        return {"status": "error", "message": f"Failed to get stats: {e}"}


async def log_workout(
    tool_context: ToolContext,
    exercise_name: str,
    exercise_type: str = "other",
    duration_minutes: int | None = None,
    set: int | None = None,
    reps: int | None = None,
    weight: float | None = None,
    distance_km: float | None = None,
    date: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Record a workout/exercise entry.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        exercise_name: Name of the exercise (e.g., "bench press", "running").
        exercise_type: Type of exercise (strength, cardio, flexibility, sports, other).
        duration_minutes: Duration in minutes (optional).
        set: Sequence number of the logged set (for strength training).
        reps: Reps per set (for strength training).
        weight: Weight in kg (for strength training). For compact strength
            notation such as "40x10", callers should usually interpret this as
            40 kg and 10 reps unless the user clearly states another unit.
        distance_km: Distance in kilometers (for cardio).
        date: Date in YYYY-MM-DD format (default: today).
        notes: Additional notes (optional).

    Returns:
        A dictionary with status, entry_id, and confirmation message.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot log workout: user not identified.",
        }

    try:
        exercise_type_enum = ExerciseType(exercise_type.lower())
    except ValueError:
        return {
            "status": "error",
            "message": f"Invalid exercise type '{exercise_type}'. "
            "Use: strength, cardio, flexibility, sports, or other.",
        }

    entry = WorkoutEntry(
        user_id=user_id,
        date=date or _get_today_date(),
        exercise_type=exercise_type_enum,
        exercise_name=exercise_name,
        duration_minutes=duration_minutes,
        set=set,
        reps=reps,
        weight=weight,
        distance_km=distance_km,
        notes=notes,
        created_at=datetime.now(get_app_timezone()).isoformat(timespec="seconds"),
    )

    try:
        storage = get_fitness_storage()
        entry_id = await storage.add_workout_entry(entry)
        logger.info(f"Added workout entry {entry_id} for user {user_id}")

        details = []
        if set:
            details.append(f"set {set}")
        if reps:
            details.append(f"{reps} reps")
        if weight is not None:
            details.append(f"{weight}kg")
        if duration_minutes:
            details.append(f"{duration_minutes}min")
        if distance_km:
            details.append(f"{distance_km}km")

        detail_str = f" ({', '.join(details)})" if details else ""
        return {
            "status": "success",
            "entry_id": entry_id,
            "message": f"Logged {exercise_name}{detail_str}",
        }
    except Exception as e:
        logger.exception("Failed to log workout")
        return {"status": "error", "message": f"Failed to log workout: {e}"}


async def list_workouts(
    tool_context: ToolContext,
    start_date: str | None = None,
    end_date: str | None = None,
    exercise_type: str | None = None,
) -> dict[str, Any]:
    """List workout entries for a date range.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        start_date: Start date in YYYY-MM-DD format (optional).
        end_date: End date in YYYY-MM-DD format (optional).
        exercise_type: Filter by type (strength, cardio, etc.).

    Returns:
        A dictionary with status and list of workout entries.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {
            "status": "error",
            "message": "Cannot list workouts: user not identified.",
        }

    try:
        storage = get_fitness_storage()
        entries = await storage.get_workout_entries(
            user_id, start_date, end_date, exercise_type
        )

        if not entries:
            return {
                "status": "success",
                "entries": [],
                "message": "No workout entries found.",
            }

        formatted = [
            {
                "id": e.id,
                "date": e.date,
                "exercise_name": e.exercise_name,
                "exercise_type": e.exercise_type.value,
                "duration_minutes": e.duration_minutes,
                "set": e.set,
                "reps": e.reps,
                "weight": e.weight,
                "distance_km": e.distance_km,
                "notes": e.notes,
            }
            for e in entries
        ]

        return {
            "status": "success",
            "entries": formatted,
            "count": len(entries),
            "message": f"Found {len(entries)} workout entries.",
        }
    except Exception as e:
        logger.exception("Failed to list workouts")
        return {"status": "error", "message": f"Failed to list workouts: {e}"}


async def get_workout_stats(
    tool_context: ToolContext,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get workout statistics including frequency and personal records.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        start_date: Start date in YYYY-MM-DD format (optional).
        end_date: End date in YYYY-MM-DD format (optional).

    Returns:
        A dictionary with status and workout statistics.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {"status": "error", "message": "Cannot get stats: user not identified."}

    try:
        storage = get_fitness_storage()
        stats = await storage.get_workout_stats(user_id, start_date, end_date)
        stats["status"] = "success"
        return stats
    except Exception as e:
        logger.exception("Failed to get workout stats")
        return {"status": "error", "message": f"Failed to get stats: {e}"}


async def delete_fitness_entry(
    tool_context: ToolContext,
    entry_type: str,
    entry_id: int,
) -> dict[str, Any]:
    """Delete a calorie or workout entry.

    Args:
        tool_context: ADK ToolContext with user_id in state.
        entry_type: Type of entry to delete ("calorie" or "workout").
        entry_id: The ID of the entry to delete.

    Returns:
        A dictionary with status and confirmation message.
    """
    user_id = _get_user_id(tool_context)
    if not user_id:
        return {"status": "error", "message": "Cannot delete: user not identified."}

    if entry_type.lower() not in ("calorie", "workout"):
        return {
            "status": "error",
            "message": "Invalid entry_type. Must be 'calorie' or 'workout'.",
        }

    try:
        storage = get_fitness_storage()
        deleted = await storage.delete_entry(entry_type.lower(), entry_id, user_id)

        if deleted:
            return {
                "status": "success",
                "message": f"Deleted {entry_type} entry {entry_id}.",
            }
        else:
            return {
                "status": "error",
                "message": f"Entry {entry_id} not found or you don't have permission.",
            }
    except Exception as e:
        logger.exception("Failed to delete entry")
        return {"status": "error", "message": f"Failed to delete entry: {e}"}


# ============================================================================
# YOUTUBE TRANSCRIPT TOOLS
# ============================================================================


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats.

    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/embed/VIDEO_ID
    - https://www.youtube.com/v/VIDEO_ID

    Args:
        url: YouTube URL or video ID.

    Returns:
        The video ID string, or None if extraction failed.
    """
    import re

    # If it's already just a video ID (11 characters, alphanumeric + - and _)
    if re.match(r"^[\w-]{11}$", url):
        return url

    # Try various URL patterns
    patterns = [
        r"(?:youtube\.com\/watch\?v=)([\w-]{11})",
        r"(?:youtu\.be\/)([\w-]{11})",
        r"(?:youtube\.com\/embed\/)([\w-]{11})",
        r"(?:youtube\.com\/v\/)([\w-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


def get_youtube_transcript(
    tool_context: ToolContext,  # noqa: ARG001
    video_url: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Get the transcript from a YouTube video.

    Fetches the transcript/captions from a YouTube video using the
    youtube-transcript-api library. Supports multiple languages if available.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        video_url: YouTube video URL or video ID. Supports formats like:
            - https://www.youtube.com/watch?v=VIDEO_ID
            - https://youtu.be/VIDEO_ID
            - Just the video ID (11 characters)
        language: Preferred language code (e.g., "en", "es", "fr").
            If not specified, returns the first available transcript.

    Returns:
        A dictionary with status, transcript text, and metadata.
    """
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
        YouTubeTranscriptApi,
    )

    # Extract video ID from URL
    video_id = _extract_video_id(video_url)
    if not video_id:
        return {
            "status": "error",
            "message": f"Could not extract video ID from URL: {video_url}",
        }

    try:
        # Create API instance and get transcript list
        ytt_api = YouTubeTranscriptApi()
        transcript_list = ytt_api.list(video_id)

        # Find the appropriate transcript
        if language:
            transcript = transcript_list.find_transcript([language])
        else:
            # Get first available transcript
            transcript = next(iter(transcript_list))

        # Fetch the actual transcript data
        fetched = transcript.fetch()
        entries = fetched.to_raw_data()

        # Combine transcript entries into full text
        full_text = " ".join(entry["text"] for entry in entries)

        # Get metadata
        total_duration = sum(entry.get("duration", 0) for entry in entries)

        logger.info(
            f"Retrieved transcript for video {video_id}: {len(full_text)} chars"
        )

        return {
            "status": "success",
            "video_id": video_id,
            "transcript": full_text,
            "entry_count": len(entries),
            "duration_seconds": int(total_duration),
            "duration_minutes": round(total_duration / 60, 1),
            "language": transcript.language_code,
            "language_name": transcript.language,
            "is_generated": transcript.is_generated,
            "message": f"Retrieved transcript ({len(full_text)} characters, "
            f"{round(total_duration / 60, 1)} minutes)",
        }

    except VideoUnavailable:
        return {
            "status": "error",
            "message": f"Video {video_id} is unavailable or does not exist.",
        }
    except TranscriptsDisabled:
        return {
            "status": "error",
            "message": f"Transcripts are disabled for video {video_id}.",
        }
    except NoTranscriptFound:
        return {
            "status": "error",
            "message": f"No transcript found for video {video_id}"
            + (f" in language '{language}'." if language else "."),
        }
    except StopIteration:
        return {
            "status": "error",
            "message": f"No transcripts available for video {video_id}.",
        }
    except Exception as e:
        logger.exception(f"Failed to get transcript for video {video_id}")
        return {
            "status": "error",
            "message": f"Failed to retrieve transcript: {e}",
        }


# ============================================================================
# CONTEXT FILE TOOLS (Secure file operations for .context/ directory)
# ============================================================================

# Context directory is relative to project root
_CONTEXT_DIR = Path(__file__).parent.parent.parent / ".context"


def _validate_context_filename(filename: str) -> Path:
    """Validate and resolve a filename within the .context/ directory.

    Args:
        filename: The filename to validate (e.g., "USER.md").

    Returns:
        The resolved absolute path within .context/.

    Raises:
        ValueError: If the filename is invalid or attempts path traversal.
    """
    # Sanitize filename: no path separators, no parent directory references
    if not filename:
        raise ValueError("Filename cannot be empty")

    # Normalize and check for path traversal
    normalized = filename.replace("\\", "/").strip("/")
    if ".." in normalized or "/" in normalized:
        raise ValueError(
            f"Invalid filename '{filename}': path separators and '..' not allowed"
        )

    # Resolve the full path
    full_path = (_CONTEXT_DIR / normalized).resolve()

    # Ensure the resolved path is within the context directory
    try:
        full_path.relative_to(_CONTEXT_DIR.resolve())
    except ValueError:
        raise ValueError(
            f"Invalid filename '{filename}': must be within .context/ directory"
        ) from None

    return full_path


def read_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
) -> dict[str, Any]:
    """Read a file from the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to read (e.g., "USER.md", "IDENTITY.md").

    Returns:
        A dictionary with status and file contents or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    if not file_path.exists():
        return {"status": "error", "message": f"File '{filename}' not found."}

    try:
        content = file_path.read_text(encoding="utf-8")
        return {
            "status": "success",
            "filename": filename,
            "content": content,
            "path": str(file_path),
        }
    except Exception as e:
        logger.exception("Failed to read context file")
        return {"status": "error", "message": f"Failed to read file: {e}"}


def write_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
    content: str,
) -> dict[str, Any]:
    """Write content to a file in the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to write (e.g., "USER.md").
        content: The content to write to the file.

    Returns:
        A dictionary with status and confirmation or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    # Ensure the .context directory exists
    _CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_text(content, encoding="utf-8")
        return {
            "status": "success",
            "filename": filename,
            "message": f"Successfully wrote {len(content)} characters to '{filename}'.",
            "path": str(file_path),
        }
    except Exception as e:
        logger.exception("Failed to write context file")
        return {"status": "error", "message": f"Failed to write file: {e}"}


def delete_context_file(
    tool_context: ToolContext,  # noqa: ARG001
    filename: str,
) -> dict[str, Any]:
    """Delete a file from the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        filename: The filename to delete (e.g., "BOOTSTRAP.md").

    Returns:
        A dictionary with status and confirmation or error message.
    """
    try:
        file_path = _validate_context_filename(filename)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    if not file_path.exists():
        return {"status": "error", "message": f"File '{filename}' not found."}

    try:
        file_path.unlink()
        return {
            "status": "success",
            "filename": filename,
            "message": f"Successfully deleted '{filename}'.",
        }
    except Exception as e:
        logger.exception("Failed to delete context file")
        return {"status": "error", "message": f"Failed to delete file: {e}"}


def list_context_files(
    tool_context: ToolContext,  # noqa: ARG001
) -> dict[str, Any]:
    """List all files in the .context/ directory.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).

    Returns:
        A dictionary with status and list of files or error message.
    """
    if not _CONTEXT_DIR.exists():
        return {
            "status": "success",
            "files": [],
            "message": "No .context/ directory found.",
        }

    try:
        files: list[dict[str, int | str]] = [
            {"name": f.name, "size": f.stat().st_size}
            for f in _CONTEXT_DIR.iterdir()
            if f.is_file() and not f.name.startswith(".")
        ]
        files.sort(key=lambda x: str(x["name"]))
        return {
            "status": "success",
            "files": files,
            "count": len(files),
            "message": f"Found {len(files)} file(s) in .context/ directory.",
        }
    except Exception as e:
        logger.exception("Failed to list context files")
        return {"status": "error", "message": f"Failed to list files: {e}"}
