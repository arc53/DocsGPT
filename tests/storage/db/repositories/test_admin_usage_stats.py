"""Repository tests for admin spend, latency and the per-user drill-down."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.admin_stats import AdminStatsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository


pytestmark = pytest.mark.integration


def _insert(conn, **fields):
    defaults = {
        "user_id": "u1",
        "prompt_tokens": 100,
        "generated_tokens": 20,
        "cost": 0.5,
        "source": "agent_stream",
        "model_id": "gpt-x",
        "cached_tokens": None,
        "duration_ms": None,
        "ttft_ms": None,
        "timestamp": datetime.now(timezone.utc),
    }
    defaults.update(fields)
    conn.execute(
        text(
            "INSERT INTO token_usage (user_id, prompt_tokens, generated_tokens, "
            "cost, source, model_id, cached_tokens, duration_ms, ttft_ms, timestamp) "
            "VALUES (:user_id, :prompt_tokens, :generated_tokens, :cost, :source, "
            ":model_id, :cached_tokens, :duration_ms, :ttft_ms, :timestamp)"
        ),
        defaults,
    )


@pytest.fixture()
def since():
    return datetime.now(timezone.utc) - timedelta(days=7)


class TestBucketedCost:
    def test_buckets_carry_cost_alongside_tokens(self, pg_conn, since):
        _insert(pg_conn, cost=1.25)
        _insert(pg_conn, cost=0.75)
        series = TokenUsageRepository(pg_conn).bucketed_totals(
            bucket_unit="day", timestamp_gte=since
        )
        assert len(series) == 1
        assert series[0]["cost"] == pytest.approx(2.0)
        assert series[0]["prompt_tokens"] == 200

    def test_unreported_cache_bins_stay_unknown(self, pg_conn, since):
        """NULL means the provider said nothing, which is not the same as 0."""
        _insert(pg_conn, cached_tokens=None)
        series = TokenUsageRepository(pg_conn).bucketed_totals(
            bucket_unit="day", timestamp_gte=since
        )
        assert series[0]["cached_tokens"] is None

    def test_reported_cache_bins_sum(self, pg_conn, since):
        _insert(pg_conn, cached_tokens=30)
        _insert(pg_conn, cached_tokens=None)
        series = TokenUsageRepository(pg_conn).bucketed_totals(
            bucket_unit="day", timestamp_gte=since
        )
        assert series[0]["cached_tokens"] == 30

    def test_grouping_keeps_cost_per_group(self, pg_conn, since):
        _insert(pg_conn, model_id="cheap", cost=0.1)
        _insert(pg_conn, model_id="pricey", cost=9.9)
        series = TokenUsageRepository(pg_conn).bucketed_totals(
            bucket_unit="day", timestamp_gte=since, group_by="model"
        )
        costs = {row["group_key"]: row["cost"] for row in series}
        assert costs == {"cheap": pytest.approx(0.1), "pricey": pytest.approx(9.9)}


class TestTopUsers:
    def test_reports_spend_next_to_tokens(self, pg_conn, since):
        _insert(pg_conn, user_id="heavy", prompt_tokens=1000, cost=2.0)
        _insert(pg_conn, user_id="light", prompt_tokens=10, cost=0.1)
        rows = AdminStatsRepository(pg_conn).top_token_users(since=since)
        assert [row["user_id"] for row in rows] == ["heavy", "light"]
        assert rows[0]["cost"] == pytest.approx(2.0)

    def test_rollup_rows_are_not_billed_twice(self, pg_conn, since):
        _insert(pg_conn, user_id="u1", source="agent_stream", cost=1.0)
        _insert(pg_conn, user_id="u1", source="schedule", cost=1.0)
        rows = AdminStatsRepository(pg_conn).top_token_users(since=since)
        assert rows[0]["cost"] == pytest.approx(1.0)


class TestLatencySummary:
    def test_percentiles_over_measured_calls(self, pg_conn, since):
        for duration in (100, 200, 300, 400):
            _insert(pg_conn, duration_ms=duration, ttft_ms=duration // 10)
        summary = AdminStatsRepository(pg_conn).latency_summary(since=since)
        assert summary["samples"] == 4
        assert summary["p50_ms"] == 250
        assert summary["p95_ms"] == 385
        assert summary["ttft_p50_ms"] == 25

    def test_unmeasured_rows_are_skipped_not_counted_as_zero(self, pg_conn, since):
        _insert(pg_conn, duration_ms=1000, ttft_ms=None)
        _insert(pg_conn, duration_ms=None, ttft_ms=None)
        summary = AdminStatsRepository(pg_conn).latency_summary(since=since)
        assert summary["samples"] == 1
        assert summary["p50_ms"] == 1000
        # A stream that never yielded contributes no first-token sample.
        assert summary["ttft_samples"] == 0
        assert summary["ttft_p50_ms"] is None

    def test_no_data_reports_no_samples(self, pg_conn, since):
        summary = AdminStatsRepository(pg_conn).latency_summary(since=since)
        assert summary == {
            "samples": 0,
            "p50_ms": None,
            "p95_ms": None,
            "ttft_samples": 0,
            "ttft_p50_ms": None,
        }


class TestUserUsageBreakdown:
    def test_totals_and_splits(self, pg_conn, since):
        _insert(pg_conn, user_id="u1", model_id="a", source="agent_stream", cost=1.0)
        _insert(pg_conn, user_id="u1", model_id="b", source="webhook", cost=2.0)
        _insert(pg_conn, user_id="other", model_id="a", cost=99.0)
        detail = AdminStatsRepository(pg_conn).user_usage_breakdown("u1", since=since)
        assert detail["totals"]["calls"] == 2
        assert detail["totals"]["cost"] == pytest.approx(3.0)
        assert {row["key"] for row in detail["by_model"]} == {"a", "b"}
        assert {row["key"] for row in detail["by_source"]} == {
            "agent_stream",
            "webhook",
        }

    def test_rollup_rows_are_not_billed_twice(self, pg_conn, since):
        """A scheduled run's rollup duplicates its own per-call rows."""
        _insert(pg_conn, user_id="u1", source="agent_stream", cost=1.0)
        _insert(pg_conn, user_id="u1", source="schedule", cost=1.0)
        detail = AdminStatsRepository(pg_conn).user_usage_breakdown("u1", since=since)
        assert detail["totals"]["calls"] == 1
        assert detail["totals"]["cost"] == pytest.approx(1.0)
        assert [row["key"] for row in detail["by_source"]] == ["agent_stream"]

    def test_a_user_with_no_usage_reports_zeroes(self, pg_conn, since):
        detail = AdminStatsRepository(pg_conn).user_usage_breakdown("ghost", since=since)
        assert detail["totals"] == {"tokens": 0, "cost": 0.0, "calls": 0}
        assert detail["by_model"] == [] and detail["by_source"] == []

    def test_window_is_respected(self, pg_conn, since):
        _insert(
            pg_conn,
            user_id="u1",
            timestamp=datetime.now(timezone.utc) - timedelta(days=30),
        )
        detail = AdminStatsRepository(pg_conn).user_usage_breakdown("u1", since=since)
        assert detail["totals"]["calls"] == 0
