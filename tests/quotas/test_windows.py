"""Tests for docsgpt/quotas/windows.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from docsgpt.quotas.windows import window_bounds

UTC = timezone.utc


@pytest.mark.unit
class TestWindowBounds:
    @pytest.mark.parametrize(
        "period, start, end",
        [
            ("day", datetime(2026, 9, 23, tzinfo=UTC), datetime(2026, 9, 24, tzinfo=UTC)),
            ("week", datetime(2026, 9, 21, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC)),
            ("month", datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC)),
        ],
    )
    def test_midweek(self, period, start, end):
        now = datetime(2026, 9, 23, 15, 30, 12, 99, tzinfo=UTC)  # a Wednesday
        assert window_bounds(period, now) == (start, end)

    def test_week_starts_on_monday_itself(self):
        monday = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)
        assert window_bounds("week", monday)[0] == monday

    def test_month_rolls_over_the_year(self):
        start, end = window_bounds("month", datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
        assert (start, end) == (datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))

    def test_leap_february(self):
        start, end = window_bounds("month", datetime(2028, 2, 29, 12, tzinfo=UTC))
        assert (end - start).days == 29

    def test_other_timezones_are_read_in_utc(self):
        tokyo = timezone(timedelta(hours=9))
        # 2026-10-01 08:00 in Tokyo is still 2026-09-30 in UTC.
        start, _ = window_bounds("month", datetime(2026, 10, 1, 8, tzinfo=tokyo))
        assert start == datetime(2026, 9, 1, tzinfo=UTC)

    def test_naive_datetimes_are_utc(self):
        assert window_bounds("day", datetime(2026, 9, 23, 5))[0] == datetime(2026, 9, 23, tzinfo=UTC)

    def test_defaults_to_now(self):
        start, end = window_bounds("day")
        assert start <= datetime.now(UTC) < end

    def test_unknown_period(self):
        with pytest.raises(ValueError):
            window_bounds("year")
