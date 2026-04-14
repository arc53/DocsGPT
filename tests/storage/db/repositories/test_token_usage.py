"""Tests for TokenUsageRepository against a real Postgres instance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from application.storage.db.repositories.token_usage import TokenUsageRepository

pytestmark = pytest.mark.skipif(
    not __import__("application.core.settings", fromlist=["settings"]).settings.POSTGRES_URI,
    reason="POSTGRES_URI not configured",
)


def _repo(conn) -> TokenUsageRepository:
    return TokenUsageRepository(conn)


def _now():
    return datetime.now(timezone.utc)


class TestInsert:
    def test_inserts_row(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="u1", prompt_tokens=10, generated_tokens=5)
        total = repo.sum_tokens_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), user_id="u1"
        )
        assert total == 15

    def test_insert_with_api_key(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(api_key="key-1", prompt_tokens=20, generated_tokens=10)
        total = repo.sum_tokens_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), api_key="key-1"
        )
        assert total == 30


class TestSumTokensInRange:
    def test_sums_correctly(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="u1", prompt_tokens=10, generated_tokens=5)
        repo.insert(user_id="u1", prompt_tokens=20, generated_tokens=10)
        repo.insert(user_id="u2", prompt_tokens=100, generated_tokens=50)
        total = repo.sum_tokens_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), user_id="u1"
        )
        assert total == 45

    def test_returns_zero_when_no_rows(self, pg_conn):
        repo = _repo(pg_conn)
        total = repo.sum_tokens_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), user_id="nobody"
        )
        assert total == 0

    def test_respects_time_range(self, pg_conn):
        repo = _repo(pg_conn)
        old = _now() - timedelta(hours=48)
        repo.insert(user_id="u1", prompt_tokens=100, generated_tokens=0, timestamp=old)
        repo.insert(user_id="u1", prompt_tokens=10, generated_tokens=0)
        total = repo.sum_tokens_in_range(
            start=_now() - timedelta(hours=1), end=_now() + timedelta(minutes=1), user_id="u1"
        )
        assert total == 10


class TestCountInRange:
    def test_counts_rows(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(user_id="u1", prompt_tokens=1, generated_tokens=1)
        repo.insert(user_id="u1", prompt_tokens=1, generated_tokens=1)
        repo.insert(user_id="u2", prompt_tokens=1, generated_tokens=1)
        count = repo.count_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), user_id="u1"
        )
        assert count == 2

    def test_filters_by_api_key(self, pg_conn):
        repo = _repo(pg_conn)
        repo.insert(api_key="k1", prompt_tokens=1, generated_tokens=1)
        repo.insert(api_key="k2", prompt_tokens=1, generated_tokens=1)
        count = repo.count_in_range(
            start=_now() - timedelta(minutes=1), end=_now() + timedelta(minutes=1), api_key="k1"
        )
        assert count == 1


class TestBucketedTotals:
    def test_day_bucket_sums_per_day(self, pg_conn):
        repo = _repo(pg_conn)
        t1 = datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 10, 23, 30, tzinfo=timezone.utc)
        t3 = datetime(2026, 4, 11, 0, 15, tzinfo=timezone.utc)
        repo.insert(user_id="u-day", prompt_tokens=10, generated_tokens=5, timestamp=t1)
        repo.insert(user_id="u-day", prompt_tokens=20, generated_tokens=7, timestamp=t2)
        repo.insert(user_id="u-day", prompt_tokens=1, generated_tokens=1, timestamp=t3)
        rows = repo.bucketed_totals(
            bucket_unit="day",
            user_id="u-day",
            timestamp_gte=datetime(2026, 4, 10, tzinfo=timezone.utc),
            timestamp_lt=datetime(2026, 4, 12, tzinfo=timezone.utc),
        )
        assert rows == [
            {"bucket": "2026-04-10", "prompt_tokens": 30, "generated_tokens": 12},
            {"bucket": "2026-04-11", "prompt_tokens": 1, "generated_tokens": 1},
        ]

    def test_hour_bucket(self, pg_conn):
        repo = _repo(pg_conn)
        t1 = datetime(2026, 4, 10, 10, 5, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 10, 10, 50, tzinfo=timezone.utc)
        t3 = datetime(2026, 4, 10, 11, 0, tzinfo=timezone.utc)
        repo.insert(user_id="u-hour", prompt_tokens=1, generated_tokens=2, timestamp=t1)
        repo.insert(user_id="u-hour", prompt_tokens=3, generated_tokens=4, timestamp=t2)
        repo.insert(user_id="u-hour", prompt_tokens=5, generated_tokens=6, timestamp=t3)
        rows = repo.bucketed_totals(bucket_unit="hour", user_id="u-hour")
        buckets = {r["bucket"]: r for r in rows}
        assert buckets["2026-04-10 10:00"]["prompt_tokens"] == 4
        assert buckets["2026-04-10 10:00"]["generated_tokens"] == 6
        assert buckets["2026-04-10 11:00"]["prompt_tokens"] == 5

    def test_minute_bucket(self, pg_conn):
        repo = _repo(pg_conn)
        t1 = datetime(2026, 4, 10, 10, 5, 15, tzinfo=timezone.utc)
        t2 = datetime(2026, 4, 10, 10, 5, 45, tzinfo=timezone.utc)
        repo.insert(user_id="u-min", prompt_tokens=1, generated_tokens=2, timestamp=t1)
        repo.insert(user_id="u-min", prompt_tokens=3, generated_tokens=4, timestamp=t2)
        rows = repo.bucketed_totals(bucket_unit="minute", user_id="u-min")
        assert len(rows) == 1
        assert rows[0]["bucket"] == "2026-04-10 10:05:00"
        assert rows[0]["prompt_tokens"] == 4
        assert rows[0]["generated_tokens"] == 6

    def test_filters_by_api_key(self, pg_conn):
        repo = _repo(pg_conn)
        t = datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
        repo.insert(api_key="dash-key", prompt_tokens=1, generated_tokens=1, timestamp=t)
        repo.insert(api_key="other-key", prompt_tokens=99, generated_tokens=99, timestamp=t)
        rows = repo.bucketed_totals(bucket_unit="day", api_key="dash-key")
        assert len(rows) == 1
        assert rows[0]["prompt_tokens"] == 1

    def test_rejects_invalid_bucket_unit(self, pg_conn):
        repo = _repo(pg_conn)
        with pytest.raises(ValueError):
            repo.bucketed_totals(bucket_unit="week")

    def test_respects_timestamp_range(self, pg_conn):
        repo = _repo(pg_conn)
        inside = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
        outside = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        repo.insert(user_id="u-range", prompt_tokens=10, generated_tokens=0, timestamp=inside)
        repo.insert(user_id="u-range", prompt_tokens=99, generated_tokens=0, timestamp=outside)
        rows = repo.bucketed_totals(
            bucket_unit="day",
            user_id="u-range",
            timestamp_gte=datetime(2026, 4, 10, tzinfo=timezone.utc),
            timestamp_lt=datetime(2026, 4, 11, tzinfo=timezone.utc),
        )
        assert len(rows) == 1
        assert rows[0]["prompt_tokens"] == 10
