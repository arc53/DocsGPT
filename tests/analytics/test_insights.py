"""The insights series' bucket unit and how fine buckets merge into coarser ones."""

import pytest

from docsgpt.analytics import insights


class TestBucketUnit:
    def test_keeps_the_filters_unit_while_its_buckets_average_the_sample_floor(self):
        days = [f"2026-10-{day:02d}" for day in range(1, 8)]
        assert insights.bucket_unit("day", days, insights.MIN_SAMPLE * len(days)) == "day"

    @pytest.mark.parametrize(("unit", "coarser"), [("minute", "hour"), ("hour", "day"), ("day", "week")])
    def test_coarsens_one_step_when_too_few_items_fill_them(self, unit, coarser):
        assert insights.bucket_unit(unit, ["a", "b", "c"], 29) == coarser

    def test_a_week_is_as_coarse_as_it_gets(self):
        assert insights.bucket_unit("week", ["2026-10-05"], 0) == "week"


class TestCoarseKey:
    def test_minute_to_hour_and_hour_to_day(self):
        assert insights.coarse_key("2026-10-24 13:05:00", "hour") == "2026-10-24 13:00"
        assert insights.coarse_key("2026-10-24 13:00", "day") == "2026-10-24"

    def test_a_day_to_its_weeks_monday(self):
        assert insights.coarse_key("2026-10-24", "week") == "2026-10-19"
        assert insights.coarse_key("2026-10-19", "week") == "2026-10-19"


class TestRebucket:
    def test_merges_days_into_weeks_clipped_to_the_window(self):
        days = ["2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"]
        counts = [
            {"bucket": "2026-09-25", "label": "sentiment", "n": 2},
            {"bucket": "2026-09-28", "label": "sentiment", "n": 1},
            {"bucket": "2026-09-30", "label": "sentiment", "n": 4},
        ]
        sums = [
            {"bucket": "2026-09-25", "label": "sentiment", "option": "0", "expected": 0.5},
            {"bucket": "2026-09-28", "label": "sentiment", "option": "0", "expected": 0.25},
            {"bucket": "2026-09-30", "label": "sentiment", "option": "2", "expected": 3.0},
        ]
        buckets, ends, merged_counts, merged_sums = insights.rebucket(days, counts, sums, "week")
        # The window opens on a Friday: its first week runs Fri–Sun, named by its first day.
        assert buckets == ["2026-09-25", "2026-09-28"]
        assert ends == {"2026-09-25": "2026-09-27", "2026-09-28": "2026-09-30"}
        assert sorted((row["bucket"], row["n"]) for row in merged_counts) == [("2026-09-25", 2), ("2026-09-28", 5)]
        assert sorted((row["bucket"], row["option"], row["expected"]) for row in merged_sums) == [
            ("2026-09-25", "0", 0.5), ("2026-09-28", "0", 0.25), ("2026-09-28", "2", 3.0)]

    def test_series_carries_each_buckets_last_day(self):
        series = insights.series(
            ["2026-09-25"], ["sentiment"], [{"bucket": "2026-09-25", "label": "sentiment", "n": 3}],
            [{"bucket": "2026-09-25", "label": "sentiment", "option": "0", "expected": 0.75}],
            {"sentiment": ["negative", "neutral", "positive"]}, ends={"2026-09-25": "2026-09-27"},
        )
        assert series == [{"bucket": "2026-09-25", "bucket_end": "2026-09-27", "labels": {
            "sentiment": {"n": 3, "options": {"negative": 0.75, "neutral": 0.0, "positive": 0.0}}}}]

    def test_hours_merge_into_their_day_by_key(self):
        hours = ["2026-10-23 22:00", "2026-10-23 23:00", "2026-10-24 00:00"]
        counts = [{"bucket": hour, "label": "reaction", "n": 1} for hour in hours]
        buckets, ends, merged, _ = insights.rebucket(hours, counts, [], "day")
        assert buckets == ["2026-10-23", "2026-10-24"]
        assert ends == {}
        assert sorted((row["bucket"], row["n"]) for row in merged) == [("2026-10-23", 2), ("2026-10-24", 1)]
