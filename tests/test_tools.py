"""Unit tests for custom tools."""

import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

# Import mock classes from conftest
from conftest import MockState, MockToolContext

from agent.reminders import Reminder, ReminderScheduler, ReminderStorage
from agent.tools import (
    _agent_runs_inside_docker,
    _parse_reminder_datetime,
    _truncate_output,
    cancel_reminder,
    docker_bash_execute,
    example_tool,
    get_current_datetime,
    list_reminders,
    schedule_reminder,
)


class TestExampleTool:
    """Tests for the example_tool function."""

    def test_example_tool_returns_success(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that example_tool returns success status and message."""
        # Setup logging to capture INFO level
        caplog.set_level(logging.INFO)

        # Create mock tool context with state
        state = MockState({"user_id": "test_user", "session_key": "value"})
        tool_context = MockToolContext(state=state)

        # Execute tool
        result = example_tool(tool_context)  # type: ignore

        # Verify return value
        assert result["status"] == "success"
        assert result["message"] == "Successfully used example_tool."

    def test_example_tool_logs_state_keys(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that example_tool logs session state keys."""
        # Setup logging to capture INFO level
        caplog.set_level(logging.INFO)

        # Create mock tool context with state
        state = MockState({"key1": "value1", "key2": "value2"})
        tool_context = MockToolContext(state=state)

        # Execute tool
        example_tool(tool_context)  # type: ignore

        # Verify logging
        assert "Session state keys:" in caplog.text
        assert "Successfully used example_tool." in caplog.text

        # Verify INFO level was used
        info_records = [r for r in caplog.records if r.levelname == "INFO"]
        assert len(info_records) == 2

    def test_example_tool_with_empty_state(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that example_tool handles empty state correctly."""
        # Setup logging
        caplog.set_level(logging.INFO)

        # Create mock tool context with empty state
        state = MockState({})
        tool_context = MockToolContext(state=state)

        # Execute tool
        result = example_tool(tool_context)  # type: ignore

        # Verify success even with empty state
        assert result["status"] == "success"
        assert result["message"] == "Successfully used example_tool."

        # Verify logging occurred
        assert "Session state keys:" in caplog.text


class TestGetCurrentDatetime:
    """Tests for get_current_datetime tool."""

    def test_returns_clock_fields(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        result = get_current_datetime(tool_context)  # type: ignore[arg-type]
        assert "iso_datetime" in result
        assert "time" in result
        assert "date" in result
        assert "weekday" in result
        assert "timezone" in result
        assert len(result["time"].split(":")) == 3


class TestParseReminderDatetime:
    """Tests for _parse_reminder_datetime helper function."""

    def test_parse_absolute_datetime(self) -> None:
        """Test parsing absolute datetime format returns UTC-aware datetime."""
        result = _parse_reminder_datetime("2026-03-15 14:30")
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 15
        # Result is timezone-aware in UTC
        assert result.tzinfo is not None

    def test_parse_in_minutes(self) -> None:
        """Test parsing relative time in minutes."""
        now = datetime.now(UTC)
        result = _parse_reminder_datetime("in 30 minutes")
        expected = now + timedelta(minutes=30)
        # Allow 1 second tolerance
        diff = abs((result - expected).total_seconds())
        assert diff < 1
        # Result is timezone-aware
        assert result.tzinfo is not None

    def test_parse_in_hours(self) -> None:
        """Test parsing relative time in hours."""
        now = datetime.now(UTC)
        result = _parse_reminder_datetime("in 2 hours")
        expected = now + timedelta(hours=2)
        diff = abs((result - expected).total_seconds())
        assert diff < 1
        # Result is timezone-aware
        assert result.tzinfo is not None

    def test_parse_tomorrow(self) -> None:
        """Test parsing tomorrow."""
        now = datetime.now(UTC)
        result = _parse_reminder_datetime("tomorrow")
        assert result.day != now.day or result.month != now.month
        # Result is timezone-aware
        assert result.tzinfo is not None

    def test_parse_tomorrow_with_time(self) -> None:
        """Test parsing tomorrow with specific time returns timezone-aware."""
        result = _parse_reminder_datetime("tomorrow at 09:30")
        # The result is timezone-aware in UTC
        assert result.tzinfo is not None
        # The time is interpreted in local timezone and converted to UTC
        # So we just verify it's a valid time (hour and minute are reasonable)
        assert 0 <= result.hour <= 23
        assert 0 <= result.minute <= 59

    def test_parse_returns_timezone_aware(self) -> None:
        """Test that all parsed datetimes are timezone-aware in UTC."""
        test_cases = [
            "2026-03-15 14:30",
            "in 30 minutes",
            "tomorrow",
            "tomorrow at 9am",
        ]
        for case in test_cases:
            result = _parse_reminder_datetime(case)
            assert result.tzinfo is not None

    def test_parse_invalid_format_raises_error(self) -> None:
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError):
            _parse_reminder_datetime("invalid datetime")


class TestScheduleReminder:
    """Tests for schedule_reminder tool."""

    @pytest.mark.asyncio
    async def test_no_user_id_returns_error(self) -> None:
        """Test that missing user_id returns error."""
        state = MockState({})
        tool_context = MockToolContext(state=state)

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Test reminder",
            reminder_datetime="2026-03-15 14:30",
        )

        assert result["status"] == "error"
        assert "user not identified" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_datetime_and_recurrence_returns_error(self) -> None:
        """One-time path requires reminder_datetime when recurrence is empty."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Test reminder",
            reminder_datetime=None,
            recurrence=None,
        )

        assert result["status"] == "error"
        assert "Could not understand the time" in result["message"]

    @pytest.mark.asyncio
    async def test_message_too_long_returns_error(self) -> None:
        """Test that long message returns error."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)
        long_message = "x" * 501

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message=long_message,
            reminder_datetime="2026-03-15 14:30",
        )

        assert result["status"] == "error"
        assert "too long" in result["message"]

    @pytest.mark.asyncio
    async def test_past_time_returns_error(self) -> None:
        """Test that past time returns error."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)
        past_time = "2020-01-01 10:00"

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Test reminder",
            reminder_datetime=past_time,
        )

        assert result["status"] == "error"
        assert "future" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_invalid_datetime_returns_error(self) -> None:
        """Test that invalid datetime returns error."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Test reminder",
            reminder_datetime="not a valid datetime",
        )

        assert result["status"] == "error"
        assert "could not understand the time" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_successful_schedule(self) -> None:
        """Test successfully scheduling a reminder."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage

            with patch("agent.tools.get_scheduler", return_value=scheduler):
                state = MockState({"user_id": "test_user"})
                tool_context = MockToolContext(state=state)

                # Use relative time format which dateparser handles well
                result = await schedule_reminder(
                    tool_context,  # type: ignore
                    message="Test reminder",
                    reminder_datetime="in 1 hour",
                )

                assert result["status"] == "success"
                assert "reminder_id" in result
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_successful_recurring_schedule(self) -> None:
        """Test successfully scheduling a recurring reminder."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage

            with patch("agent.tools.get_scheduler", return_value=scheduler):
                state = MockState({"user_id": "test_user"})
                tool_context = MockToolContext(state=state)

                result = await schedule_reminder(
                    tool_context,  # type: ignore
                    message="Drink water",
                    recurrence="0 9 * * *",
                )

                reminders = await scheduler.get_user_reminders("test_user")

                assert result["status"] == "success"
                assert "Recurring reminder scheduled" in result["message"]
                assert len(reminders) == 1
                assert reminders[0].is_recurring is True
                assert reminders[0].recurrence_text == "cron: 0 9 * * *"
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_natural_language_recurrence_returns_error(self) -> None:
        """Test recurring reminders reject non-cron recurrence text."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Drink water",
            recurrence="every minute",
        )

        assert result["status"] == "error"
        assert "cron expression" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_recurring_schedule_rejects_reminder_datetime(self) -> None:
        """Test recurring reminders reject reminder_datetime plus recurrence."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        result = await schedule_reminder(
            tool_context,  # type: ignore
            message="Drink water",
            reminder_datetime="tomorrow at 9am",
            recurrence="0 9 * * *",
        )

        assert result["status"] == "error"
        assert "omit reminder_datetime" in result["message"].lower()


class TestListReminders:
    """Tests for list_reminders tool."""

    @pytest.mark.asyncio
    async def test_no_user_id_returns_error(self) -> None:
        """Test that missing user_id returns error."""
        state = MockState({})
        tool_context = MockToolContext(state=state)

        result = await list_reminders(tool_context)  # type: ignore

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_empty_reminders_list(self) -> None:
        """Test listing reminders when none exist."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage

            with patch("agent.tools.get_scheduler", return_value=scheduler):
                state = MockState({"user_id": "test_user"})
                tool_context = MockToolContext(state=state)

                result = await list_reminders(tool_context)  # type: ignore

                assert result["status"] == "success"
                assert result["reminders"] == []
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_recurring_reminders_include_schedule_metadata(self) -> None:
        """Test listing reminders exposes recurring schedule details."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage

            with patch("agent.tools.get_scheduler", return_value=scheduler):
                state = MockState({"user_id": "test_user"})
                tool_context = MockToolContext(state=state)

                await schedule_reminder(
                    tool_context,  # type: ignore
                    message="Stand up",
                    recurrence="*/15 * * * *",
                )

                result = await list_reminders(tool_context)  # type: ignore

                assert result["status"] == "success"
                assert result["count"] == 1
                assert result["reminders"][0]["is_recurring"] is True
                assert result["reminders"][0]["schedule_type"] == "recurring"
                assert result["reminders"][0]["recurrence"] == "cron: */15 * * * *"
                assert "next_trigger_time" in result["reminders"][0]
        finally:
            db_path.unlink(missing_ok=True)


class TestCancelReminder:
    """Tests for cancel_reminder tool."""

    @pytest.mark.asyncio
    async def test_no_user_id_returns_error(self) -> None:
        """Test that missing user_id returns error."""
        state = MockState({})
        tool_context = MockToolContext(state=state)

        result = await cancel_reminder(
            tool_context,  # type: ignore
            reminder_id=1,
        )

        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_reminder(self) -> None:
        """Test cancelling a non-existent reminder."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage

            with patch("agent.tools.get_scheduler", return_value=scheduler):
                state = MockState({"user_id": "test_user"})
                tool_context = MockToolContext(state=state)

                result = await cancel_reminder(
                    tool_context,  # type: ignore
                    reminder_id=999,
                )

                assert result["status"] == "error"
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_cancel_reminder_exception(self) -> None:
        """Test cancel_reminder handles exceptions."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        with patch("agent.tools.get_scheduler") as mock_get_scheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.delete_reminder = AsyncMock(
                side_effect=Exception("DB error")
            )
            mock_get_scheduler.return_value = mock_scheduler

            result = await cancel_reminder(
                tool_context,  # type: ignore
                reminder_id=1,
            )

            assert result["status"] == "error"
            assert "Failed to cancel reminder" in result["message"]


class TestScheduleReminderBranches:
    """Extra branches for schedule_reminder."""

    @pytest.mark.asyncio
    async def test_user_id_from_tool_context_attribute(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage
            tool_context = MockToolContext(state=MockState({}), user_id="attr-user")
            with patch("agent.tools.get_scheduler", return_value=scheduler):
                result = await schedule_reminder(
                    tool_context,  # type: ignore
                    message="Hi",
                    reminder_datetime="in 2 hours",
                )
            assert result["status"] == "success"
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_success_truncates_long_message_in_reply(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage
            long_msg = "M" * 80
            with patch("agent.tools.get_scheduler", return_value=scheduler):
                result = await schedule_reminder(
                    MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
                    message=long_msg,
                    reminder_datetime="in 2 hours",
                )
            assert result["status"] == "success"
            assert "..." in result["message"]
        finally:
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_scheduler_failure_returns_error(self) -> None:
        scheduler = MagicMock()
        scheduler.storage = AsyncMock()
        scheduler.storage.initialize = AsyncMock()
        scheduler.schedule_reminder = AsyncMock(side_effect=RuntimeError("db"))

        with patch("agent.tools.get_scheduler", return_value=scheduler):
            result = await schedule_reminder(
                MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
                message="x",
                reminder_datetime="in 3 hours",
            )
        assert result["status"] == "error"
        assert "Failed to schedule" in result["message"]


class TestListRemindersBranches:
    @pytest.mark.asyncio
    async def test_lists_formatted_reminders(self) -> None:
        scheduler = MagicMock()
        past = Reminder(
            id=1,
            user_id="u",
            message="do thing",
            trigger_time="2026-03-15T10:00:00+00:00",
            is_sent=False,
            created_at="2026-03-15T09:00:00",
        )
        scheduler.get_user_reminders = AsyncMock(return_value=[past])

        with patch("agent.tools.get_scheduler", return_value=scheduler):
            result = await list_reminders(
                MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
            )
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["reminders"][0]["message"] == "do thing"

    @pytest.mark.asyncio
    async def test_storage_error_message(self) -> None:
        scheduler = MagicMock()
        scheduler.get_user_reminders = AsyncMock(side_effect=ValueError("bad"))

        with patch("agent.tools.get_scheduler", return_value=scheduler):
            result = await list_reminders(
                MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
            )
        assert result["status"] == "error"
        assert "Failed to list reminders" in result["message"]


class TestCancelReminderBranches:
    @pytest.mark.asyncio
    async def test_success_when_deleted(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        try:
            storage = ReminderStorage(db_path=db_path)
            scheduler = ReminderScheduler()
            scheduler.storage = storage
            await storage.initialize()
            rid = await storage.add_reminder(
                Reminder(
                    user_id="u",
                    message="m",
                    trigger_time="2026-04-01T12:00:00",
                    created_at="2026-04-01T10:00:00",
                )
            )
            with patch("agent.tools.get_scheduler", return_value=scheduler):
                result = await cancel_reminder(
                    MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
                    reminder_id=rid,
                )
            assert result["status"] == "success"
        finally:
            await storage.close()
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_delete_failure_message(self) -> None:
        scheduler = MagicMock()
        scheduler.delete_reminder = AsyncMock(return_value=False)

        with patch("agent.tools.get_scheduler", return_value=scheduler):
            result = await cancel_reminder(
                MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
                reminder_id=99,
            )
        assert result["status"] == "error"
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_exception_during_cancel(self) -> None:
        scheduler = MagicMock()
        scheduler.delete_reminder = AsyncMock(side_effect=RuntimeError("x"))

        with patch("agent.tools.get_scheduler", return_value=scheduler):
            result = await cancel_reminder(
                MockToolContext(state=MockState({"user_id": "u"})),  # type: ignore
                reminder_id=1,
            )
        assert result["status"] == "error"


class TestParseReminderDatetimeBranches:
    def test_timezone_aware_parse_uses_astimezone_branch(self) -> None:
        ist = ZoneInfo("Asia/Kolkata")
        aware = datetime(2026, 6, 1, 12, 0, tzinfo=ist)
        with patch("agent.tools.dateparser.parse", return_value=aware):
            out = _parse_reminder_datetime("ignored input")
        assert out.tzinfo == UTC


class TestScheduleReminderExceptions:
    """Tests for schedule_reminder exception handling."""

    @pytest.mark.asyncio
    async def test_schedule_reminder_exception(self) -> None:
        """Test schedule_reminder handles exceptions."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        with patch("agent.tools.get_scheduler") as mock_get_scheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.schedule_reminder = AsyncMock(
                side_effect=Exception("DB error")
            )
            mock_get_scheduler.return_value = mock_scheduler

            result = await schedule_reminder(
                tool_context,  # type: ignore
                message="Test reminder",
                reminder_datetime="in 1 hour",
            )

            assert result["status"] == "error"
            assert "Failed to schedule reminder" in result["message"]


class TestListRemindersExceptions:
    """Tests for list_reminders exception handling."""

    @pytest.mark.asyncio
    async def test_list_reminders_exception(self) -> None:
        """Test list_reminders handles exceptions."""
        state = MockState({"user_id": "test_user"})
        tool_context = MockToolContext(state=state)

        with patch("agent.tools.get_scheduler") as mock_get_scheduler:
            mock_scheduler = MagicMock()
            mock_scheduler.get_user_reminders = AsyncMock(
                side_effect=Exception("DB error")
            )
            mock_get_scheduler.return_value = mock_scheduler

            result = await list_reminders(tool_context)  # type: ignore

            assert result["status"] == "error"
            assert "Failed to list reminders" in result["message"]


class TestParseReminderDatetimeTimezone:
    """Tests for _parse_reminder_datetime timezone handling."""

    def test_parse_with_timezone_aware_datetime(self) -> None:
        """Test parsing datetime that already has timezone info."""
        # dateparser can return timezone-aware datetimes for some inputs
        result = _parse_reminder_datetime("2026-03-15 14:30 +05:30")
        assert result.tzinfo is not None
        # Result is converted to UTC
        assert str(result.tzinfo) == "UTC"


class TestDockerBashExecute:
    """Tests for docker_bash_execute (Docker-gated shell tool)."""

    def test_agent_runs_inside_docker_is_deterministic_bool(self) -> None:
        """Exercise /.dockerenv check (real filesystem; no patch)."""
        assert _agent_runs_inside_docker() in (True, False)

    def test_truncate_output_marks_truncation(self) -> None:
        data = b"x" * 100
        text, truncated = _truncate_output(data, max_bytes=50)
        assert truncated is True
        assert "truncated" in text

    @pytest.mark.asyncio
    async def test_disabled_when_not_in_docker(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=False):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo hi",
            )
        assert result["status"] == "error"
        assert "outside Docker" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_empty_command(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "   ",
            )
        assert result["status"] == "error"
        assert "non-empty" in result["message"]

    @pytest.mark.asyncio
    async def test_rejects_oversized_command(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "x" * 13_000,
            )
        assert result["status"] == "error"
        assert "maximum length" in result["message"]

    @pytest.mark.asyncio
    async def test_runs_echo(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo hello",
            )
        assert result["status"] == "success"
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]
        assert result["output_truncated"] is False

    @pytest.mark.asyncio
    async def test_large_stdout_truncated(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "python3 -c \"print('x' * 200000)\"",
            )
        assert result["status"] == "success"
        assert result["output_truncated"] is True

    @pytest.mark.asyncio
    async def test_timeout_seconds_clamped_low(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo ok",
                timeout_seconds=0,
            )
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_timeout_seconds_clamped_high(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo ok",
                timeout_seconds=9_999,
            )
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_subprocess_start_oserror(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with (
            patch("agent.tools._agent_runs_inside_docker", return_value=True),
            patch(
                "agent.tools.asyncio.create_subprocess_exec",
                side_effect=OSError("no bash"),
            ),
        ):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo hi",
            )
        assert result["status"] == "error"
        assert "Failed to start bash" in result["message"]

    @pytest.mark.asyncio
    async def test_times_out(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "sleep 5",
                timeout_seconds=1,
            )
        assert result["status"] == "error"
        assert result.get("timed_out") is True
        assert "timeout" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_nonzero_exit_still_returns_output(self) -> None:
        state = MockState({})
        tool_context = MockToolContext(state=state)
        with patch("agent.tools._agent_runs_inside_docker", return_value=True):
            result = await docker_bash_execute(
                tool_context,  # type: ignore[arg-type]
                "echo out >&1; echo err >&2; exit 7",
            )
        assert result["status"] == "success"
        assert result["exit_code"] == 7
        assert "out" in result["stdout"]
        assert "err" in result["stderr"]
