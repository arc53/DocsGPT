"""Checking a draft request before it streams: what the client sends back, rate and quota."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docsgpt.core.settings import settings
from docsgpt.drafter.catalog import Workspace
from docsgpt.drafter.prompt_recipe import CONTENT_MAX, MAX_EDITS, parse_context, validate
from docsgpt.drafter.recipe import DraftRequest
from docsgpt.drafter.service import parse_messages, prepare


def _echo(event: dict) -> str:
    """The event as the panel sends it back (``JSON.stringify``: no spaces, non-ASCII kept)."""
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def _rewrite_event() -> dict:
    """A near-total rewrite of a prompt at the size cap, in text that JSON escapes (quotes, line breaks)."""
    chunk = CONTENT_MAX // MAX_EDITS
    line = 'Say "hi" first.\n'
    current = "".join(f"{i:02d}" + (line * chunk)[: chunk - 2] for i in range(MAX_EDITS))
    edits = []
    for i in range(MAX_EDITS):
        find = current[i * chunk:(i + 1) * chunk]
        edits.append({"find": find, "replace": find.replace("hi", "Hi"), "reason": "r" * 300})
    context = parse_context({"mode": "improve", "prompt": {"id": "p1", "name": "P", "content": current}})
    req = DraftRequest("alice", "prompt", [{"role": "user", "content": "Rewrite it"}], context, "drafter:t")
    proposal = validate({"message": "m" * 600, "edits": edits, "warnings": ["w" * 300] * 3,
                         "suggestions": ["s" * 120] * 3}, req, Workspace())
    return {"type": "proposal", "proposal": proposal}


@pytest.mark.unit
class TestEcho:
    def test_the_largest_proposal_comes_back_whole(self):
        echoed = _echo(_rewrite_event())
        messages = parse_messages([
            {"role": "user", "content": "Rewrite it"},
            {"role": "assistant", "content": echoed},
            {"role": "user", "content": "Shorter"},
        ])
        assert json.loads(messages[1]["content"]) == json.loads(echoed)


def _body() -> dict:
    return {"recipe": "agent", "messages": [{"role": "user", "content": "x"}], "context": {}}


@pytest.mark.unit
class TestRateAndQuota:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setattr(settings, "DRAFTER_ENABLED", True)
        monkeypatch.setattr(settings, "DRAFTER_RATE_LIMIT_PER_MINUTE", 10)
        with patch("docsgpt.drafter.service.drafter_model", return_value={"id": "m"}):
            yield

    def test_a_request_refused_for_quota_uses_no_rate_budget(self):
        exceeded = SimpleNamespace(to_payload=lambda: {"message": "Usage quota reached."})
        with patch("docsgpt.quotas.service.QuotaService.check", return_value=exceeded), \
                patch("docsgpt.monitors.triggers.rate_limited") as limiter:
            refusal, *_ = prepare("alice", _body())
        assert refusal.code == "quota"
        limiter.assert_not_called()

    def test_a_request_within_quota_is_counted(self):
        with patch("docsgpt.quotas.service.QuotaService.check", return_value=None), \
                patch("docsgpt.monitors.triggers.rate_limited", return_value=True) as limiter:
            refusal, *_ = prepare("alice", _body())
        assert refusal.code == "rate_limited"
        limiter.assert_called_once_with("drafter", "alice", 10)
