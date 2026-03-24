"""Unit tests for prompt definition functions."""

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import MockReadonlyContext

from agent.prompt import (
    _load_context_file,
    load_context,
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
        assert "clarity" in instruction.lower()
        assert "context" in instruction.lower()

    def test_instruction_is_consistent(self) -> None:
        """Test that function returns the same instruction on multiple calls."""
        instruction1 = return_instruction_root()
        instruction2 = return_instruction_root()

        assert instruction1 == instruction2

    def test_instruction_explicitly_disallows_tables(self) -> None:
        """Test that prompt guidance bans markdown tables."""
        instruction = return_instruction_root()

        assert "Do not use markdown tables." in instruction

    def test_instruction_explains_recurring_reminder_contract(self) -> None:
        """Test that prompt explains cron-only recurrence and delivery behavior."""
        instruction = return_instruction_root()

        assert "5-field" in instruction
        assert "cron expression" in instruction
        assert "Do not call schedule_reminder again" in instruction

    def test_instruction_uses_configured_garbanzo_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that Garbanzo advertises the configured durable home path."""
        configured_home = "/srv/garbanzo-home"
        monkeypatch.setenv("GARBANZO_HOME", configured_home)

        instruction = return_instruction_root()

        assert configured_home in instruction
        assert f"{configured_home}/workspace" in instruction

    def test_instruction_uses_default_garbanzo_home_when_env_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that Garbanzo falls back to the Docker default home path."""
        default_home = "/home/app/garbanzo-home"
        monkeypatch.delenv("GARBANZO_HOME", raising=False)

        instruction = return_instruction_root()

        assert default_home in instruction
        assert f"{default_home}/workspace" in instruction


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
        ist_today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")

        assert ist_today in instruction
        # Default app timezone is Asia/Kolkata (see AGENT_TIMEZONE)
        assert "current time" in instruction.lower()
        assert "Asia/Kolkata" in instruction

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
        import re

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

        # Both should contain a wall-clock datetime pattern
        import re

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
        import re

        datetime_pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        assert re.search(datetime_pattern, instruction1)


class TestLoadContextEdgeCases:
    """Branch coverage for context file loading."""

    def test_load_context_warns_when_no_files(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        assert load_context(tmp_path) == ""
        assert "No context files loaded" in caplog.text

    def test_load_context_file_read_error_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = tmp_path / "BOOTSTRAP.md"
        p.write_text("x", encoding="utf-8")

        def _boom(*_a: object, **_kw: object) -> str:
            raise OSError("read failed")

        monkeypatch.setattr("agent.prompt.Path.read_text", _boom)
        assert _load_context_file("BOOTSTRAP.md", tmp_path) == ""
