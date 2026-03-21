"""Tests for application timezone helpers."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from agent.utils.app_timezone import (
    format_stored_instant_for_display,
    get_app_timezone,
    naive_local_now,
    now_utc,
    utc_iso_seconds,
)


def test_get_app_timezone_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_TIMEZONE", raising=False)
    tz = get_app_timezone()
    assert tz == ZoneInfo("Asia/Kolkata")


def test_get_app_timezone_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TIMEZONE", "UTC")
    assert get_app_timezone() == ZoneInfo("UTC")


def test_naive_local_now_is_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_TIMEZONE", raising=False)
    n = naive_local_now()
    assert n.tzinfo is None


def test_utc_iso_seconds_normalizes() -> None:
    ist = ZoneInfo("Asia/Kolkata")
    dt = datetime(2026, 6, 1, 18, 0, 30, tzinfo=ist)
    s = utc_iso_seconds(dt)
    assert "+00:00" in s


def test_format_stored_instant_for_display_utc_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_TIMEZONE", raising=False)
    out = format_stored_instant_for_display("2026-01-01T00:00:00+00:00")
    assert "2026-01-01" in out
    assert "IST" in out


def test_now_utc_is_aware() -> None:
    n = now_utc()
    assert n.tzinfo == UTC


def test_invalid_agent_timezone_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_TIMEZONE", "Invalid/Timezone")
    assert get_app_timezone() == ZoneInfo("Asia/Kolkata")


def test_blank_agent_timezone_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TIMEZONE", "   ")
    assert get_app_timezone().key == "Asia/Kolkata"


def test_format_stored_instant_shows_non_ist_zone_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_TIMEZONE", "Europe/London")
    out = format_stored_instant_for_display("2026-06-01T12:00:00+00:00")
    assert "Europe/London" in out
    assert "IST" not in out


def test_utc_iso_seconds_accepts_naive_datetime() -> None:
    dt = datetime(2026, 1, 1, 15, 30, 0)
    s = utc_iso_seconds(dt)
    assert "+00:00" in s or "Z" in s


def test_format_stored_instant_treats_naive_iso_as_utc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENT_TIMEZONE", raising=False)
    out = format_stored_instant_for_display("2026-06-01T10:30:00")
    assert "2026-06-01" in out
