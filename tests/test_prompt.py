"""Unit tests for prompt definition functions."""

import re
from datetime import date

from conftest import MockReadonlyContext

from agent.prompt import (
    return_description_root,
    return_global_instruction,
    return_instruction_root,
)


class TestReturnDescriptionRoot:
    """Tests for return_description_root function."""

    def test_returns_non_empty_string(self) -> None:
        """Test that function returns a non-empty description string."""
        description = return_description_root()

        assert isinstance(description, str)
        assert len(description) > 0

    def test_description_content(self) -> None:
        """Test that description is a non-empty string with meaningful content."""
        description = return_description_root()

        # Description should be a non-empty string (flexible for any agent name)
        assert isinstance(description, str)
        assert len(description) > 0
        # Should contain at least some alphabetic characters
        assert any(c.isalpha() for c in description)

    def test_description_is_consistent(self) -> None:
        """Test that function returns the same description on multiple calls."""
        description1 = return_description_root()
        description2 = return_description_root()

        assert description1 == description2


class TestReturnInstructionRoot:
    """Tests for return_instruction_root function."""

    def test_returns_non_empty_string(self) -> None:
        """Test that function returns a non-empty instruction string."""
        instruction = return_instruction_root()

        assert isinstance(instruction, str)
        assert len(instruction) > 0

    def test_instruction_content(self) -> None:
        """Test that instruction contains expected guidance."""
        instruction = return_instruction_root()

        assert "<output_verbosity_spec>" in instruction
        assert "sentences" in instruction.lower()
        assert "bullets" in instruction.lower()

    def test_instruction_is_consistent(self) -> None:
        """Test that function returns the same instruction on multiple calls."""
        instruction1 = return_instruction_root()
        instruction2 = return_instruction_root()

        assert instruction1 == instruction2


class TestReturnGlobalInstruction:
    """Tests for return_global_instruction InstructionProvider function."""

    def test_returns_string_with_context(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that InstructionProvider returns a string when given ReadonlyContext."""
        instruction = return_global_instruction(mock_readonly_context)  # type: ignore

        assert isinstance(instruction, str)
        assert len(instruction) > 0

    def test_includes_current_date(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that instruction includes today's date dynamically."""
        instruction = return_global_instruction(mock_readonly_context)  # type: ignore
        today = str(date.today())

        assert today in instruction
        # Should include timezone info (defaults to UTC when TZ env var not set)
        assert "current time" in instruction.lower()

    def test_includes_assistant_context(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that instruction identifies role as helpful assistant."""
        instruction = return_global_instruction(mock_readonly_context)  # type: ignore

        assert "helpful" in instruction.lower()
        assert "assistant" in instruction.lower()

    def test_date_updates_dynamically(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that datetime updates when function is called."""

        # Get instruction and verify it has a datetime
        instruction1 = return_global_instruction(mock_readonly_context)  # type: ignore

        # Verify it contains a datetime-like pattern (YYYY-MM-DD HH:MM:SS)
        datetime_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        assert re.search(datetime_pattern, instruction1)

        # Verify it contains day of week
        days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        assert any(day in instruction1 for day in days)

    def test_accepts_readonly_context_parameter(self) -> None:
        """Test that function signature accepts ReadonlyContext as required by ADK."""
        # Create a context with state to ensure it's accessible if needed
        context = MockReadonlyContext(
            agent_name="test_agent",
            invocation_id="test-123",
            state={"user_id": "user_456", "preferences": {"theme": "dark"}},
        )

        # Function should execute without errors
        instruction = return_global_instruction(context)  # type: ignore

        # Verify it returns valid instruction
        assert isinstance(instruction, str)
        assert len(instruction) > 0

    def test_context_state_accessible_but_unused(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that context state is accessible but not currently used in instruction.

        This test documents that while the function receives ReadonlyContext with
        state access, the current implementation doesn't use state. This allows
        future enhancement to customize instructions based on session state.
        """
        # Create two contexts with different states
        context1 = MockReadonlyContext(state={"user_tier": "premium"})
        context2 = MockReadonlyContext(state={"user_tier": "free"})

        instruction1 = return_global_instruction(context1)  # type: ignore
        instruction2 = return_global_instruction(context2)  # type: ignore

        # Both should contain the datetime pattern
        datetime_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        assert re.search(datetime_pattern, instruction1)
        assert re.search(datetime_pattern, instruction2)

        # Verify state is accessible if needed in future
        assert context1.state["user_tier"] == "premium"
        assert context2.state["user_tier"] == "free"

    def test_instruction_format_consistency(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that instruction maintains consistent format across calls."""
        instruction1 = return_global_instruction(mock_readonly_context)  # type: ignore

        # Should contain expected structure
        assert "\n" in instruction1  # Multi-line format
        assert "Current time" in instruction1
        # Verify datetime format (YYYY-MM-DD HH:MM:SS Day)
        datetime_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        assert re.search(datetime_pattern, instruction1)

    def test_includes_context_files(
        self, mock_readonly_context: MockReadonlyContext
    ) -> None:
        """Test that instruction includes all context files."""
        instruction = return_global_instruction(mock_readonly_context)  # type: ignore

        # Should contain SOUL.md
        assert "SOUL.md" in instruction
        assert "Core Truths" in instruction
        assert "Boundaries" in instruction
        assert "Continuity" in instruction

        # Should contain IDENTITY.md
        assert "IDENTITY.md" in instruction
        assert "Name" in instruction
        assert "Creature" in instruction
        assert "Vibe" in instruction

        # Should contain USER.md
        assert "USER.md" in instruction
        assert "Context" in instruction
