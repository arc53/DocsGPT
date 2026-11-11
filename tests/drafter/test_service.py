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
from docsgpt.drafter.service import parse_messages, prepare, PreparedDraft


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
            refusal = prepare("alice", _body())
        assert refusal.code == "quota"
        limiter.assert_not_called()

    def test_a_request_within_quota_is_counted(self):
        with patch("docsgpt.quotas.service.QuotaService.check", return_value=None), \
                patch("docsgpt.monitors.triggers.rate_limited", return_value=True) as limiter:
            refusal = prepare("alice", _body())
        assert refusal.code == "rate_limited"
        limiter.assert_called_once_with("drafter", "alice", 10)

    def test_a_request_that_passes_carries_what_the_stream_needs(self):
        with patch("docsgpt.quotas.service.QuotaService.check", return_value=None), \
                patch("docsgpt.monitors.triggers.rate_limited", return_value=False):
            prepared = prepare("alice", _body())
        assert isinstance(prepared, PreparedDraft)
        assert prepared.recipe.id == "agent" and prepared.model == {"id": "m"}
        assert prepared.request.user_id == "alice" and prepared.request.recipe == "agent"
        assert prepared.request.messages == [{"role": "user", "content": "x"}]
        assert prepared.request.request_id.startswith("drafter:")


@pytest.fixture
def store(monkeypatch):
    from tests.activity.conftest import FakeRedis

    class _Redis(FakeRedis):
        def get(self, key):
            return self.kv.get(key) if self._alive(key) else None

    fake = _Redis()
    monkeypatch.setattr("docsgpt.drafter.service._turn_store", lambda: fake)
    return fake


@pytest.mark.unit
class TestModelFailures:
    """The last key failure of a task model, remembered for Settings and Admin > Defaults."""

    def test_a_recorded_failure_reads_back_for_its_model(self, store):
        from docsgpt.drafter.service import model_failure, record_model_failure

        record_model_failure("alice", "gpt-a", "model_auth")
        failure = model_failure("alice", "gpt-a")
        assert failure["model_id"] == "gpt-a" and failure["code"] == "model_auth"
        assert failure["at"].endswith("+00:00") or failure["at"].endswith("Z")

    def test_a_failure_of_another_model_reads_as_none(self, store):
        from docsgpt.drafter.service import model_failure, record_model_failure

        record_model_failure("alice", "gpt-a", "model_auth")
        assert model_failure("alice", "gpt-b") is None
        assert model_failure("bob", "gpt-a") is None

    def test_the_instance_keeps_its_own(self, store):
        from docsgpt.drafter.service import model_failure, record_model_failure

        record_model_failure("alice", "gpt-a", "model_auth", instance=True)
        assert model_failure(None, "gpt-a")["model_id"] == "gpt-a"
        assert model_failure("alice", "gpt-a") is not None

    def test_a_success_with_that_model_clears_both(self, store):
        from docsgpt.drafter.service import clear_model_failure, model_failure, record_model_failure

        record_model_failure("alice", "gpt-a", "model_auth", instance=True)
        clear_model_failure("alice", "gpt-b")
        assert model_failure("alice", "gpt-a") is not None
        clear_model_failure("alice", "gpt-a")
        assert model_failure("alice", "gpt-a") is None and model_failure(None, "gpt-a") is None

    def test_forget_drops_the_record(self, store):
        from docsgpt.drafter.service import forget_model_failure, model_failure, record_model_failure

        record_model_failure("alice", "gpt-a", "model_auth", instance=True)
        forget_model_failure("alice")
        forget_model_failure(None)
        assert model_failure("alice", "gpt-a") is None and model_failure(None, "gpt-a") is None

    def test_without_redis_nothing_is_remembered_and_nothing_fails(self, monkeypatch):
        from docsgpt.drafter.service import clear_model_failure, model_failure, record_model_failure

        monkeypatch.setattr("docsgpt.drafter.service._turn_store", lambda: None)
        record_model_failure("alice", "gpt-a", "model_auth")
        clear_model_failure("alice", "gpt-a")
        assert model_failure("alice", "gpt-a") is None


@pytest.mark.unit
class TestBadRequestReason:
    """A refused request says why, so the panel offers Start over only when the conversation is what's refused."""

    def _refusal(self, body):
        with patch.object(settings, "DRAFTER_ENABLED", True):
            refusal = prepare("alice", body)
        return refusal.event()

    @pytest.mark.parametrize("messages", [
        [],
        [{"role": "user", "content": "x"}] * 25,
        [{"role": "robot", "content": "x"}],
        [{"role": "user", "content": 5}],
        [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
        [{"role": "user", "content": "x"}, {"role": "assistant", "content": "​"}, {"role": "user", "content": "z"}],
        [{"role": "assistant", "content": "y" * 200_000}, {"role": "user", "content": "z"}],
    ])
    def test_a_refused_conversation_is_history(self, messages):
        event = self._refusal({"recipe": "agent", "messages": messages})
        assert (event["code"], event["reason"]) == ("bad_request", "history")

    def test_an_empty_last_message_is_empty(self):
        event = self._refusal({"recipe": "agent", "messages": [{"role": "user", "content": "​​"}]})
        assert (event["code"], event["reason"]) == ("bad_request", "empty")

    def test_a_prompt_over_the_read_cap_is_too_long_with_the_limit(self):
        from docsgpt.drafter.prompt_recipe import READ_MAX

        event = self._refusal({"recipe": "prompt", "messages": [{"role": "user", "content": "Improve it"}],
                               "context": {"mode": "improve", "prompt": {"content": "x" * (READ_MAX + 1)}}})
        assert (event["code"], event["reason"], event["limit"]) == ("bad_request", "too_long", READ_MAX)
        assert event["message"]

    @pytest.mark.parametrize("body", [
        ["not an object"],
        {"recipe": "nope", "messages": [{"role": "user", "content": "x"}]},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x"}], "context": 5},
        {"recipe": "agent", "messages": [{"role": "user", "content": "x" * 9000}]},
    ])
    def test_anything_else_is_invalid(self, body):
        event = self._refusal(body)
        assert (event["code"], event["reason"]) == ("bad_request", "invalid") and "limit" not in event

    def test_other_refusals_carry_no_reason(self):
        with patch.object(settings, "DRAFTER_ENABLED", False):
            refusal = prepare("alice", {})
        assert "reason" not in refusal.event()
