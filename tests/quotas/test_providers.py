"""Tests for docsgpt/quotas/providers.py."""

from __future__ import annotations

import pytest

from docsgpt.quotas import providers
from docsgpt.quotas.providers import QuotaDefaultsProvider, default_rows, register_defaults_provider
from docsgpt.quotas.resolver import resolve_limits


@pytest.fixture(autouse=True)
def _restore_provider():
    original = providers.get_defaults_provider()
    yield
    register_defaults_provider(original)


class _PlanProvider(QuotaDefaultsProvider):
    def default_policies(self, user_id):
        return [
            {"bucket": "agent", "cost_limit_usd": 5.0, "scope": "user"},
            {"cost_limit_usd": 10.0},
            "ignored",
        ]

    def error_payload(self, payload, user_id):
        return {**payload, "error_code": "free-limit-reached"}


@pytest.mark.unit
class TestDefaultsProvider:
    def test_base_provider_has_no_defaults(self):
        assert default_rows("u1") == []
        assert QuotaDefaultsProvider().error_payload({"a": 1}, "u1") == {"a": 1}

    def test_rows_are_forced_into_the_default_layer(self):
        register_defaults_provider(_PlanProvider())
        rows = default_rows("u1")
        assert [r["scope"] for r in rows] == ["default", "default"]
        assert [r["bucket"] for r in rows] == ["agent", "all"]
        assert resolve_limits(rows, "agent").cost.source == "default"

    def test_stored_rows_win_over_defaults(self):
        register_defaults_provider(_PlanProvider())
        stored = {"scope": "instance", "subject_id": None, "bucket": "all", "enabled": True, "cost_limit_usd": 99}
        assert resolve_limits(default_rows("u1") + [stored]).cost.limit == 99.0
