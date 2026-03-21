"""Tests for recurring reminder schedule helpers."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from zoneinfo import ZoneInfoNotFoundError

import pytest

from agent.reminders.recurrence import (
    RecurringSchedule,
    get_next_trigger_time,
    validate_cron_expression,
)


class TestValidateCronExpression:
    """Tests for validate_cron_expression function."""

    def test_validates_standard_cron(self) -> None:
        """Test validation of a standard cron expression."""
        result = validate_cron_expression("*/15 * * * *", "UTC")
        assert result == "*/15 * * * *"

    def test_normalizes_whitespace(self) -> None:
        """Test that extra whitespace is normalized."""
        result = validate_cron_expression("  */15   * * * *  ", "UTC")
        assert result == "*/15 * * * *"

    def test_validates_with_timezone(self) -> None:
        """Test validation with a specific timezone."""
        result = validate_cron_expression("0 9 * * 1-5", "Asia/Kolkata")
        assert result == "0 9 * * 1-5"

    def test_raises_for_invalid_cron(self) -> None:
        """Test that invalid cron raises ValueError."""
        with pytest.raises(ValueError):
            validate_cron_expression("invalid cron", "UTC")

    def test_raises_for_invalid_timezone(self) -> None:
        """Test that invalid timezone raises exception."""
        with pytest.raises(ZoneInfoNotFoundError):
            validate_cron_expression("*/15 * * * *", "Invalid/Timezone")


class TestGetNextTriggerTime:
    """Tests for get_next_trigger_time function."""

    def test_returns_datetime(self) -> None:
        """Test that a datetime is returned."""
        result = get_next_trigger_time("*/15 * * * *", "UTC")
        assert isinstance(result, datetime)

    def test_returns_aware_datetime(self) -> None:
        """Test that returned datetime is timezone-aware."""
        result = get_next_trigger_time("*/15 * * * *", "UTC")
        assert result.tzinfo is not None

    def test_returns_utc_datetime(self) -> None:
        """Test that returned datetime is in UTC."""
        result = get_next_trigger_time("*/15 * * * *", "UTC")
        assert result.tzinfo == UTC

    def test_with_reference_time(self) -> None:
        """Test with explicit reference time."""
        reference_time = datetime(2026, 3, 21, 10, 0, tzinfo=UTC)
        result = get_next_trigger_time("0 12 * * *", "UTC", reference_time)
        # Next 12:00 UTC after 10:00 UTC same day
        assert result.hour == 12
        assert result.day == 21

    def test_with_naive_reference_time(self) -> None:
        """Test with naive reference time (should be treated as UTC)."""
        reference_time = datetime(2026, 3, 21, 10, 0)  # No tzinfo
        result = get_next_trigger_time("0 12 * * *", "UTC", reference_time)
        assert result.tzinfo == UTC

    def test_with_timezone_conversion(self) -> None:
        """Test that timezone conversion is applied correctly."""
        # 9 AM IST = 3:30 AM UTC (IST is UTC+5:30)
        reference_time = datetime(2026, 3, 21, 3, 0, tzinfo=UTC)
        # This cron runs at 9 AM IST
        result = get_next_trigger_time("0 9 * * *", "Asia/Kolkata", reference_time)
        # Should be 9 AM IST = 3:30 AM UTC
        assert result.hour == 3
        assert result.minute == 30

    def test_returns_future_time(self) -> None:
        """Test that returned time is in the future."""
        now = datetime.now(UTC)
        result = get_next_trigger_time("*/15 * * * *", "UTC")
        assert result > now

    def test_hourly_schedule(self) -> None:
        """Test hourly schedule returns next hour."""
        reference_time = datetime(2026, 3, 21, 10, 30, tzinfo=UTC)
        result = get_next_trigger_time("0 * * * *", "UTC", reference_time)
        assert result.hour == 11
        assert result.minute == 0

    def test_future_utc_with_kolkata_reference(self) -> None:
        """Next fire after a UTC reference in another timezone's cron."""
        reference_time = datetime(2026, 3, 20, 12, 7, tzinfo=UTC)
        next_trigger_time = get_next_trigger_time(
            "*/15 * * * *",
            "Asia/Kolkata",
            reference_time=reference_time,
        )

        assert next_trigger_time.tzinfo == UTC
        assert next_trigger_time > reference_time
        assert next_trigger_time.minute in {0, 15, 30, 45}

    def test_accepts_naive_reference_for_ny_cron(self) -> None:
        """Naive reference is treated as UTC before local cron evaluation."""
        next_trigger_time = get_next_trigger_time(
            "0 9 * * *",
            "America/New_York",
            reference_time=datetime(2026, 3, 20, 12, 0, 0),
        )

        assert next_trigger_time.tzinfo == UTC


class TestRecurringSchedule:
    """Tests for RecurringSchedule dataclass."""

    def test_creates_schedule(self) -> None:
        """Test creating a recurring schedule."""
        schedule = RecurringSchedule(
            cron_expression="*/15 * * * *",
            description="every 15 minutes",
            timezone_name="UTC",
        )
        assert schedule.cron_expression == "*/15 * * * *"
        assert schedule.description == "every 15 minutes"
        assert schedule.timezone_name == "UTC"

    def test_is_frozen(self) -> None:
        """Test that RecurringSchedule is immutable."""
        schedule = RecurringSchedule(
            cron_expression="*/15 * * * *",
            description="every 15 minutes",
            timezone_name="UTC",
        )
        with pytest.raises(FrozenInstanceError):
            schedule.cron_expression = "0 * * * *"  # type: ignore
