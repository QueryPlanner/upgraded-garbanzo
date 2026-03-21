"""Helpers for validating cron expressions and computing next fire times."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger  # type: ignore


@dataclass(frozen=True)
class RecurringSchedule:
    """Declarative recurring schedule metadata (cron + timezone)."""

    cron_expression: str
    description: str
    timezone_name: str


def validate_cron_expression(cron_expression: str, timezone_name: str) -> str:
    """Normalize whitespace, validate tz and 5-field cron; return canonical expr."""
    normalized = " ".join(cron_expression.split())
    tz = ZoneInfo(timezone_name)
    CronTrigger.from_crontab(normalized, timezone=tz)
    return normalized


def get_next_trigger_time(
    cron_expression: str,
    timezone_name: str,
    reference: datetime | None = None,
) -> datetime:
    """Return the next cron fire time strictly after ``reference``, in UTC."""
    normalized = validate_cron_expression(cron_expression, timezone_name)
    tz = ZoneInfo(timezone_name)
    trigger = CronTrigger.from_crontab(normalized, timezone=tz)

    if reference is None:
        now_for_scheduler = datetime.now(UTC)
    elif reference.tzinfo is None:
        now_for_scheduler = reference.replace(tzinfo=UTC)
    else:
        now_for_scheduler = reference

    next_fire = trigger.get_next_fire_time(None, now_for_scheduler)
    if next_fire is None:
        msg = f"No upcoming fire time for cron {normalized!r} in {timezone_name!r}"
        raise ValueError(msg)

    return cast(datetime, next_fire.astimezone(UTC))
