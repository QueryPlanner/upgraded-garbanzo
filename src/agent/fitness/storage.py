"""Persistent fitness storage backed by SQLite via aiosqlite.

A single ``aiosqlite`` connection is opened on the first call to
``initialize()`` and reused for every subsequent operation.  This eliminates
the per-call overhead of opening/closing a connection and removes the need
to offload work to a thread-pool executor.

The database file lives inside the agent data directory, which is mounted
as a Docker named volume (``agent_data``). Named volumes survive
``docker compose up -d`` redeploys, so data is never lost during CI/CD.

⚠️  Running ``docker compose down -v`` WILL destroy the volume and all data.
    Use ``docker compose down`` (without -v) to stop without data loss.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from ..utils.config import get_data_dir
from .models import CalorieEntry, ExerciseType, MealType, WorkoutEntry

logger = logging.getLogger(__name__)


def _get_default_db_path() -> Path:
    return get_data_dir() / "fitness.db"


class FitnessStorage:
    """Storage for fitness data using a persistent aiosqlite connection."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize fitness storage.

        Args:
            db_path: Override the database file path. When None (default),
                uses ``fitness.db`` inside the agent data directory.
                Pass an explicit path in tests to use a temp file.
        """
        self._db_path = db_path or _get_default_db_path()
        self._lock = asyncio.Lock()
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        return self._db_path

    async def initialize(self) -> None:
        """Open the connection and create schema if needed (idempotent)."""
        async with self._lock:
            if self._conn is not None:
                return
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = await aiosqlite.connect(self._db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await self._create_tables(conn)
            self._conn = conn
            logger.info("Fitness storage initialized at %s", self._db_path)

    async def close(self) -> None:
        """Close the underlying database connection."""
        async with self._lock:
            if self._conn is not None:
                await self._conn.close()
                self._conn = None

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Fitness storage is not initialized")
        return self._conn

    async def _create_tables(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calories (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                food_item   TEXT    NOT NULL,
                calories    INTEGER NOT NULL,
                protein     REAL,
                carbs       REAL,
                fat         REAL,
                meal_type   TEXT    NOT NULL DEFAULT 'snack',
                notes       TEXT,
                created_at  TEXT    NOT NULL
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_calories_user_date
            ON calories (user_id, date)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS workouts (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           TEXT    NOT NULL,
                date              TEXT    NOT NULL,
                exercise_type     TEXT    NOT NULL DEFAULT 'other',
                exercise_name     TEXT    NOT NULL,
                duration_minutes  INTEGER,
                set_number        INTEGER,
                reps              INTEGER,
                weight            REAL,
                distance_km       REAL,
                notes             TEXT,
                created_at        TEXT    NOT NULL
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workouts_user_date
            ON workouts (user_id, date)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_workouts_exercise
            ON workouts (user_id, exercise_name)
        """)
        await conn.commit()

    # ------------------------------------------------------------------
    # Calorie entries
    # ------------------------------------------------------------------

    async def add_calorie_entry(self, entry: CalorieEntry) -> int:
        """Insert a calorie entry and return its new row ID."""
        await self.initialize()
        conn = self._require_conn()
        cursor = await conn.execute(
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
        await conn.commit()
        eid = cursor.lastrowid or 0
        logger.info(
            "Added calorie entry %s for user %s: %s (%s cal)",
            eid,
            entry.user_id,
            entry.food_item,
            entry.calories,
        )
        return eid

    async def get_calorie_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[CalorieEntry]:
        """Return calorie entries for a user, with optional date range filter."""
        await self.initialize()
        conn = self._require_conn()

        conditions = ["user_id = ?"]
        params: list[Any] = [user_id]
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)
        query = (
            "SELECT id, user_id, date, food_item, calories, protein, carbs, fat, "
            f"meal_type, notes, created_at FROM calories WHERE {where} "  # noqa: S608
            "ORDER BY date DESC, created_at DESC"
        )
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_calorie_entry(r) for r in rows]

    async def get_calorie_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregated calorie statistics for a user."""
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

    # ------------------------------------------------------------------
    # Workout entries
    # ------------------------------------------------------------------

    async def add_workout_entry(self, entry: WorkoutEntry) -> int:
        """Insert a workout entry and return its new row ID."""
        await self.initialize()
        conn = self._require_conn()
        cursor = await conn.execute(
            """
            INSERT INTO workouts
                (user_id, date, exercise_type, exercise_name, duration_minutes,
                 set_number, reps, weight, distance_km, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.user_id,
                entry.date,
                entry.exercise_type.value,
                entry.exercise_name,
                entry.duration_minutes,
                entry.set,
                entry.reps,
                entry.weight,
                entry.distance_km,
                entry.notes,
                entry.created_at,
            ),
        )
        await conn.commit()
        eid = cursor.lastrowid or 0
        logger.info(
            "Added workout entry %s for user %s: %s",
            eid,
            entry.user_id,
            entry.exercise_name,
        )
        return eid

    async def get_workout_entries(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        exercise_type: str | None = None,
    ) -> list[WorkoutEntry]:
        """Return workout entries for a user, with optional filters."""
        await self.initialize()
        conn = self._require_conn()

        conditions = ["user_id = ?"]
        params: list[Any] = [user_id]
        if start_date:
            conditions.append("date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            params.append(end_date)
        if exercise_type:
            conditions.append("exercise_type = ?")
            params.append(exercise_type)

        where = " AND ".join(conditions)
        query = (
            "SELECT id, user_id, date, exercise_type, exercise_name, "
            "duration_minutes, set_number, reps, weight, distance_km, notes, "
            f"created_at FROM workouts WHERE {where} "  # noqa: S608
            "ORDER BY date DESC, created_at DESC"
        )
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_workout_entry(r) for r in rows]

    async def get_workout_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregated workout statistics for a user."""
        entries = await self.get_workout_entries(user_id, start_date, end_date)

        if not entries:
            return {
                "total_workouts": 0,
                "total_minutes": 0,
                "exercise_types": {},
                "personal_records": [],
            }

        total_minutes = sum(e.duration_minutes or 0 for e in entries)
        type_counts: dict[str, int] = {}
        for entry in entries:
            et = entry.exercise_type.value
            type_counts[et] = type_counts.get(et, 0) + 1

        strength_entries = [e for e in entries if e.weight is not None and e.weight > 0]
        prs: list[dict[str, Any]] = []
        if strength_entries:
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

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_entry(self, entry_type: str, entry_id: int, user_id: str) -> bool:
        """Delete a calorie or workout entry owned by the given user.

        Args:
            entry_type: Either ``"calorie"`` or ``"workout"``.
            entry_id: Row ID of the entry to delete.
            user_id: Owner check — only deletes if the row belongs to this user.

        Returns:
            True if a row was deleted, False if not found or wrong user.
        """
        if entry_type not in ("calorie", "workout"):
            return False
        await self.initialize()
        conn = self._require_conn()
        table = "calories" if entry_type == "calorie" else "workouts"
        cursor = await conn.execute(
            f"DELETE FROM {table} WHERE id = ? AND user_id = ?",  # noqa: S608
            (entry_id, user_id),
        )
        await conn.commit()
        deleted = (cursor.rowcount or 0) > 0
        if deleted:
            logger.info("Deleted %s entry %s", entry_type, entry_id)
        return deleted

    # ------------------------------------------------------------------
    # Row mappers
    # ------------------------------------------------------------------

    def _row_to_calorie_entry(self, row: aiosqlite.Row) -> CalorieEntry:
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

    def _row_to_workout_entry(self, row: aiosqlite.Row) -> WorkoutEntry:
        return WorkoutEntry(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            exercise_type=ExerciseType(row["exercise_type"]),
            exercise_name=row["exercise_name"],
            duration_minutes=row["duration_minutes"],
            set=row["set_number"],
            reps=row["reps"],
            weight=row["weight"],
            distance_km=row["distance_km"],
            notes=row["notes"],
            created_at=row["created_at"],
        )


_storage: FitnessStorage | None = None


def get_fitness_storage() -> FitnessStorage:
    """Return the process-wide singleton FitnessStorage instance."""
    global _storage
    if _storage is None:
        _storage = FitnessStorage()
    return _storage


async def close_shared_fitness_storage() -> None:
    """Close the singleton connection and clear the global instance.

    aiosqlite keeps a non-daemon worker thread per open connection. Call this
    before process exit (e.g. end of pytest) so the interpreter is not blocked
    in ``threading._shutdown()``.
    """
    global _storage
    if _storage is None:
        return
    await _storage.close()
    _storage = None
