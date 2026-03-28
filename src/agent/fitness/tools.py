"""ADK tools for fitness tracking (calories and workouts)."""

import logging
from datetime import datetime
from typing import Any

from google.adk.tools import ToolContext

from ..utils.app_timezone import get_app_timezone
from . import CalorieEntry, ExerciseType, MealType, WorkoutEntry, get_fitness_storage

logger = logging.getLogger(__name__)


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


__all__ = [
    "add_calories",
    "delete_fitness_entry",
    "get_calorie_stats",
    "get_workout_stats",
    "list_calories",
    "list_workouts",
    "log_workout",
]
