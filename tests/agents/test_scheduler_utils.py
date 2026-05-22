"""Tests for scheduler_utils (cron / DST / delay / horizon)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from application.agents.scheduler_utils import (
    ScheduleValidationError,
    clamp_once_horizon,
    cron_interval_seconds,
    next_cron_run,
    parse_cron,
    parse_delay,
    parse_run_at,
    resolve_timezone,
)


class TestParseCron:
    def test_valid(self):
        parse_cron("0 9 * * 1")

    def test_invalid(self):
        with pytest.raises(ScheduleValidationError):
            parse_cron("not a cron")

    def test_wrong_field_count(self):
        with pytest.raises(ScheduleValidationError):
            parse_cron("0 9 * *")


class TestNextCronRunDST:
    def test_daily_9am_warsaw_across_spring_forward(self):
        tz = ZoneInfo("Europe/Warsaw")
        before_dst = datetime(2026, 3, 28, 9, 30, tzinfo=tz)
        nxt = next_cron_run("0 9 * * *", "Europe/Warsaw", after=before_dst)
        assert nxt.astimezone(tz) == datetime(2026, 3, 29, 9, 0, tzinfo=tz)

    def test_daily_9am_warsaw_across_fall_back(self):
        tz = ZoneInfo("Europe/Warsaw")
        before_dst = datetime(2026, 10, 24, 9, 30, tzinfo=tz)
        nxt = next_cron_run("0 9 * * *", "Europe/Warsaw", after=before_dst)
        assert nxt.astimezone(tz) == datetime(2026, 10, 25, 9, 0, tzinfo=tz)

    def test_utc_default(self):
        anchor = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
        nxt = next_cron_run("0 * * * *", None, after=anchor)
        assert nxt > anchor
        assert nxt.tzinfo is not None

    def test_returned_value_is_utc(self):
        anchor = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)
        nxt = next_cron_run("0 9 * * *", "Europe/Warsaw", after=anchor)
        assert nxt.tzinfo is not None
        assert nxt.utcoffset() == timedelta(0)


class TestResolveTimezone:
    def test_unknown(self):
        with pytest.raises(ScheduleValidationError):
            resolve_timezone("Atlantis/Nowhere")

    def test_blank_defaults_utc(self):
        assert resolve_timezone("").key == "UTC"
        assert resolve_timezone(None).key == "UTC"


class TestParseDelay:
    @pytest.mark.parametrize(
        "raw,seconds",
        [("30s", 30), ("15m", 900), ("2h", 7200), ("1d", 86_400)],
    )
    def test_units(self, raw, seconds):
        assert parse_delay(raw).total_seconds() == seconds

    def test_uppercase(self):
        assert parse_delay("2H").total_seconds() == 7200

    def test_zero_rejected(self):
        with pytest.raises(ScheduleValidationError):
            parse_delay("0m")

    def test_garbage(self):
        with pytest.raises(ScheduleValidationError):
            parse_delay("two hours")


class TestParseRunAt:
    def test_iso_utc(self):
        parsed = parse_run_at("2026-05-19T12:00:00Z")
        assert parsed.tzinfo is not None
        assert parsed == datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)

    def test_iso_with_offset(self):
        parsed = parse_run_at("2026-05-19T14:00:00+02:00")
        assert parsed == datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)

    def test_naive_uses_tz(self):
        parsed = parse_run_at("2026-05-19T14:00:00", "Europe/Warsaw")
        assert parsed == datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)

    def test_invalid(self):
        with pytest.raises(ScheduleValidationError):
            parse_run_at("not a date")


class TestCronIntervalSeconds:
    def test_every_minute_returns_60s(self):
        assert cron_interval_seconds("* * * * *", None) == 60

    def test_hourly_returns_3600s(self):
        assert cron_interval_seconds("0 * * * *", None) == 3600

    def test_bursty_cron_returns_smallest_gap(self):
        # '* 9 * * *' has 60s gaps inside the 9 AM burst; sampling two adjacent
        # ticks at random can miss them — the rolling window must catch the 60.
        assert cron_interval_seconds("* 9 * * *", None) == 60

    def test_bursty_cron_rejected_when_floor_above_burst(self):
        from application.core.settings import settings as app_settings
        burst = "* 9 * * *"
        cadence = cron_interval_seconds(burst, None)
        floor = max(0, int(app_settings.SCHEDULE_MIN_INTERVAL))
        assert cadence < floor, (
            f"bursty cron {burst!r} cadence {cadence}s must be below the "
            f"configured SCHEDULE_MIN_INTERVAL floor ({floor}s)"
        )


class TestClampOnceHorizon:
    def test_rejects_past(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        with pytest.raises(ScheduleValidationError):
            clamp_once_horizon(past, max_horizon_seconds=3600)

    def test_rejects_beyond_horizon(self):
        far = datetime.now(timezone.utc) + timedelta(days=400)
        with pytest.raises(ScheduleValidationError):
            clamp_once_horizon(far, max_horizon_seconds=365 * 86_400)

    def test_accepts_in_range(self):
        soon = datetime.now(timezone.utc) + timedelta(hours=1)
        clamp_once_horizon(soon, max_horizon_seconds=86_400)
