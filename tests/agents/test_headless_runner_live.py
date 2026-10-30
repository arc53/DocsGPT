"""A headless run can be watched as it runs and stopped part way, for a continuation that streams."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _run(monkeypatch, events, **kwargs):
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")
    closed = []

    def _gen(query):
        try:
            yield from events
        finally:
            closed.append(True)

    agent.gen.side_effect = _gen
    agent.llm.token_usage = {}
    executor = MagicMock(headless_denials=[])
    executor.get_truncated_tool_calls.return_value = [{"call_id": "c1", "job_id": "j1"}]
    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: executor)
    monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent))
    monkeypatch.setattr(hr.QuotaService, "check", lambda *a, **kw: None)
    config = {"user_id": "u1", "id": "agent-1", "default_model_id": "m", "agent_type": "classic", "chunks": 0}
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
            patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
            patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
            patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        outcome = hr.run_agent_headless(config, "q", **kwargs)
    return outcome, closed


@pytest.mark.unit
class TestLiveHeadlessRun:
    def test_the_observer_sees_every_event_in_order(self, monkeypatch):
        seen = []
        events = [{"thought": "hm"}, {"answer": "a"}, {"answer": "b"}]
        outcome, _ = _run(monkeypatch, events, on_event=seen.append)
        assert seen == events
        assert outcome["answer"] == "ab" and outcome["stopped"] is False

    def test_a_failing_observer_does_not_end_the_run(self, monkeypatch):
        def _boom(event):
            raise RuntimeError("journal down")

        outcome, _ = _run(monkeypatch, [{"answer": "a"}, {"answer": "b"}], on_event=_boom)
        assert outcome["answer"] == "ab"

    def test_a_stop_ends_the_run_and_keeps_its_unreported_calls(self, monkeypatch):
        events = [{"answer": "a"}, {"answer": "b"}, {"answer": "c"}]
        seen = []
        outcome, closed = _run(
            monkeypatch, events, on_event=seen.append, should_stop=lambda: len(seen) >= 2
        )
        assert outcome["answer"] == "ab"
        assert outcome["stopped"] is True
        assert closed == [True]
        assert outcome["tool_calls"] == [{"call_id": "c1", "job_id": "j1"}]

    def test_a_stop_after_a_tool_call_ends_the_run_before_the_next_round(self, monkeypatch):
        events = [{"type": "tool_call", "data": {"call_id": "c1"}}, {"answer": "next round"}]
        outcome, closed = _run(monkeypatch, events, should_stop=lambda: True)
        assert outcome["stopped"] is True
        assert outcome["answer"] == ""
        assert closed == [True]

    def test_a_stop_that_ends_the_agent_mid_read_is_reported_as_stopped(self, monkeypatch):
        stop = []

        def events():
            yield {"answer": "a"}
            stop.append(True)  # the Stop ends the provider read; the agent returns quietly

        outcome, _ = _run(monkeypatch, events(), should_stop=lambda: bool(stop))
        assert outcome["answer"] == "a"
        assert outcome["stopped"] is True

    def test_worker_time_limit_keeps_partial_answer(self, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        def events():
            yield {"answer": "Saved progress"}
            raise SoftTimeLimitExceeded()

        outcome, closed = _run(monkeypatch, events(), endpoint="continuation")
        assert closed == [True]
        assert outcome["answer"] == "Saved progress"
        assert outcome["error_type"] == "TimeLimit"
        assert outcome["tool_calls"] == [{"call_id": "c1", "job_id": "j1"}]

    def test_scheduled_time_limit_reaches_its_existing_outer_handler(self, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        def events():
            yield {"answer": "Partial"}
            raise SoftTimeLimitExceeded()

        with pytest.raises(SoftTimeLimitExceeded):
            _run(monkeypatch, events(), endpoint="scheduled")

    def test_time_limit_in_observer_keeps_current_chunk_and_closes_the_agent(self, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        def observer(event):
            if event == {"answer": "b"}:
                raise SoftTimeLimitExceeded()

        outcome, closed = _run(
            monkeypatch, [{"answer": "a"}, {"answer": "b"}, {"answer": "unread"}],
            endpoint="continuation", on_event=observer,
        )
        assert outcome["answer"] == "ab"
        assert outcome["error_type"] == "TimeLimit"
        assert closed == [True]
