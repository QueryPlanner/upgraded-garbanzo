"""Unit tests for recurring reminder helpers."""

from datetime import UTC, datetime

import pytest

from agent.reminders.recurrence import (
    get_next_trigger_time,
    validate_cron_expression,
)


class TestValidateCronExpression:
    """Tests for cron rule validation."""

    def test_normalizes_spacing(self) -> None:
        normalized = validate_cron_expression("*/15   *  * * *", "Asia/Kolkata")
        assert normalized == "*/15 * * * *"

    def test_invalid_expression_raises_error(self) -> None:
        with pytest.raises(ValueError):
            validate_cron_expression("not-a-cron", "Asia/Kolkata")


class TestGetNextTriggerTime:
    """Tests for recurring next-fire calculation."""

    def test_returns_future_utc_time(self) -> None:
        reference_time = datetime(2026, 3, 20, 12, 7, tzinfo=UTC)
        next_trigger_time = get_next_trigger_time(
            "*/15 * * * *",
            "Asia/Kolkata",
            reference_time=reference_time,
        )

        assert next_trigger_time.tzinfo == UTC
        assert next_trigger_time > reference_time
        assert next_trigger_time.minute in {0, 15, 30, 45}

    def test_accepts_naive_reference_time(self) -> None:
        next_trigger_time = get_next_trigger_time(
            "0 9 * * *",
            "America/New_York",
            reference_time=datetime(2026, 3, 20, 12, 0, 0),
        )

        assert next_trigger_time.tzinfo == UTC
