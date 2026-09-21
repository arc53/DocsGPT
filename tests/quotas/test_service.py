"""Tests for QuotaService against a real Postgres instance."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from docsgpt.quotas import providers
from docsgpt.quotas.providers import QuotaDefaultsProvider, register_defaults_provider
from docsgpt.quotas.service import QuotaService
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository

NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
THIS_MONTH = NOW - timedelta(days=2)
LAST_MONTH = NOW - timedelta(days=40)


@pytest.fixture
def conn(pg_conn, monkeypatch):
    @contextmanager
    def _readonly():
        yield pg_conn

    monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _readonly)
    monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "month")
    return pg_conn


@pytest.fixture(autouse=True)
def _restore_provider():
    original = providers.get_defaults_provider()
    yield
    register_defaults_provider(original)


def _use(conn, user_id="u1", tokens=0, cost=0.0, api_key=None, when=THIS_MONTH, source="agent_stream"):
    TokenUsageRepository(conn).insert(
        user_id=user_id, api_key=api_key, prompt_tokens=tokens, cost=cost, timestamp=when, source=source
    )


def _policy(conn, scope, subject_id=None, **fields):
    return QuotaPoliciesRepository(conn).upsert(scope=scope, subject_id=subject_id, **fields)


def _team_with_member(conn, slug, user_id="u1"):
    team_id = str(
        conn.execute(
            text("INSERT INTO teams (name, slug, owner_id) VALUES (:n, :s, 'o') RETURNING id"),
            {"n": slug, "s": slug},
        ).scalar()
    )
    conn.execute(
        text("INSERT INTO team_members (team_id, user_id, role) VALUES (CAST(:t AS uuid), :u, 'team_member')"),
        {"t": team_id, "u": user_id},
    )
    return team_id


class TestCheck:
    def test_no_policies_allows(self, conn):
        _use(conn, tokens=10**9)
        assert QuotaService.check("u1", now=NOW) is None

    def test_no_user_allows(self, conn):
        assert QuotaService.check(None, now=NOW) is None

    def test_under_the_limit_allows(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=99)
        assert QuotaService.check("u1", now=NOW) is None

    def test_reaching_the_token_limit_blocks(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=100)
        exceeded = QuotaService.check("u1", now=NOW)
        assert (exceeded.budget, exceeded.usage, exceeded.limit, exceeded.source) == ("tokens", 100, 100.0, "instance")
        assert exceeded.resets_at == datetime(2026, 10, 1, tzinfo=timezone.utc)

    def test_cost_limit_blocks(self, conn):
        _policy(conn, "user", "u1", cost_limit_usd=1.5)
        _use(conn, cost=1.0)
        _use(conn, cost=0.5)
        exceeded = QuotaService.check("u1", now=NOW)
        assert (exceeded.budget, exceeded.usage, exceeded.source) == ("cost", 1.5, "user")

    def test_zero_limit_blocks_without_usage(self, conn):
        _policy(conn, "user", "u1", token_limit=0)
        assert QuotaService.check("u1", now=NOW).limit == 0

    def test_last_periods_usage_does_not_count(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=500, when=LAST_MONTH)
        assert QuotaService.check("u1", now=NOW) is None

    def test_other_users_usage_does_not_count(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, user_id="u2", tokens=500)
        assert QuotaService.check("u1", now=NOW) is None

    def test_scheduler_rollups_do_not_count(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=60)
        _use(conn, tokens=60, source="schedule")
        assert QuotaService.check("u1", now=NOW) is None

    def test_user_override_lifts_the_instance_limit(self, conn):
        _policy(conn, "instance", token_limit=100)
        _policy(conn, "user", "u1", token_unlimited=True)
        _use(conn, tokens=10**6)
        assert QuotaService.check("u1", now=NOW) is None

    def test_period_setting_moves_the_window(self, conn, monkeypatch):
        monkeypatch.setattr("docsgpt.quotas.service.settings.QUOTA_PERIOD", "day")
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=500, when=NOW - timedelta(days=1))
        assert QuotaService.check("u1", now=NOW) is None
        _use(conn, tokens=500, when=NOW - timedelta(hours=1))
        assert QuotaService.check("u1", now=NOW).resets_at == datetime(2026, 9, 24, tzinfo=timezone.utc)

    def test_unknown_bucket_rejected(self, conn):
        with pytest.raises(ValueError):
            QuotaService.check("u1", bucket="all", now=NOW)

    def test_failure_allows_the_request(self, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("docsgpt.quotas.service.db_readonly", boom)
        assert QuotaService.check("u1", now=NOW) is None


class TestTeams:
    def test_the_most_generous_team_sets_the_allowance(self, conn):
        _policy(conn, "team", _team_with_member(conn, "svc-small"), token_limit=100)
        big = _team_with_member(conn, "svc-big")
        _policy(conn, "team", big, token_limit=1000)
        _use(conn, tokens=500)
        assert QuotaService.check("u1", now=NOW) is None
        _use(conn, tokens=500)
        exceeded = QuotaService.check("u1", now=NOW)
        assert (exceeded.limit, exceeded.source, exceeded.source_id) == (1000.0, "team", big)

    def test_usage_is_one_total_not_one_per_team(self, conn):
        for slug in ("svc-a", "svc-b", "svc-c"):
            _policy(conn, "team", _team_with_member(conn, slug), token_limit=100)
        _use(conn, tokens=100)
        assert QuotaService.check("u1", now=NOW).limit == 100.0

    def test_a_team_only_covers_its_members(self, conn):
        _policy(conn, "instance", token_limit=100)
        _policy(conn, "team", _team_with_member(conn, "svc-vip", user_id="u2"), token_unlimited=True)
        _use(conn, tokens=100)
        assert QuotaService.check("u1", now=NOW).source == "instance"


class TestBuckets:
    def test_bucket_policies_only_see_their_traffic(self, conn):
        _policy(conn, "instance", bucket="agent", token_limit=100)
        _use(conn, tokens=500)
        _use(conn, tokens=90, api_key="k")
        assert QuotaService.check("u1", "direct", now=NOW) is None
        assert QuotaService.check("u1", "agent", now=NOW) is None
        _use(conn, tokens=10, api_key="k")
        exceeded = QuotaService.check("u1", "agent", now=NOW)
        assert (exceeded.bucket, exceeded.usage) == ("agent", 100)
        assert QuotaService.check("u1", "direct", now=NOW) is None

    def test_the_all_bucket_applies_to_both_kinds_of_traffic(self, conn):
        _policy(conn, "instance", token_limit=100)
        _use(conn, tokens=60)
        _use(conn, tokens=60, api_key="k")
        assert QuotaService.check("u1", "direct", now=NOW).bucket == "all"
        assert QuotaService.check("u1", "agent", now=NOW).bucket == "all"


class TestProviderDefaults:
    class _Plan(QuotaDefaultsProvider):
        def default_policies(self, user_id):
            return [{"cost_limit_usd": 5.0}] if user_id == "u1" else []

        def error_payload(self, payload, user_id):
            return {**payload, "error_code": "free-limit-reached"}

    def test_defaults_apply_without_stored_rows(self, conn):
        register_defaults_provider(self._Plan())
        _use(conn, cost=5.0)
        exceeded = QuotaService.check("u1", now=NOW)
        assert exceeded.source == "default"
        assert exceeded.to_payload()["error_code"] == "free-limit-reached"

    def test_a_broken_provider_payload_falls_back(self, conn):
        class _Broken(self._Plan):
            def error_payload(self, payload, user_id):
                raise RuntimeError("nope")

        register_defaults_provider(_Broken())
        _use(conn, cost=5.0)
        assert QuotaService.check("u1", now=NOW).to_payload()["error_code"] == "quota-exceeded"


class TestStatusAndPayload:
    def test_status_reports_limits_and_usage(self, conn):
        _policy(conn, "instance", token_limit=100, cost_limit_usd=2)
        _use(conn, tokens=40, cost=0.5)
        (status,) = QuotaService.status("u1", now=NOW)
        assert status.to_dict() == {
            "bucket": "all",
            "tokens": {"limit": 100, "used": 40, "source": "instance", "source_id": None},
            "cost": {"limit": 2.0, "used": 0.5, "source": "instance", "source_id": None},
            "resets_at": "2026-10-01T00:00:00+00:00",
        }

    def test_unlimited_users_skip_the_usage_query(self, conn, monkeypatch):
        def fail(*args, **kwargs):
            raise AssertionError("usage must not be summed for an unlimited user")

        monkeypatch.setattr(TokenUsageRepository, "usage_totals", fail)
        (status,) = QuotaService.status("u1", now=NOW)
        assert status.limits.unlimited and status.tokens_used == 0

    def test_payload_shape(self, conn):
        _policy(conn, "user", "u1", cost_limit_usd=1)
        _use(conn, cost=1.25)
        exceeded = QuotaService.check("u1", now=NOW)
        payload = exceeded.to_payload()
        assert payload["success"] is False
        assert payload["error_code"] == "quota-exceeded"
        assert (payload["dimension"], payload["unit"]) == ("cost", "USD")
        assert (payload["usage"], payload["limit"]) == (1.25, 1.0)
        assert payload["resets_at"] == "2026-10-01T00:00:00+00:00"
        assert "$1.25 of $1.00" in payload["message"]
        assert exceeded.retry_after_seconds >= 1
