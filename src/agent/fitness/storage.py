"""SQLite-based storage for fitness tracking (calories and workouts).

This module provides persistent storage for fitness data that can survive
agent restarts. Uses a single database with two tables.
"""

import asyncio
import logging
import sqlite3
from pathlib import Path
from typing import Any

from ..utils.config import get_data_dir
from .models import CalorieEntry, ExerciseType, MealType, WorkoutEntry

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    """Get the default database path in the agent data directory."""
    return get_data_dir() / "fitness.db"


class FitnessStorage:
    """SQLite-based storage for fitness data.

    This class provides CRUD operations for calories and workouts with proper
    async handling using a dedicated thread.

    Attributes:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the fitness storage.

        Args:
            db_path: Optional path to SQLite database file.
                Defaults to <agent_data_dir>/fitness.db
        """
        self.db_path = db_path or _get_default_db_path()
        self._lock = asyncio.Lock()
        self._initialized = False

    def _ensure_db_dir(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection with proper configuration.

        Returns:
            A configured SQLite connection.
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    async def initialize(self) -> None:
        """Initialize the database schema.

        Creates the calories and workouts tables if they don't exist.
        """
        async with self._lock:
            if self._initialized:
                return

            self._ensure_db_dir()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._create_tables)
            self._initialized = True
            logger.info(f"Fitness storage initialized at {self.db_path}")

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        conn = self._get_connection()
        try:
            # Calories table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS calories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    food_item TEXT NOT NULL,
                    calories INTEGER NOT NULL,
                    protein REAL,
                    carbs REAL,
                    fat REAL,
                    meal_type TEXT NOT NULL DEFAULT 'snack',
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_calories_user_date
                ON calories(user_id, date)
            """)

            # Workouts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    exercise_type TEXT NOT NULL DEFAULT 'other',
                    exercise_name TEXT NOT NULL,
                    duration_minutes INTEGER,
                    sets INTEGER,
                    reps INTEGER,
                    weight REAL,
                    distance_km REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workouts_user_date
                ON workouts(user_id, date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workouts_exercise
                ON workouts(user_id, exercise_name)
            """)
            conn.commit()
        finally:
            conn.close()

    # ==================== CALORIE OPERATIONS ====================

    async def add_calorie_entry(self, entry: CalorieEntry) -> int:
        """Add a new calorie entry to the database.

        Args:
            entry: The calorie entry to add.

        Returns:
            The ID of the newly created entry.
        """
        await self.initialize()

        loop = asyncio.get_running_loop()
        entry_id = await loop.run_in_executor(None, self._add_calorie_entry_sync, entry)
        logger.info(
            f"Added calorie entry {entry_id} for user {entry.user_id}: "
            f"{entry.food_item} ({entry.calories} cal)"
        )
        return entry_id

    def _add_calorie_entry_sync(self, entry: CalorieEntry) -> int:
        """Synchronous implementation of add_calorie_entry."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO calories
                (user_id, date, food_item, calories, protein, carbs, fat,
                 meal_type, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.user_id,
                    entry.date,
                    entry.food_item,
                    entry.calories,
                    entry.protein,
                    entry.carbs,
                    entry.fat,
                    entry.meal_type.value,
                    entry.notes,
                    entry.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    async def get_calorie_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[CalorieEntry]:
        """Get calorie entries for a user within a date range.

        Args:
            user_id: The user ID.
            start_date: Optional start date (YYYY-MM-DD).
            end_date: Optional end date (YYYY-MM-DD).

        Returns:
            List of calorie entries.
        """
        await self.initialize()

        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None, self._get_calorie_entries_sync, user_id, start_date, end_date
        )
        return entries

    def _get_calorie_entries_sync(
        self,
        user_id: str,
        start_date: str | None,
        end_date: str | None,
    ) -> list[CalorieEntry]:
        """Synchronous implementation of get_calorie_entries."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM calories WHERE user_id = ?"
            params: list[Any] = [user_id]

            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)

            query += " ORDER BY date DESC, created_at DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_calorie_entry(row) for row in rows]
        finally:
            conn.close()

    async def get_calorie_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get calorie statistics for a user.

        Args:
            user_id: The user ID.
            start_date: Optional start date (YYYY-MM-DD).
            end_date: Optional end date (YYYY-MM-DD).

        Returns:
            Dictionary with statistics including totals and averages.
        """
        entries = await self.get_calorie_entries(user_id, start_date, end_date)

        if not entries:
            return {
                "total_entries": 0,
                "total_calories": 0,
                "avg_daily_calories": 0,
                "avg_protein": 0,
                "avg_carbs": 0,
                "avg_fat": 0,
            }

        total_calories = sum(e.calories for e in entries)
        total_protein = sum(e.protein or 0 for e in entries)
        total_carbs = sum(e.carbs or 0 for e in entries)
        total_fat = sum(e.fat or 0 for e in entries)

        # Get unique days
        unique_days = {e.date for e in entries}
        num_days = len(unique_days)

        return {
            "total_entries": len(entries),
            "total_calories": total_calories,
            "avg_daily_calories": round(total_calories / num_days, 1)
            if num_days > 0
            else 0,
            "avg_protein": round(total_protein / len(entries), 1),
            "avg_carbs": round(total_carbs / len(entries), 1),
            "avg_fat": round(total_fat / len(entries), 1),
            "days_tracked": num_days,
        }

    # ==================== WORKOUT OPERATIONS ====================

    async def add_workout_entry(self, entry: WorkoutEntry) -> int:
        """Add a new workout entry to the database.

        Args:
            entry: The workout entry to add.

        Returns:
            The ID of the newly created entry.
        """
        await self.initialize()

        loop = asyncio.get_running_loop()
        entry_id = await loop.run_in_executor(None, self._add_workout_entry_sync, entry)
        logger.info(
            f"Added workout entry {entry_id} for user {entry.user_id}: "
            f"{entry.exercise_name}"
        )
        return entry_id

    def _add_workout_entry_sync(self, entry: WorkoutEntry) -> int:
        """Synchronous implementation of add_workout_entry."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO workouts
                (user_id, date, exercise_type, exercise_name, duration_minutes,
                 sets, reps, weight, distance_km, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.user_id,
                    entry.date,
                    entry.exercise_type.value,
                    entry.exercise_name,
                    entry.duration_minutes,
                    entry.sets,
                    entry.reps,
                    entry.weight,
                    entry.distance_km,
                    entry.notes,
                    entry.created_at,
                ),
            )
            conn.commit()
            return cursor.lastrowid or 0
        finally:
            conn.close()

    async def get_workout_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        exercise_type: str | None = None,
    ) -> list[WorkoutEntry]:
        """Get workout entries for a user within a date range.

        Args:
            user_id: The user ID.
            start_date: Optional start date (YYYY-MM-DD).
            end_date: Optional end date (YYYY-MM-DD).
            exercise_type: Optional filter by exercise type.

        Returns:
            List of workout entries.
        """
        await self.initialize()

        loop = asyncio.get_running_loop()
        entries = await loop.run_in_executor(
            None,
            self._get_workout_entries_sync,
            user_id,
            start_date,
            end_date,
            exercise_type,
        )
        return entries

    def _get_workout_entries_sync(
        self,
        user_id: str,
        start_date: str | None,
        end_date: str | None,
        exercise_type: str | None,
    ) -> list[WorkoutEntry]:
        """Synchronous implementation of get_workout_entries."""
        conn = self._get_connection()
        try:
            query = "SELECT * FROM workouts WHERE user_id = ?"
            params: list[Any] = [user_id]

            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            if exercise_type:
                query += " AND exercise_type = ?"
                params.append(exercise_type)

            query += " ORDER BY date DESC, created_at DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_workout_entry(row) for row in rows]
        finally:
            conn.close()

    async def get_workout_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Get workout statistics for a user.

        Args:
            user_id: The user ID.
            start_date: Optional start date (YYYY-MM-DD).
            end_date: Optional end date (YYYY-MM-DD).

        Returns:
            Dictionary with statistics including frequency and PRs.
        """
        entries = await self.get_workout_entries(user_id, start_date, end_date)

        if not entries:
            return {
                "total_workouts": 0,
                "total_minutes": 0,
                "exercise_types": {},
                "personal_records": [],
            }

        total_minutes = sum(e.duration_minutes or 0 for e in entries)

        # Count by exercise type
        type_counts: dict[str, int] = {}
        for entry in entries:
            et = entry.exercise_type.value
            type_counts[et] = type_counts.get(et, 0) + 1

        # Find personal records (highest weight for strength exercises)
        prs: list[dict[str, Any]] = []
        strength_entries = [e for e in entries if e.weight is not None and e.weight > 0]
        if strength_entries:
            # Group by exercise name and find max weight
            exercise_max: dict[str, float] = {}
            for e in strength_entries:
                name = e.exercise_name.lower()
                if name not in exercise_max or (e.weight or 0) > exercise_max[name]:
                    exercise_max[name] = e.weight or 0

            prs = [
                {"exercise": name.title(), "weight_kg": weight}
                for name, weight in sorted(
                    exercise_max.items(), key=lambda x: x[1], reverse=True
                )[:5]
            ]

        unique_days = {e.date for e in entries}

        return {
            "total_workouts": len(entries),
            "total_minutes": total_minutes,
            "days_active": len(unique_days),
            "exercise_types": type_counts,
            "personal_records": prs,
        }

    # ==================== DELETE OPERATIONS ====================

    async def delete_entry(self, entry_type: str, entry_id: int, user_id: str) -> bool:
        """Delete a calorie or workout entry.

        Args:
            entry_type: Either "calorie" or "workout".
            entry_id: The ID of the entry to delete.
            user_id: The user ID (for authorization check).

        Returns:
            True if deleted, False if not found or not authorized.
        """
        await self.initialize()

        loop = asyncio.get_running_loop()
        deleted = await loop.run_in_executor(
            None, self._delete_entry_sync, entry_type, entry_id, user_id
        )
        if deleted:
            logger.info(f"Deleted {entry_type} entry {entry_id}")
        return deleted

    def _delete_entry_sync(self, entry_type: str, entry_id: int, user_id: str) -> bool:
        """Synchronous implementation of delete_entry."""
        # Validate entry_type to prevent SQL injection
        valid_tables = {"calorie": "calories", "workout": "workouts"}
        if entry_type not in valid_tables:
            return False
        table = valid_tables[entry_type]

        conn = self._get_connection()
        try:
            # Table name is validated against whitelist above
            query = f"DELETE FROM {table} WHERE id = ? AND user_id = ?"  # noqa: S608
            cursor = conn.execute(query, (entry_id, user_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # ==================== HELPER METHODS ====================

    def _row_to_calorie_entry(self, row: sqlite3.Row) -> CalorieEntry:
        """Convert a database row to a CalorieEntry object."""
        return CalorieEntry(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            food_item=row["food_item"],
            calories=row["calories"],
            protein=row["protein"],
            carbs=row["carbs"],
            fat=row["fat"],
            meal_type=MealType(row["meal_type"]),
            notes=row["notes"],
            created_at=row["created_at"],
        )

    def _row_to_workout_entry(self, row: sqlite3.Row) -> WorkoutEntry:
        """Convert a database row to a WorkoutEntry object."""
        return WorkoutEntry(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            exercise_type=ExerciseType(row["exercise_type"]),
            exercise_name=row["exercise_name"],
            duration_minutes=row["duration_minutes"],
            sets=row["sets"],
            reps=row["reps"],
            weight=row["weight"],
            distance_km=row["distance_km"],
            notes=row["notes"],
            created_at=row["created_at"],
        )


# Global storage instance
_storage: FitnessStorage | None = None


def get_fitness_storage() -> FitnessStorage:
    """Get the global fitness storage instance.

    Returns:
        The global FitnessStorage instance.
    """
    global _storage
    if _storage is None:
        _storage = FitnessStorage()
    return _storage
