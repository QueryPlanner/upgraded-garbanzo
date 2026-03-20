"""Tests for SQLite-backed FitnessStorage."""

import tempfile
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent.fitness import (
    CalorieEntry,
    ExerciseType,
    FitnessStorage,
    MealType,
    WorkoutEntry,
    get_fitness_storage,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture
async def storage() -> AsyncGenerator[FitnessStorage]:
    """FitnessStorage backed by a temporary SQLite file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    store = FitnessStorage(db_path=db_path)
    await store.initialize()
    yield store

    await store.close()
    db_path.unlink(missing_ok=True)


class TestFitnessStorageInit:
    """Initialization behaviour."""

    @pytest.mark.asyncio
    async def test_initialize_creates_db_file(self, storage: FitnessStorage) -> None:
        assert storage._conn is not None
        assert storage.db_path.exists()

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, storage: FitnessStorage) -> None:
        """Calling initialize twice should not raise or open a second connection."""
        first_conn = storage._conn
        await storage.initialize()
        assert storage._conn is first_conn


class TestCalorieEntries:
    """CRUD tests for calorie entries."""

    @pytest.mark.asyncio
    async def test_add_and_retrieve_calorie_entry(
        self, storage: FitnessStorage
    ) -> None:
        entry = CalorieEntry(
            user_id="u1",
            date="2026-03-15",
            food_item="Eggs",
            calories=140,
            protein=12.0,
            meal_type=MealType.BREAKFAST,
            created_at=_now(),
        )
        eid = await storage.add_calorie_entry(entry)
        assert eid > 0

        rows = await storage.get_calorie_entries("u1")
        assert len(rows) == 1
        assert rows[0].food_item == "Eggs"
        assert rows[0].calories == 140

    @pytest.mark.asyncio
    async def test_calorie_entries_filtered_by_date(
        self, storage: FitnessStorage
    ) -> None:
        for date, item in [("2026-03-14", "Apple"), ("2026-03-15", "Banana")]:
            await storage.add_calorie_entry(
                CalorieEntry(
                    user_id="u1",
                    date=date,
                    food_item=item,
                    calories=80,
                    meal_type=MealType.SNACK,
                    created_at=_now(),
                )
            )

        rows = await storage.get_calorie_entries("u1", start_date="2026-03-15")
        assert len(rows) == 1
        assert rows[0].food_item == "Banana"

    @pytest.mark.asyncio
    async def test_calorie_entries_isolated_per_user(
        self, storage: FitnessStorage
    ) -> None:
        for user in ("u1", "u2"):
            await storage.add_calorie_entry(
                CalorieEntry(
                    user_id=user,
                    date="2026-03-15",
                    food_item="Rice",
                    calories=200,
                    meal_type=MealType.LUNCH,
                    created_at=_now(),
                )
            )

        assert len(await storage.get_calorie_entries("u1")) == 1
        assert len(await storage.get_calorie_entries("u2")) == 1

    @pytest.mark.asyncio
    async def test_calorie_stats(self, storage: FitnessStorage) -> None:
        for _ in range(3):
            await storage.add_calorie_entry(
                CalorieEntry(
                    user_id="u1",
                    date="2026-03-15",
                    food_item="Chicken",
                    calories=300,
                    protein=30.0,
                    carbs=0.0,
                    fat=10.0,
                    meal_type=MealType.DINNER,
                    created_at=_now(),
                )
            )

        stats = await storage.get_calorie_stats("u1")
        assert stats["total_entries"] == 3
        assert stats["total_calories"] == 900
        assert stats["days_tracked"] == 1

    @pytest.mark.asyncio
    async def test_calorie_stats_empty(self, storage: FitnessStorage) -> None:
        stats = await storage.get_calorie_stats("nobody")
        assert stats["total_calories"] == 0

    @pytest.mark.asyncio
    async def test_delete_calorie_entry(self, storage: FitnessStorage) -> None:
        eid = await storage.add_calorie_entry(
            CalorieEntry(
                user_id="u1",
                date="2026-03-15",
                food_item="Toast",
                calories=90,
                meal_type=MealType.BREAKFAST,
                created_at=_now(),
            )
        )
        assert await storage.delete_entry("calorie", eid, "u1") is True
        assert await storage.get_calorie_entries("u1") == []

    @pytest.mark.asyncio
    async def test_delete_calorie_wrong_user_is_rejected(
        self, storage: FitnessStorage
    ) -> None:
        eid = await storage.add_calorie_entry(
            CalorieEntry(
                user_id="u1",
                date="2026-03-15",
                food_item="Toast",
                calories=90,
                meal_type=MealType.BREAKFAST,
                created_at=_now(),
            )
        )
        assert await storage.delete_entry("calorie", eid, "u2") is False
        assert len(await storage.get_calorie_entries("u1")) == 1


class TestWorkoutEntries:
    """CRUD tests for workout entries."""

    @pytest.mark.asyncio
    async def test_add_and_retrieve_workout_entry(
        self, storage: FitnessStorage
    ) -> None:
        entry = WorkoutEntry(
            user_id="u1",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Bench Press",
            duration_minutes=45,
            set=2,
            reps=8,
            weight=100.0,
            created_at=_now(),
        )
        eid = await storage.add_workout_entry(entry)
        assert eid > 0

        rows = await storage.get_workout_entries("u1")
        assert len(rows) == 1
        assert rows[0].exercise_name == "Bench Press"
        assert rows[0].set == 2
        assert rows[0].weight == 100.0

    @pytest.mark.asyncio
    async def test_workout_entries_filtered_by_exercise_type(
        self, storage: FitnessStorage
    ) -> None:
        await storage.add_workout_entry(
            WorkoutEntry(
                user_id="u1",
                date="2026-03-15",
                exercise_type=ExerciseType.STRENGTH,
                exercise_name="Squat",
                created_at=_now(),
            )
        )
        await storage.add_workout_entry(
            WorkoutEntry(
                user_id="u1",
                date="2026-03-15",
                exercise_type=ExerciseType.CARDIO,
                exercise_name="Running",
                distance_km=5.0,
                created_at=_now(),
            )
        )

        strength = await storage.get_workout_entries("u1", exercise_type="strength")
        assert len(strength) == 1
        assert strength[0].exercise_name == "Squat"

    @pytest.mark.asyncio
    async def test_workout_stats(self, storage: FitnessStorage) -> None:
        await storage.add_workout_entry(
            WorkoutEntry(
                user_id="u1",
                date="2026-03-15",
                exercise_type=ExerciseType.STRENGTH,
                exercise_name="Deadlift",
                duration_minutes=60,
                weight=150.0,
                created_at=_now(),
            )
        )

        stats = await storage.get_workout_stats("u1")
        assert stats["total_workouts"] == 1
        assert stats["total_minutes"] == 60
        assert stats["personal_records"][0]["exercise"] == "Deadlift"
        assert stats["personal_records"][0]["weight_kg"] == 150.0

    @pytest.mark.asyncio
    async def test_workout_stats_uses_set_field(self, storage: FitnessStorage) -> None:
        """Verify the set field round-trips correctly through SQLite."""
        entry = WorkoutEntry(
            user_id="u1",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Bench Press",
            duration_minutes=45,
            set=3,
            reps=10,
            weight=80.0,
            created_at=_now(),
        )
        await storage.add_workout_entry(entry)

        rows = await storage.get_workout_entries("u1")
        assert rows[0].set == 3

    @pytest.mark.asyncio
    async def test_workout_stats_empty(self, storage: FitnessStorage) -> None:
        stats = await storage.get_workout_stats("nobody")
        assert stats["total_workouts"] == 0
        assert stats["personal_records"] == []

    @pytest.mark.asyncio
    async def test_delete_workout_entry(self, storage: FitnessStorage) -> None:
        eid = await storage.add_workout_entry(
            WorkoutEntry(
                user_id="u1",
                date="2026-03-15",
                exercise_type=ExerciseType.CARDIO,
                exercise_name="Cycling",
                created_at=_now(),
            )
        )
        assert await storage.delete_entry("workout", eid, "u1") is True
        assert await storage.get_workout_entries("u1") == []

    @pytest.mark.asyncio
    async def test_delete_invalid_type_returns_false(
        self, storage: FitnessStorage
    ) -> None:
        assert await storage.delete_entry("invalid", 1, "u1") is False


class TestGetFitnessStorage:
    """Global singleton behaviour."""

    def test_returns_fitness_storage_instance(self) -> None:
        from unittest.mock import patch

        with patch("agent.fitness.storage._storage", None):
            assert isinstance(get_fitness_storage(), FitnessStorage)

    def test_returns_same_instance_on_repeated_calls(self) -> None:
        from unittest.mock import patch

        with patch("agent.fitness.storage._storage", None):
            assert get_fitness_storage() is get_fitness_storage()
