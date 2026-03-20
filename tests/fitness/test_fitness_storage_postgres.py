"""Postgres-mode tests for FitnessStorage (mocked asyncpg pool)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fitness import CalorieEntry, ExerciseType, MealType, WorkoutEntry
from agent.fitness.storage import FitnessStorage


def _make_pool() -> AsyncMock:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    acq_cm = MagicMock()
    acq_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acq_cm.__aexit__ = AsyncMock(return_value=None)
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acq_cm)
    pool.fetchval = AsyncMock(return_value=99)
    pool.fetch = AsyncMock(return_value=[])
    pool.fetchrow = AsyncMock(return_value=None)
    return pool


def _cal_row() -> dict[str, object]:
    return {
        "id": 1,
        "user_id": "u1",
        "date": "2026-03-15",
        "food_item": "egg",
        "calories": 70,
        "protein": 6.0,
        "carbs": 0.5,
        "fat": 5.0,
        "meal_type": "breakfast",
        "notes": None,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _wo_row() -> dict[str, object]:
    return {
        "id": 2,
        "user_id": "u1",
        "date": "2026-03-15",
        "exercise_type": "strength",
        "exercise_name": "squat",
        "duration_minutes": 30,
        "sets": 3,
        "reps": 10,
        "weight": 100.0,
        "distance_km": None,
        "notes": None,
        "created_at": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def mock_pool() -> AsyncMock:
    return _make_pool()


@pytest.mark.asyncio
async def test_fitness_postgres_calorie_workflow(mock_pool: AsyncMock) -> None:
    async def fake_pool() -> AsyncMock:
        return mock_pool

    mock_pool.fetch = AsyncMock(side_effect=[[_cal_row()], [_cal_row()]])
    with (
        patch(
            "agent.fitness.storage.postgres_dsn_from_environment",
            return_value="postgresql://localhost/db",
        ),
        patch("agent.fitness.storage.get_shared_app_pool", side_effect=fake_pool),
    ):
        storage = FitnessStorage()
        await storage.initialize()
        entry = CalorieEntry(
            user_id="u1",
            date="2026-03-15",
            food_item="egg",
            calories=70,
            meal_type=MealType.BREAKFAST,
            created_at=datetime.now(UTC).isoformat(),
        )
        eid = await storage.add_calorie_entry(entry)
        assert eid == 99

        rows = await storage.get_calorie_entries("u1")
        assert len(rows) == 1
        stats = await storage.get_calorie_stats("u1")
        assert stats["total_entries"] == 1


@pytest.mark.asyncio
async def test_fitness_postgres_workout_and_delete(mock_pool: AsyncMock) -> None:
    async def fake_pool() -> AsyncMock:
        return mock_pool

    mock_pool.fetch = AsyncMock(side_effect=[[_wo_row()], [_wo_row()]])
    mock_pool.fetchrow = AsyncMock(return_value={"id": 2})
    with (
        patch(
            "agent.fitness.storage.postgres_dsn_from_environment",
            return_value="postgresql://localhost/db",
        ),
        patch("agent.fitness.storage.get_shared_app_pool", side_effect=fake_pool),
    ):
        storage = FitnessStorage()
        await storage.initialize()
        w = WorkoutEntry(
            user_id="u1",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="squat",
            created_at=datetime.now(UTC).isoformat(),
        )
        assert await storage.add_workout_entry(w) == 99

        workouts = await storage.get_workout_entries("u1", exercise_type="strength")
        assert len(workouts) == 1
        stats = await storage.get_workout_stats("u1")
        assert stats["total_workouts"] == 1

        assert await storage.delete_entry("workout", 2, "u1") is True
