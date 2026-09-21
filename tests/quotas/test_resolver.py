"""Tests for docsgpt/quotas/resolver.py."""

from __future__ import annotations

import pytest

from docsgpt.quotas.resolver import ResolvedLimit, resolve_limits


def _row(scope, subject_id=None, **fields):
    return {"scope": scope, "subject_id": subject_id, "bucket": "all", "enabled": True, **fields}


@pytest.mark.unit
class TestLayers:
    def test_no_rows_is_unlimited(self):
        limits = resolve_limits([])
        assert limits.unlimited
        assert limits.tokens == ResolvedLimit()

    def test_user_beats_team_beats_instance_beats_default(self):
        rows = [
            _row("default", token_limit=1),
            _row("instance", token_limit=10),
            _row("team", "t1", token_limit=100),
            _row("user", "u1", token_limit=5),
        ]
        assert resolve_limits(rows).tokens == ResolvedLimit(5.0, "user")
        assert resolve_limits(rows[:3]).tokens == ResolvedLimit(100.0, "team", "t1")
        assert resolve_limits(rows[:2]).tokens == ResolvedLimit(10.0, "instance")
        assert resolve_limits(rows[:1]).tokens == ResolvedLimit(1.0, "default")

    def test_user_override_can_be_stricter_than_the_team(self):
        rows = [_row("team", "t1", token_unlimited=True), _row("user", "u1", token_limit=0)]
        assert resolve_limits(rows).tokens == ResolvedLimit(0.0, "user")

    def test_user_unlimited_lifts_an_instance_limit(self):
        rows = [_row("instance", token_limit=10), _row("user", "u1", token_unlimited=True)]
        resolved = resolve_limits(rows).tokens
        assert resolved.unlimited and resolved.source == "user"

    def test_budgets_resolve_independently(self):
        rows = [
            _row("instance", token_limit=10, cost_limit_usd=1),
            _row("user", "u1", cost_limit_usd=25),
        ]
        limits = resolve_limits(rows)
        assert limits.tokens == ResolvedLimit(10.0, "instance")
        assert limits.cost == ResolvedLimit(25.0, "user")

    def test_a_row_with_no_opinion_defers(self):
        rows = [_row("instance", token_limit=10), _row("user", "u1", note="vip")]
        assert resolve_limits(rows).tokens == ResolvedLimit(10.0, "instance")

    def test_zero_is_a_limit_not_unlimited(self):
        resolved = resolve_limits([_row("instance", cost_limit_usd=0)]).cost
        assert resolved.limit == 0.0 and not resolved.unlimited


@pytest.mark.unit
class TestMultipleTeams:
    def test_most_generous_team_wins(self):
        rows = [
            _row("team", "small", token_limit=100),
            _row("team", "big", token_limit=900),
            _row("team", "mid", token_limit=500),
        ]
        assert resolve_limits(rows).tokens == ResolvedLimit(900.0, "team", "big")

    def test_an_unlimited_team_beats_any_limit(self):
        rows = [_row("team", "big", token_limit=10**12), _row("team", "free", token_unlimited=True)]
        assert resolve_limits(rows).tokens == ResolvedLimit(None, "team", "free")

    def test_allowances_are_not_added_together(self):
        rows = [_row("team", "a", token_limit=100), _row("team", "b", token_limit=100)]
        assert resolve_limits(rows).tokens.limit == 100.0

    def test_equal_teams_report_a_stable_source(self):
        rows = [_row("team", "b", token_limit=100), _row("team", "a", token_limit=100)]
        assert resolve_limits(rows).tokens.source_id == "a"
        assert resolve_limits(list(reversed(rows))).tokens.source_id == "a"

    def test_each_budget_can_come_from_a_different_team(self):
        rows = [
            _row("team", "tok", token_limit=900, cost_limit_usd=1),
            _row("team", "usd", token_limit=100, cost_limit_usd=50),
        ]
        limits = resolve_limits(rows)
        assert limits.tokens.source_id == "tok"
        assert limits.cost.source_id == "usd"

    def test_a_team_without_an_opinion_does_not_lift_the_limit(self):
        rows = [_row("team", "quiet"), _row("team", "capped", token_limit=100)]
        assert resolve_limits(rows).tokens == ResolvedLimit(100.0, "team", "capped")

    def test_teams_without_opinions_fall_through_to_instance(self):
        rows = [_row("team", "quiet", cost_limit_usd=5), _row("instance", token_limit=10)]
        assert resolve_limits(rows).tokens == ResolvedLimit(10.0, "instance")

    def test_a_zero_team_does_not_block_a_member_of_a_funded_team(self):
        rows = [_row("team", "blocked", token_limit=0), _row("team", "funded", token_limit=50)]
        assert resolve_limits(rows).tokens.limit == 50.0

    def test_disabled_team_rows_are_ignored(self):
        rows = [_row("team", "big", token_limit=900, enabled=False), _row("team", "small", token_limit=100)]
        assert resolve_limits(rows).tokens == ResolvedLimit(100.0, "team", "small")


@pytest.mark.unit
class TestBuckets:
    def test_only_rows_of_the_bucket_apply(self):
        rows = [
            _row("instance", token_limit=10),
            {**_row("instance", token_limit=3), "bucket": "agent"},
        ]
        assert resolve_limits(rows, "all").tokens.limit == 10.0
        assert resolve_limits(rows, "agent").tokens.limit == 3.0
        assert resolve_limits(rows, "direct").unlimited

    def test_decimal_limits_become_floats(self):
        from decimal import Decimal

        resolved = resolve_limits([_row("instance", cost_limit_usd=Decimal("12.5000"))]).cost
        assert resolved.limit == 12.5 and isinstance(resolved.limit, float)
