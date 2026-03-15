"""Tests for fitness tools in tools.py."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.tools import ToolContext

from agent.tools import (
    add_calories,
    delete_fitness_entry,
    execute_bash,
    get_calorie_stats,
    get_workout_stats,
    list_calories,
    list_workouts,
    log_workout,
)


@pytest.fixture
def mock_tool_context() -> ToolContext:
    """Create a mock ToolContext with user_id."""
    context = MagicMock(spec=ToolContext)
    context.user_id = "test_user"
    context.state = MagicMock()
    context.state.get = MagicMock(return_value="test_user")
    return context


@pytest.fixture
def mock_tool_context_no_user() -> ToolContext:
    """Create a mock ToolContext without user_id."""
    context = MagicMock(spec=ToolContext)
    context.user_id = None
    context.state = MagicMock()
    context.state.get = MagicMock(return_value=None)
    return context


class TestAddCalories:
    """Tests for add_calories tool."""

    @pytest.mark.asyncio
    async def test_add_calories_success(self, mock_tool_context: ToolContext) -> None:
        """Test adding calories successfully."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.add_calorie_entry = AsyncMock(return_value=1)
            mock_get_storage.return_value = mock_storage

            result = await add_calories(
                mock_tool_context,
                food_item="Test Food",
                calories=500,
                meal_type="lunch",
            )

            assert result["status"] == "success"
            assert result["entry_id"] == 1
            assert "Test Food" in result["message"]

    @pytest.mark.asyncio
    async def test_add_calories_no_user(
        self, mock_tool_context_no_user: ToolContext
    ) -> None:
        """Test adding calories without user_id."""
        result = await add_calories(
            mock_tool_context_no_user,
            food_item="Test Food",
            calories=500,
        )

        assert result["status"] == "error"
        assert "user not identified" in result["message"]

    @pytest.mark.asyncio
    async def test_add_calories_invalid_meal_type(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test adding calories with invalid meal type."""
        result = await add_calories(
            mock_tool_context,
            food_item="Test Food",
            calories=500,
            meal_type="invalid",
        )

        assert result["status"] == "error"
        assert "Invalid meal type" in result["message"]


class TestListCalories:
    """Tests for list_calories tool."""

    @pytest.mark.asyncio
    async def test_list_calories_success(self, mock_tool_context: ToolContext) -> None:
        """Test listing calories successfully."""
        from agent.fitness import CalorieEntry, MealType

        mock_entry = CalorieEntry(
            id=1,
            user_id="test_user",
            date="2026-03-15",
            food_item="Test Food",
            calories=500,
            meal_type=MealType.LUNCH,
            created_at=datetime.now(UTC).isoformat(),
        )

        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.get_calorie_entries = AsyncMock(return_value=[mock_entry])
            mock_get_storage.return_value = mock_storage

            result = await list_calories(mock_tool_context)

            assert result["status"] == "success"
            assert result["count"] == 1
            assert result["total_calories"] == 500

    @pytest.mark.asyncio
    async def test_list_calories_empty(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test listing calories when empty."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.get_calorie_entries = AsyncMock(return_value=[])
            mock_get_storage.return_value = mock_storage

            result = await list_calories(mock_tool_context)

            assert result["status"] == "success"
            assert result["entries"] == []


class TestGetCalorieStats:
    """Tests for get_calorie_stats tool."""

    @pytest.mark.asyncio
    async def test_get_calorie_stats_success(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test getting calorie stats successfully."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.get_calorie_stats = AsyncMock(
                return_value={
                    "total_entries": 5,
                    "total_calories": 2500,
                    "avg_daily_calories": 500.0,
                }
            )
            mock_get_storage.return_value = mock_storage

            result = await get_calorie_stats(mock_tool_context)

            assert result["status"] == "success"
            assert result["total_entries"] == 5


class TestLogWorkout:
    """Tests for log_workout tool."""

    @pytest.mark.asyncio
    async def test_log_workout_success(self, mock_tool_context: ToolContext) -> None:
        """Test logging workout successfully."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.add_workout_entry = AsyncMock(return_value=1)
            mock_get_storage.return_value = mock_storage

            result = await log_workout(
                mock_tool_context,
                exercise_name="Bench Press",
                exercise_type="strength",
                sets=4,
                reps=8,
                weight=80.0,
            )

            assert result["status"] == "success"
            assert result["entry_id"] == 1
            assert "Bench Press" in result["message"]

    @pytest.mark.asyncio
    async def test_log_workout_invalid_type(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test logging workout with invalid type."""
        result = await log_workout(
            mock_tool_context,
            exercise_name="Test",
            exercise_type="invalid_type",
        )

        assert result["status"] == "error"
        assert "Invalid exercise type" in result["message"]


class TestListWorkouts:
    """Tests for list_workouts tool."""

    @pytest.mark.asyncio
    async def test_list_workouts_success(self, mock_tool_context: ToolContext) -> None:
        """Test listing workouts successfully."""
        from agent.fitness import ExerciseType, WorkoutEntry

        mock_entry = WorkoutEntry(
            id=1,
            user_id="test_user",
            date="2026-03-15",
            exercise_type=ExerciseType.STRENGTH,
            exercise_name="Bench Press",
            weight=80.0,
            created_at=datetime.now(UTC).isoformat(),
        )

        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.get_workout_entries = AsyncMock(return_value=[mock_entry])
            mock_get_storage.return_value = mock_storage

            result = await list_workouts(mock_tool_context)

            assert result["status"] == "success"
            assert result["count"] == 1


class TestGetWorkoutStats:
    """Tests for get_workout_stats tool."""

    @pytest.mark.asyncio
    async def test_get_workout_stats_success(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test getting workout stats successfully."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.get_workout_stats = AsyncMock(
                return_value={
                    "total_workouts": 10,
                    "total_minutes": 450,
                    "personal_records": [],
                }
            )
            mock_get_storage.return_value = mock_storage

            result = await get_workout_stats(mock_tool_context)

            assert result["status"] == "success"
            assert result["total_workouts"] == 10


class TestDeleteFitnessEntry:
    """Tests for delete_fitness_entry tool."""

    @pytest.mark.asyncio
    async def test_delete_calorie_entry(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test deleting a calorie entry."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.delete_entry = AsyncMock(return_value=True)
            mock_get_storage.return_value = mock_storage

            result = await delete_fitness_entry(
                mock_tool_context,
                entry_type="calorie",
                entry_id=1,
            )

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_workout_entry(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test deleting a workout entry."""
        with patch(
            "agent.tools.get_fitness_storage"
        ) as mock_get_storage:
            mock_storage = AsyncMock()
            mock_storage.delete_entry = AsyncMock(return_value=True)
            mock_get_storage.return_value = mock_storage

            result = await delete_fitness_entry(
                mock_tool_context,
                entry_type="workout",
                entry_id=1,
            )

            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_delete_invalid_entry_type(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test deleting with invalid entry type."""
        result = await delete_fitness_entry(
            mock_tool_context,
            entry_type="invalid",
            entry_id=1,
        )

        assert result["status"] == "error"
        assert "Invalid entry_type" in result["message"]


class TestExecuteBash:
    """Tests for execute_bash tool."""

    def test_execute_bash_echo(self, mock_tool_context: ToolContext) -> None:
        """Test executing a simple echo command."""
        result = execute_bash(mock_tool_context, "echo 'hello'")

        assert result["status"] == "success"
        assert result["stdout"] == "hello"

    def test_execute_bash_dangerous_command(
        self, mock_tool_context: ToolContext
    ) -> None:
        """Test that dangerous commands are blocked."""
        result = execute_bash(mock_tool_context, "rm -rf /")

        assert result["status"] == "error"
        assert "Blocked dangerous command" in result["message"]

    def test_execute_bash_sudo_blocked(self, mock_tool_context: ToolContext) -> None:
        """Test that sudo commands are blocked."""
        result = execute_bash(mock_tool_context, "sudo apt-get install something")

        assert result["status"] == "error"
        assert "Blocked dangerous command" in result["message"]

    def test_execute_bash_timeout(self, mock_tool_context: ToolContext) -> None:
        """Test command timeout."""
        # This test uses a very short timeout
        result = execute_bash(
            mock_tool_context,
            "sleep 10",
            timeout=1,
        )

        assert result["status"] == "error"
        assert "timed out" in result["message"]
