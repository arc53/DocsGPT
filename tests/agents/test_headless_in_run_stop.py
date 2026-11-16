"""A headless run stopped mid-way by a limit returns an outcome that says which limit, keeping what it did.

``run_agent_headless`` opens the run's limits with its billing, so each model call of a scheduled, webhook or
continuation run is checked. A stop is not an exception for its caller: the outcome carries the partial answer and
tool calls, ``error_type`` ``payer_out_of_allowance`` (the payer's allowance) or ``budget_exceeded`` (the agent's
own limit), and the message as ``error``. It is never worded as a time limit.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.quotas.agent_limits import AgentLimitExceeded
from docsgpt.quotas.payer import current_run_billing
from docsgpt.quotas.run_limits import RunLimitReached, RunLimits
from docsgpt.quotas.service import QuotaExceeded

RESETS_AT = datetime.now(timezone.utc) + timedelta(days=10)


def _allowance_stop(outside: bool = False) -> RunLimitReached:
    exceeded = QuotaExceeded(
        user_id="dana", bucket="all", budget="tokens", usage=120, limit=100, source="user", source_id=None,
        resets_at=RESETS_AT,
    )
    return RunLimitReached(exceeded, outside=outside)


def _agent_stop() -> RunLimitReached:
    return RunLimitReached(AgentLimitExceeded(agent_id="agent-1", dimension="tokens", usage=150, limit=100))


def _run(monkeypatch, gen, *, endpoint="schedule", config=None, seen=None, **kwargs):
    """Drive ``run_agent_headless`` over an agent whose ``gen`` is ``gen``."""
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    agent.gen.side_effect = lambda **_kw: gen()
    agent.llm.token_usage = {"prompt_tokens": 7, "generated_tokens": 0}
    retriever = MagicMock(name="retriever")
    retriever.search.return_value = []
    executor = MagicMock(name="tool_executor", headless_denials=[])
    executor.get_truncated_tool_calls.return_value = [{"call_id": "c1", "tool_name": "search", "status": "done"}]

    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever))
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: executor)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)

    started = {}

    def _start(payer, **start_kwargs):
        started.update(payer=payer, **start_kwargs)
        return RunLimits(payer, outside=start_kwargs.get("outside", False))

    monkeypatch.setattr(hr.RunLimits, "start", staticmethod(_start))
    if seen is not None:
        seen["started"] = started
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        return hr.run_agent_headless(
            config or {"user_id": "owner", "id": "agent-1", "default_model_id": "m"},
            "do the thing",
            endpoint=endpoint,
            **kwargs,
        )


@pytest.mark.unit
class TestTheOutcome:
    def test_the_payers_allowance_stops_the_run_with_its_partial_answer(self, monkeypatch):
        def gen():
            yield {"answer": "Half of the report"}
            yield {"type": "tool_call", "data": {"call_id": "c1"}}
            raise _allowance_stop()

        outcome = _run(monkeypatch, gen, payer="dana")

        assert outcome["error_type"] == "payer_out_of_allowance"
        assert outcome["answer"] == "Half of the report"
        assert outcome["tool_calls"] == [{"call_id": "c1", "tool_name": "search", "status": "done"}]
        assert "quota" in outcome["error"].lower()
        assert "time limit" not in outcome["error"].lower()

    def test_the_agent_limit_stops_the_run_as_budget_exceeded(self, monkeypatch):
        def gen():
            yield {"answer": "Started"}
            raise _agent_stop()

        outcome = _run(monkeypatch, gen, payer="dana")

        assert outcome["error_type"] == "budget_exceeded"
        assert outcome["answer"] == "Started"
        assert "agent's token limit" in outcome["error"]

    @pytest.mark.parametrize("endpoint", ["schedule", "webhook", "continuation"])
    def test_every_headless_caller_gets_the_outcome_and_none_says_time_limit(self, monkeypatch, endpoint):
        def gen():
            yield {"answer": "Partial"}
            raise _allowance_stop()

        outcome = _run(monkeypatch, gen, endpoint=endpoint, payer="dana")

        assert outcome["error_type"] == "payer_out_of_allowance"
        assert outcome["error_type"] != "TimeLimit"
        assert outcome["answer"] == "Partial"

    def test_a_stop_a_workflow_step_swallowed_is_still_named(self, monkeypatch):
        """A workflow engine turns a failed step into an error event; the run's limits remember the stop."""

        def gen():
            yield {"answer": "Step one done"}
            current_run_billing().limits.reached = _allowance_stop()
            yield {"type": "error", "error": "Rate limit exceeded. Please wait a moment before trying again."}

        outcome = _run(monkeypatch, gen, payer="dana")

        assert outcome["error_type"] == "payer_out_of_allowance"
        assert outcome["answer"] == "Step one done"

    def test_an_outside_runs_stop_does_not_carry_the_payers_numbers(self, monkeypatch):
        def gen():
            yield {"answer": "Partial"}
            raise _allowance_stop(outside=True)

        outcome = _run(monkeypatch, gen, endpoint="webhook", payer="dana")

        assert outcome["error_type"] == "payer_out_of_allowance"
        assert "120" not in outcome["error"] and "100" not in outcome["error"]
        assert "paused" in outcome["error"]


@pytest.mark.unit
class TestTheRunOpensItsLimits:
    def test_a_schedule_checks_the_setter_in_the_agent_bucket(self, monkeypatch):
        seen = {}
        billing = {}

        def gen():
            billing["limits"] = current_run_billing().limits
            yield {"answer": "ok"}

        outcome = _run(monkeypatch, gen, payer="dana", seen=seen)

        assert outcome["error_type"] is None
        assert seen["started"]["payer"] == "dana"
        assert seen["started"]["bucket"] == "agent"
        assert seen["started"]["outside"] is False
        assert billing["limits"].payer == "dana"

    def test_a_webhook_is_outside_traffic(self, monkeypatch):
        seen = {}
        _run(monkeypatch, lambda: iter([{"answer": "ok"}]), endpoint="webhook", payer="dana", seen=seen)
        assert seen["started"]["outside"] is True

    def test_the_agent_row_is_passed_so_no_extra_read_is_needed(self, monkeypatch):
        seen = {}
        config = {"user_id": "owner", "id": "agent-1", "default_model_id": "m", "limited_token_mode": True,
                  "token_limit": 10}
        _run(monkeypatch, lambda: iter([{"answer": "ok"}]), config=config, payer="dana", seen=seen)
        assert seen["started"]["agent"]["token_limit"] == 10


@pytest.mark.unit
class TestTheWebhookTask:
    @pytest.fixture
    def worker_db(self, pg_conn, monkeypatch):
        @contextmanager
        def _use():
            yield pg_conn

        monkeypatch.setattr("docsgpt.worker.db_session", _use)
        monkeypatch.setattr("docsgpt.worker.db_readonly", _use)
        return pg_conn

    @pytest.mark.parametrize("error_type", ["payer_out_of_allowance", "budget_exceeded"])
    def test_a_stop_mid_run_returns_quota_exceeded(self, worker_db, monkeypatch, error_type):
        from docsgpt import worker
        from docsgpt.agents import headless_runner
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(worker_db).create("sam", "Mine", "published", agent_type="classic")
        monkeypatch.setattr(
            headless_runner,
            "run_agent_headless",
            MagicMock(return_value={"answer": "Partial", "sources": [], "tool_calls": [], "thought": "",
                                    "error_type": error_type, "error": "This agent is paused."}),
        )
        task = MagicMock(name="celery_task_self")
        task.request.retries = 0

        result = worker.agent_webhook_worker(task, str(agent["id"]), {"event": "ping"})

        assert result["status"] == "quota_exceeded"
        assert result["error"] == "This agent is paused."
        assert result["result"]["answer"] == "Partial"
