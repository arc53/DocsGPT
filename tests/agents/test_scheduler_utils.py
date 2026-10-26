"""Tests for scheduler_utils (cron / DST / delay / horizon)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from docsgpt.agents import scheduler_utils
from docsgpt.agents.scheduler_utils import (
    ScheduleValidationError,
    clamp_once_horizon,
    cron_interval_seconds,
    cron_runs,
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


def _one_at_a_time(expression, tz_name, after, until, limit):
    """The reference: ``next_cron_run`` re-anchored at every fire time."""
    out = []
    fire = next_cron_run(expression, tz_name, after=after)
    while fire < until and len(out) < limit:
        out.append(fire)
        fire = next_cron_run(expression, tz_name, after=fire)
    return out


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class TestCronRuns:
    """One iterator over a window, as Calendar and Now expand schedules."""

    @pytest.mark.parametrize(
        "expression",
        ["0 9 * * *", "30 2 * * *", "*/15 * * * *", "* * * * *", "0 1-3 * * *", "0 9 * * 1-5"],
    )
    @pytest.mark.parametrize(
        "tz_name", ["Europe/Warsaw", "America/New_York", "Australia/Lord_Howe", "UTC"]
    )
    @pytest.mark.parametrize(
        "after",
        [
            _utc(2026, 3, 6),  # US spring forward
            _utc(2026, 3, 27),  # EU spring forward
            _utc(2026, 4, 3),  # Lord Howe falls back half an hour
            _utc(2026, 10, 23),  # EU fall back
            _utc(2026, 10, 30),  # US fall back
        ],
    )
    def test_matches_next_cron_run_across_dst(self, expression, tz_name, after):
        until = after + timedelta(days=4)
        expected = _one_at_a_time(expression, tz_name, after, until, 2000)
        assert cron_runs(expression, tz_name, after=after, until=until, limit=2000) == expected

    @pytest.mark.parametrize(
        "expression",
        ["*/5 8-18 * * 1-5", "0 9 1,15 * 1", "0 0 1 * *", "45 23 * * 0", "0,30 * 3 * *"],
    )
    @pytest.mark.parametrize("tz_name", ["Europe/Warsaw", "America/New_York", "Australia/Lord_Howe"])
    @pytest.mark.parametrize(
        "after", [_utc(2026, 3, 1, 7, 13), _utc(2026, 9, 20, 22, 59), _utc(2026, 3, 29, 1, 30)]
    )
    def test_matches_next_cron_run_over_weeks(self, expression, tz_name, after):
        until = after + timedelta(days=45)
        expected = _one_at_a_time(expression, tz_name, after, until, 5000)
        assert cron_runs(expression, tz_name, after=after, until=until, limit=5000) == expected

    def test_a_frequent_cron_walks_the_clock_once_per_day(self):
        # A 15-minute cron over six weeks fires 4,032 times; croniter takes
        # about 17µs a step, and the Calendar expands every schedule a user
        # has. The times of a day repeat on every day without a clock change.
        real = scheduler_utils.croniter.get_next
        steps = []

        def counted(self, *args, **kwargs):
            steps.append(1)
            return real(self, *args, **kwargs)

        after = _utc(2026, 3, 16)
        until = after + timedelta(days=42)  # across the spring-forward night
        expected = _one_at_a_time("*/15 * * * *", "Europe/Warsaw", after, until, 5000)
        with patch.object(scheduler_utils.croniter, "get_next", counted):
            runs = cron_runs("*/15 * * * *", "Europe/Warsaw", after=after, until=until, limit=5000)
        assert runs == expected
        assert len(steps) < 600

    def test_keeps_to_the_window_and_the_limit(self):
        after = _utc(2026, 5, 1, 9)
        runs = cron_runs("0 * * * *", "UTC", after=after, until=_utc(2026, 5, 1, 12), limit=10)
        # Strictly after ``after``: 9:00 itself is not included.
        assert runs == [_utc(2026, 5, 1, 10), _utc(2026, 5, 1, 11)]
        assert len(cron_runs("* * * * *", "UTC", after=after, until=_utc(2026, 5, 2), limit=7)) == 7

    def test_validates_once(self):
        with patch.object(scheduler_utils, "parse_cron", wraps=parse_cron) as parsed:
            runs = cron_runs("* * * * *", "UTC", after=_utc(2026, 5, 1), until=_utc(2026, 5, 2), limit=500)
        assert len(runs) == 500
        assert parsed.call_count == 1

    def test_a_bad_cron_still_raises(self):
        with pytest.raises(ScheduleValidationError):
            cron_runs("not a cron", "UTC", after=_utc(2026, 5, 1), until=_utc(2026, 5, 2), limit=5)
        with pytest.raises(ScheduleValidationError):
            cron_runs("0 9 * * *", "Mars/Olympus", after=_utc(2026, 5, 1), until=_utc(2026, 5, 2), limit=5)


class TestResolveTimezone:
    def test_unknown(self):
        with pytest.raises(ScheduleValidationError):
            resolve_timezone("Atlantis/Nowhere")

    @pytest.mark.parametrize("name", ["America", "Etc", "../x", "/etc/localtime", "Europe/", "x" * 300, "UTC\x00"])
    def test_a_name_zoneinfo_rejects_otherwise_is_unknown(self, name):
        # A directory, a path or an over-long name raises OSError or
        # ValueError, not ZoneInfoNotFoundError; a 400, never a 500.
        with pytest.raises(ScheduleValidationError):
            resolve_timezone(name)

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

    @pytest.mark.parametrize(
        "raw,seconds",
        [
            ("1h20m", 4800),
            ("2d4h", 187_200),
            ("1h 30m", 5400),
            ("1H30M15S", 5415),
            ("90m", 5400),
        ],
    )
    def test_compound(self, raw, seconds):
        assert parse_delay(raw).total_seconds() == seconds

    def test_zero_rejected(self):
        with pytest.raises(ScheduleValidationError):
            parse_delay("0m")

    def test_zero_compound_rejected(self):
        with pytest.raises(ScheduleValidationError):
            parse_delay("0h0m")

    @pytest.mark.parametrize("raw", ["two hours", "", "1h20", "h20m", "1x", "-5m", "1.5h"])
    def test_garbage(self, raw):
        with pytest.raises(ScheduleValidationError):
            parse_delay(raw)

    @pytest.mark.parametrize("raw", ["500000000d500000000d", "999999999999d"])
    def test_too_long_rejected(self, raw):
        with pytest.raises(ScheduleValidationError, match="too long"):
            parse_delay(raw)

    def test_error_names_compound_form(self):
        with pytest.raises(ScheduleValidationError, match="1h30m"):
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
        from docsgpt.core.settings import settings as app_settings
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
