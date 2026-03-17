"""Tests for fitness storage module."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.fitness import (
    CalorieEntry,
    ExerciseType,
    FitnessStorage,
    MealType,
    WorkoutEntry,
    get_fitness_storage,
)
from agent.fitness.storage import _get_default_db_path


@pytest.fixture
def temp_db_path() -> Path:
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test_fitness.db"


@pytest.fixture
def storage(temp_db_path: Path) -> FitnessStorage:
    """Create a FitnessStorage instance with a temporary database."""
    return FitnessStorage(db_path=temp_db_path)


@pytest.fixture
def sample_calorie_entry() -> CalorieEntry:
    """Create a sample calorie entry."""
    return CalorieEntry(
        user_id="test_user",
        date="2026-03-15",
        food_item="Grilled Chicken",
        calories=350,
        protein=40.0,
        carbs=5.0,
        fat=15.0,
        meal_type=MealType.LUNCH,
        notes="Healthy lunch",
        created_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def sample_workout_entry() -> WorkoutEntry:
    """Create a sample workout entry."""
    return WorkoutEntry(
        user_id="test_user",
        date="2026-03-15",
        exercise_type=ExerciseType.STRENGTH,
        exercise_name="Bench Press",
        duration_minutes=45,
        sets=4,
        reps=8,
        weight=80.0,
        notes="Good form",
        created_at=datetime.now(UTC).isoformat(),
    )


class TestFitnessStorageInit:
    """Tests for FitnessStorage initialization."""

    def test_init_default_path(self) -> None:
        """Test default database path uses data directory."""
        storage = FitnessStorage()
        assert storage.db_path == _get_default_db_path()
        assert storage.db_path.name == "fitness.db"

    def test_init_custom_path(self, temp_db_path: Path) -> None:
        """Test custom database path."""
        storage = FitnessStorage(db_path=temp_db_path)
        assert storage.db_path == temp_db_path

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, storage: FitnessStorage) -> None:
        """Test that initialize creates the required tables."""
        await storage.initialize()

        assert storage._initialized
        assert storage.db_path.exists()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, storage: FitnessStorage) -> None:
        """Test that initialize is idempotent."""
        await storage.initialize()
        await storage.initialize()  # Call twice

        assert storage._initialized


class TestCalorieOperations:
    """Tests for calorie entry operations."""

    @pytest.mark.asyncio
    async def test_add_calorie_entry(
        self, storage: FitnessStorage, sample_calorie_entry: CalorieEntry
    ) -> None:
        """Test adding a calorie entry."""
        entry_id = await storage.add_calorie_entry(sample_calorie_entry)

        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_get_calorie_entries(
        self, storage: FitnessStorage, sample_calorie_entry: CalorieEntry
    ) -> None:
        """Test retrieving calorie entries."""
        await storage.add_calorie_entry(sample_calorie_entry)

        entries = await storage.get_calorie_entries("test_user")

        assert len(entries) == 1
        assert entries[0].food_item == "Grilled Chicken"
        assert entries[0].calories == 350

    @pytest.mark.asyncio
    async def test_get_calorie_entries_by_date_range(
        self, storage: FitnessStorage
    ) -> None:
        """Test retrieving entries within a date range."""
        # Add entries for different dates
        entry1 = CalorieEntry(
            user_id="test_user",
            date="2026-03-10",
            food_item="Breakfast",
            calories=400,
            meal_type=MealType.BREAKFAST,
            created_at=datetime.now(UTC).isoformat(),
        )
        entry2 = CalorieEntry(
            user_id="test_user",
            date="2026-03-15",
            food_item="Lunch",
            calories=500,
            meal_type=MealType.LUNCH,
            created_at=datetime.now(UTC).isoformat(),
        )
        entry3 = CalorieEntry(
            user_id="test_user",
            date="2026-03-20",
            food_item="Dinner",
            calories=600,
            meal_type=MealType.DINNER,
            created_at=datetime.now(UTC).isoformat(),
        )

        await storage.add_calorie_entry(entry1)
        await storage.add_calorie_entry(entry2)
        await storage.add_calorie_entry(entry3)

        entries = await storage.get_calorie_entries(
            "test_user", start_date="2026-03-12", end_date="2026-03-18"
        )

        assert len(entries) == 1
        assert entries[0].date == "2026-03-15"

    @pytest.mark.asyncio
    async def test_get_calorie_entries_empty(self, storage: FitnessStorage) -> None:
        """Test retrieving entries when none exist."""
        entries = await storage.get_calorie_entries("nonexistent_user")

        assert entries == []

    @pytest.mark.asyncio
    async def test_get_calorie_stats(self, storage: FitnessStorage) -> None:
        """Test getting calorie statistics."""
        # Add multiple entries
        for i in range(3):
            entry = CalorieEntry(
                user_id="test_user",
                date=f"2026-03-{10 + i}",
                food_item=f"Meal {i}",
                calories=500 + i * 100,
                protein=30.0 + i,
                meal_type=MealType.LUNCH,
                created_at=datetime.now(UTC).isoformat(),
            )
            await storage.add_calorie_entry(entry)

        stats = await storage.get_calorie_stats("test_user")

        assert stats["total_entries"] == 3
        assert stats["total_calories"] == 1800  # 500 + 600 + 700
        assert stats["days_tracked"] == 3


class TestWorkoutOperations:
    """Tests for workout entry operations."""

    @pytest.mark.asyncio
    async def test_add_workout_entry(
        self, storage: FitnessStorage, sample_workout_entry: WorkoutEntry
    ) -> None:
        """Test adding a workout entry."""
        entry_id = await storage.add_workout_entry(sample_workout_entry)

        assert entry_id > 0

    @pytest.mark.asyncio
    async def test_get_workout_entries(
        self, storage: FitnessStorage, sample_workout_entry: WorkoutEntry
    ) -> None:
        """Test retrieving workout entries."""
        await storage.add_workout_entry(sample_workout_entry)

        entries = await storage.get_workout_entries("test_user")

        assert len(entries) == 1
        assert entries[0].exercise_name == "Bench Press"
        assert entries[0].weight == 80.0

    @pytest.mark.asyncio
    async def test_get_workout_entries_by_type(self, storage: FitnessStorage) -> None:
        """Test filtering workouts by type."""
        entry1 = WorkoutEntry(
            user_id="test_user",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Squat",
            created_at=datetime.now(UTC).isoformat(),
        )
        entry2 = WorkoutEntry(
            user_id="test_user",
            date="2026-03-15",
            exercise_type=ExerciseType.CARDIO,
            exercise_name="Running",
            distance_km=5.0,
            created_at=datetime.now(UTC).isoformat(),
        )

        await storage.add_workout_entry(entry1)
        await storage.add_workout_entry(entry2)

        strength_entries = await storage.get_workout_entries(
            "test_user", exercise_type="strength"
        )
        cardio_entries = await storage.get_workout_entries(
            "test_user", exercise_type="cardio"
        )

        assert len(strength_entries) == 1
        assert strength_entries[0].exercise_name == "Squat"
        assert len(cardio_entries) == 1
        assert cardio_entries[0].exercise_name == "Running"

    @pytest.mark.asyncio
    async def test_get_workout_stats(self, storage: FitnessStorage) -> None:
        """Test getting workout statistics."""
        entry = WorkoutEntry(
            user_id="test_user",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Bench Press",
            duration_minutes=45,
            weight=100.0,
            created_at=datetime.now(UTC).isoformat(),
        )
        await storage.add_workout_entry(entry)

        stats = await storage.get_workout_stats("test_user")

        assert stats["total_workouts"] == 1
        assert stats["total_minutes"] == 45
        assert len(stats["personal_records"]) > 0
        assert stats["personal_records"][0]["exercise"] == "Bench Press"


class TestDeleteOperations:
    """Tests for delete operations."""

    @pytest.mark.asyncio
    async def test_delete_calorie_entry(
        self, storage: FitnessStorage, sample_calorie_entry: CalorieEntry
    ) -> None:
        """Test deleting a calorie entry."""
        entry_id = await storage.add_calorie_entry(sample_calorie_entry)

        deleted = await storage.delete_entry("calorie", entry_id, "test_user")

        assert deleted

        entries = await storage.get_calorie_entries("test_user")
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_delete_workout_entry(
        self, storage: FitnessStorage, sample_workout_entry: WorkoutEntry
    ) -> None:
        """Test deleting a workout entry."""
        entry_id = await storage.add_workout_entry(sample_workout_entry)

        deleted = await storage.delete_entry("workout", entry_id, "test_user")

        assert deleted

        entries = await storage.get_workout_entries("test_user")
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entry(self, storage: FitnessStorage) -> None:
        """Test deleting an entry that doesn't exist."""
        deleted = await storage.delete_entry("calorie", 999, "test_user")

        assert not deleted

    @pytest.mark.asyncio
    async def test_delete_wrong_user(
        self, storage: FitnessStorage, sample_calorie_entry: CalorieEntry
    ) -> None:
        """Test that a user can't delete another user's entry."""
        entry_id = await storage.add_calorie_entry(sample_calorie_entry)

        deleted = await storage.delete_entry("calorie", entry_id, "other_user")

        assert not deleted

        entries = await storage.get_calorie_entries("test_user")
        assert len(entries) == 1

    @pytest.mark.asyncio
    async def test_delete_invalid_type(self, storage: FitnessStorage) -> None:
        """Test deleting with invalid entry type."""
        deleted = await storage.delete_entry("invalid", 1, "test_user")

        assert not deleted


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
