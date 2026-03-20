"""Unit tests for Postgres-only fitness storage behavior."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fitness import ExerciseType, FitnessStorage, WorkoutEntry, get_fitness_storage


def _make_pool() -> tuple[AsyncMock, AsyncMock]:
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    acquire_context = MagicMock()
    acquire_context.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_context.__aexit__ = AsyncMock(return_value=None)

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock(return_value=acquire_context)
    return mock_pool, mock_conn


class TestFitnessStorageInit:
    """Tests for Postgres-only storage initialization."""

    @pytest.mark.asyncio
    async def test_initialize_requires_postgres_database_url(self) -> None:
        """Initialization should fail fast when Postgres is not configured."""
        storage = FitnessStorage()

        with (
            patch("agent.fitness.storage.postgres_dsn_from_environment", return_value=None),
            patch("agent.fitness.storage.get_shared_app_pool", AsyncMock(return_value=None)),
        ):
            with pytest.raises(RuntimeError, match="requires DATABASE_URL"):
                await storage.initialize()

    @pytest.mark.asyncio
    async def test_initialize_creates_tables_and_is_idempotent(self) -> None:
        """Initialization should create tables once and reuse the same pool."""
        mock_pool, mock_conn = _make_pool()
        get_pool = AsyncMock(return_value=mock_pool)
        storage = FitnessStorage()

        with (
            patch(
                "agent.fitness.storage.postgres_dsn_from_environment",
                return_value="postgresql://localhost/db",
            ),
            patch("agent.fitness.storage.get_shared_app_pool", get_pool),
        ):
            await storage.initialize()
            await storage.initialize()

        assert storage._initialized is True
        assert get_pool.await_count == 1

        executed_statements = [call.args[0] for call in mock_conn.execute.await_args_list]
        assert any('ADD COLUMN IF NOT EXISTS "set"' in statement for statement in executed_statements)
        assert any("DROP COLUMN IF EXISTS sets" in statement for statement in executed_statements)


class TestWorkoutStats:
    """Tests for workout stat aggregation independent of database transport."""

    @pytest.mark.asyncio
    async def test_get_workout_stats_uses_set_field(self) -> None:
        """Workout stats should continue to aggregate entries with the new field."""
        storage = FitnessStorage()
        entry = WorkoutEntry(
            user_id="test_user",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Bench Press",
            duration_minutes=45,
            set=2,
            reps=8,
            weight=100.0,
            created_at=datetime.now(UTC).isoformat(),
        )

        with patch.object(storage, "get_workout_entries", AsyncMock(return_value=[entry])):
            stats = await storage.get_workout_stats("test_user")

        assert stats["total_workouts"] == 1
        assert stats["total_minutes"] == 45
        assert stats["personal_records"][0]["exercise"] == "Bench Press"


class TestGetFitnessStorage:
    """Tests for the global storage instance."""

    def test_get_fitness_storage_returns_instance(self) -> None:
        """Test that get_fitness_storage returns a FitnessStorage instance."""
        with patch("agent.fitness.storage._storage", None):
            storage = get_fitness_storage()
            assert isinstance(storage, FitnessStorage)

    def test_get_fitness_storage_returns_same_instance(self) -> None:
        """Test that get_fitness_storage returns the same instance."""
        with patch("agent.fitness.storage._storage", None):
            storage1 = get_fitness_storage()
            storage2 = get_fitness_storage()
            assert storage1 is storage2
