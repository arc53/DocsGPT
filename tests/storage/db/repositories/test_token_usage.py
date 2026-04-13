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
