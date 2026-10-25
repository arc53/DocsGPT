"""``agents.config.context_window_limit``: an agent-level cap on the context a request fills."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from docsgpt.api.user.agents.routes import _policy_changed, normalize_agent_config
from docsgpt.core.model_utils import get_context_budget
from docsgpt.guardrails.config import (
    MAX_CONTEXT_WINDOW_LIMIT,
    MIN_CONTEXT_WINDOW_LIMIT,
    AgentConfig,
    context_window_limit_of,
)


@pytest.mark.unit
class TestConfigField:
    def test_defaults_to_none(self):
        assert AgentConfig().context_window_limit is None
        assert normalize_agent_config({})["context_window_limit"] is None

    def test_a_valid_limit_round_trips(self):
        assert normalize_agent_config({"context_window_limit": 32000})["context_window_limit"] == 32000

    def test_null_clears_it(self):
        assert normalize_agent_config({"context_window_limit": None})["context_window_limit"] is None

    @pytest.mark.parametrize("value", [MIN_CONTEXT_WINDOW_LIMIT - 1, 0, -5, MAX_CONTEXT_WINDOW_LIMIT + 1])
    def test_out_of_range_is_rejected_on_write(self, value):
        with pytest.raises(ValueError, match="context_window_limit"):
            normalize_agent_config({"context_window_limit": value})

    def test_a_bool_is_rejected(self):
        with pytest.raises(ValueError):
            normalize_agent_config({"context_window_limit": True})

    def test_the_bounds_are_accepted(self):
        for value in (MIN_CONTEXT_WINDOW_LIMIT, MAX_CONTEXT_WINDOW_LIMIT):
            assert normalize_agent_config({"context_window_limit": value})["context_window_limit"] == value

    def test_lenient_read_drops_a_bad_limit_and_keeps_the_rest(self):
        parsed = AgentConfig.parse({"context_window_limit": 10, "api_write_allowlist": ["t:a"]})
        assert parsed.context_window_limit is None
        assert parsed.api_write_allowlist == ["t:a"]

    def test_lenient_read_keeps_a_good_limit_next_to_a_bad_block(self):
        parsed = AgentConfig.parse({"context_window_limit": 64000, "guardrails": {"mode": "bogus"}})
        assert parsed.context_window_limit == 64000

    def test_changing_it_is_a_policy_change(self):
        existing = {"config": {}}
        assert _policy_changed(existing, {"config": {"context_window_limit": 32000}})
        assert not _policy_changed(existing, {"config": {"context_window_limit": None}})


@pytest.mark.unit
class TestReadLimit:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, None),
            ({}, None),
            ("nope", None),
            ({"context_window_limit": 32000}, 32000),
            ({"context_window_limit": 5}, None),
            ({"context_window_limit": "abc"}, None),
            ({"context_window_limit": True}, None),
            ({"context_window_limit": 32000, "guardrails": {"mode": "bogus"}}, 32000),
        ],
    )
    def test_reads_only_a_valid_limit(self, raw, expected):
        assert context_window_limit_of(raw) == expected


@pytest.mark.unit
class TestContextBudget:
    def test_no_limit_is_the_model_window(self):
        with patch("docsgpt.core.model_utils.get_token_limit", return_value=200000):
            assert get_context_budget("m") == 200000
            assert get_context_budget("m", context_window_limit=None) == 200000

    def test_a_limit_below_the_window_wins(self):
        with patch("docsgpt.core.model_utils.get_token_limit", return_value=200000):
            assert get_context_budget("m", context_window_limit=32000) == 32000

    def test_a_limit_above_the_window_has_no_effect(self):
        with patch("docsgpt.core.model_utils.get_token_limit", return_value=128000):
            assert get_context_budget("m", context_window_limit=1000000) == 128000

    def test_the_byom_scope_is_forwarded(self):
        with patch("docsgpt.core.model_utils.get_token_limit", return_value=8000) as limit:
            assert get_context_budget("m", user_id="owner", context_window_limit=32000) == 8000
        limit.assert_called_once_with("m", user_id="owner")
