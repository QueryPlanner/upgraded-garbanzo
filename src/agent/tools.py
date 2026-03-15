"""Custom tools for the LLM agent."""

import logging
import subprocess
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
    """Get today's date in YYYY-MM-DD format."""
    return datetime.now(UTC).strftime("%Y-%m-%d")


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
        calories: Number of calories.
        meal_type: Type of meal (breakfast, lunch, dinner, snack).
        protein: Grams of protein (optional).
        carbs: Grams of carbohydrates (optional).
        fat: Grams of fat (optional).
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
        created_at=datetime.now(UTC).isoformat(),
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
    sets: int | None = None,
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
        sets: Number of sets (for strength training).
        reps: Reps per set (for strength training).
        weight: Weight in kg (for strength training).
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
        sets=sets,
        reps=reps,
        weight=weight,
        distance_km=distance_km,
        notes=notes,
        created_at=datetime.now(UTC).isoformat(),
    )

    try:
        storage = get_fitness_storage()
        entry_id = await storage.add_workout_entry(entry)
        logger.info(f"Added workout entry {entry_id} for user {user_id}")

        details = []
        if sets and reps:
            details.append(f"{sets}x{reps}")
        if weight:
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
                "sets": e.sets,
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
# BASH TOOL
# ============================================================================


def execute_bash(
    tool_context: ToolContext,
    command: str,
    timeout: int = 30,
) -> dict[str, Any]:
    """Execute a bash command for file operations.

    Use this tool to read or edit context files in the .context/ directory.
    The working directory is the project root.

    Args:
        tool_context: ADK ToolContext (unused but required by ADK).
        command: The bash command to execute.
        timeout: Timeout in seconds (default: 30, max: 60).

    Returns:
        A dictionary with status, stdout, stderr, and return code.

    Note:
        This tool is intended for safe file operations on context files.
        Dangerous commands (rm -rf, sudo, etc.) are blocked.
    """
    # Safety checks
    dangerous_patterns = ["rm -rf", "sudo", "chmod 777", "> /dev/", "mkfs"]
    for pattern in dangerous_patterns:
        if pattern in command:
            return {
                "status": "error",
                "message": f"Blocked dangerous command pattern: {pattern}",
            }

    # Clamp timeout
    timeout = min(max(timeout, 1), 60)

    try:
        result = subprocess.run(  # noqa: S602 - shell=True needed for file ops
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=Path(__file__).parent.parent.parent,  # Project root
        )

        return {
            "status": "success" if result.returncode == 0 else "error",
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "command": command,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "message": f"Command timed out after {timeout} seconds.",
        }
    except Exception as e:
        logger.exception("Failed to execute bash command")
        return {"status": "error", "message": f"Failed to execute command: {e}"}
