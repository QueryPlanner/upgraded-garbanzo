"""Persistent fitness storage backed by Postgres."""

import asyncio
import logging
from typing import Any, cast

import asyncpg  # type: ignore[import-untyped]

from ..utils.pg_app_pool import get_shared_app_pool, postgres_dsn_from_environment
from .models import CalorieEntry, ExerciseType, MealType, WorkoutEntry

logger = logging.getLogger(__name__)


def _as_row_list(rows: object) -> list[Any]:
    """Help mypy treat asyncpg fetch results as a list (asyncpg ships without stubs)."""
    return cast(list[Any], rows)


class FitnessStorage:
    """Storage for fitness data using Postgres."""

    def __init__(self) -> None:
        """Initialize fitness storage."""
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()
        self._initialized = False

    def _require_pool(self) -> asyncpg.Pool:
        """Return the initialized Postgres pool or raise a clear error."""
        pool = self._pool
        if pool is None:
            msg = "Postgres pool is not initialized"
            raise RuntimeError(msg)
        return pool

    async def _fetch_calorie_rows_postgres(
        self,
        pool: asyncpg.Pool,
        user_id: str,
        start_date: str | None,
        end_date: str | None,
    ) -> list[Any]:
        """Fetch calorie rows from Postgres with optional date filters."""
        sel = (
            "SELECT id, user_id, date, food_item, calories, protein, carbs, fat, "
            "meal_type, notes, created_at FROM agent_calories"
        )
        order = " ORDER BY date DESC, created_at DESC"

        conditions = ["user_id = $1"]
        params: list[str] = [user_id]
        param_idx = 2

        if start_date:
            conditions.append(f"date >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            conditions.append(f"date <= ${param_idx}")
            params.append(end_date)

        where_clause = " AND ".join(conditions)
        query = f"{sel} WHERE {where_clause}{order}"
        return _as_row_list(await pool.fetch(query, *params))

    async def _fetch_workout_rows_postgres(
        self,
        pool: asyncpg.Pool,
        user_id: str,
        start_date: str | None,
        end_date: str | None,
        exercise_type: str | None,
    ) -> list[Any]:
        """Fetch workout rows from Postgres with optional filters."""
        sel = (
            "SELECT id, user_id, date, exercise_type, exercise_name, "
            'duration_minutes, "set", reps, weight, distance_km, notes, '
            "created_at "
            "FROM agent_workouts"
        )
        order = " ORDER BY date DESC, created_at DESC"

        conditions = ["user_id = $1"]
        params: list[str | None] = [user_id]
        param_idx = 2

        if start_date:
            conditions.append(f"date >= ${param_idx}")
            params.append(start_date)
            param_idx += 1
        if end_date:
            conditions.append(f"date <= ${param_idx}")
            params.append(end_date)
            param_idx += 1
        if exercise_type:
            conditions.append(f"exercise_type = ${param_idx}")
            params.append(exercise_type)

        where_clause = " AND ".join(conditions)
        query = f"{sel} WHERE {where_clause}{order}"
        return _as_row_list(await pool.fetch(query, *params))

    async def initialize(self) -> None:
        async with self._lock:
            if self._initialized:
                return

            dsn = postgres_dsn_from_environment()
            if dsn is None:
                msg = "Fitness storage requires DATABASE_URL to point to Postgres."
                raise RuntimeError(msg)

            pool = await get_shared_app_pool()
            if pool is None:
                msg = "Postgres was expected but pool could not be created"
                raise RuntimeError(msg)

            self._pool = pool
            await self._create_tables_postgres()
            logger.info(
                "Fitness storage initialized (Postgres tables agent_calories, "
                "agent_workouts)"
            )

            self._initialized = True

    async def _create_tables_postgres(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_calories (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    food_item TEXT NOT NULL,
                    calories INTEGER NOT NULL,
                    protein DOUBLE PRECISION,
                    carbs DOUBLE PRECISION,
                    fat DOUBLE PRECISION,
                    meal_type TEXT NOT NULL DEFAULT 'snack',
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_calories_user_date
                ON agent_calories (user_id, date)
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_workouts (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    exercise_type TEXT NOT NULL DEFAULT 'other',
                    exercise_name TEXT NOT NULL,
                    duration_minutes INTEGER,
                    "set" INTEGER,
                    reps INTEGER,
                    weight DOUBLE PRECISION,
                    distance_km DOUBLE PRECISION,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            await conn.execute("""
                ALTER TABLE agent_workouts
                ADD COLUMN IF NOT EXISTS "set" INTEGER
            """)
            await conn.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'agent_workouts'
                          AND column_name = 'set_number'
                    ) THEN
                        EXECUTE '
                            UPDATE agent_workouts
                            SET "set" = COALESCE("set", set_number)
                            WHERE set_number IS NOT NULL
                        ';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'agent_workouts'
                          AND column_name = 'sets'
                    ) THEN
                        EXECUTE '
                            UPDATE agent_workouts
                            SET "set" = COALESCE("set", sets)
                            WHERE sets IS NOT NULL
                        ';
                    END IF;
                END
                $$;
            """)
            await conn.execute("""
                ALTER TABLE agent_workouts
                DROP COLUMN IF EXISTS set_number
            """)
            await conn.execute("""
                ALTER TABLE agent_workouts
                DROP COLUMN IF EXISTS sets
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_workouts_user_date
                ON agent_workouts (user_id, date)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_workouts_exercise
                ON agent_workouts (user_id, exercise_name)
            """)

    async def add_calorie_entry(self, entry: CalorieEntry) -> int:
        """Add a new calorie entry to the database.

        Args:
            entry: The calorie entry to add.

        Returns:
            The ID of the newly created entry.
        """
        await self.initialize()
        pool = self._require_pool()
        entry_id = await pool.fetchval(
            """
            INSERT INTO agent_calories
            (user_id, date, food_item, calories, protein, carbs, fat,
             meal_type, notes, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
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
        )
        eid = int(entry_id) if entry_id is not None else 0

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
        await self.initialize()
        pool = self._require_pool()
        rows = await self._fetch_calorie_rows_postgres(
            pool, user_id, start_date, end_date
        )
        return [self._record_to_calorie_entry(r) for r in rows]

    async def get_calorie_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
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

    async def add_workout_entry(self, entry: WorkoutEntry) -> int:
        """Add a new workout entry to the database.

        Args:
            entry: The workout entry to add.

        Returns:
            The ID of the newly created entry.
        """
        await self.initialize()
        pool = self._require_pool()
        entry_id = await pool.fetchval(
            """
            INSERT INTO agent_workouts
            (user_id, date, exercise_type, exercise_name, duration_minutes,
             "set", reps, weight, distance_km, notes, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING id
            """,
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
        )
        eid = int(entry_id) if entry_id is not None else 0

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
        await self.initialize()
        pool = self._require_pool()
        rows = await self._fetch_workout_rows_postgres(
            pool, user_id, start_date, end_date, exercise_type
        )
        return [self._record_to_workout_entry(r) for r in rows]

    async def get_workout_stats(
        self,
        user_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
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

        prs: list[dict[str, Any]] = []
        strength_entries = [e for e in entries if e.weight is not None and e.weight > 0]
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

        if entry_type not in ("calorie", "workout"):
            return False

        pool = self._require_pool()
        if entry_type == "calorie":
            row = await pool.fetchrow(
                (
                    "DELETE FROM agent_calories "
                    "WHERE id = $1 AND user_id = $2 RETURNING id"
                ),
                entry_id,
                user_id,
            )
        else:
            row = await pool.fetchrow(
                (
                    "DELETE FROM agent_workouts "
                    "WHERE id = $1 AND user_id = $2 RETURNING id"
                ),
                entry_id,
                user_id,
            )
        deleted = row is not None

        if deleted:
            logger.info("Deleted %s entry %s", entry_type, entry_id)
        return deleted

    def _record_to_calorie_entry(self, row: asyncpg.Record) -> CalorieEntry:
        """Convert an asyncpg record to a CalorieEntry object."""
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

    def _record_to_workout_entry(self, row: asyncpg.Record) -> WorkoutEntry:
        """Convert an asyncpg record to a WorkoutEntry object."""
        return WorkoutEntry(
            id=row["id"],
            user_id=row["user_id"],
            date=row["date"],
            exercise_type=ExerciseType(row["exercise_type"]),
            exercise_name=row["exercise_name"],
            duration_minutes=row["duration_minutes"],
            set=row["set"],
            reps=row["reps"],
            weight=row["weight"],
            distance_km=row["distance_km"],
            notes=row["notes"],
            created_at=row["created_at"],
        )


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
