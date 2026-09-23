"""Non-chat entry points each record and write one execution trace."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from docsgpt import tracing
from docsgpt.core.settings import settings


@pytest.fixture(autouse=True)
def _tracing_on(monkeypatch):
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_OTEL_EXPORT", False)


@pytest.fixture()
def flushed():
    """Capture flushed traces instead of writing them."""
    captured = []

    def _fake_flush(trace, status=None, **_kwargs):
        if trace is None or trace.flushed:
            return
        trace.flushed = True
        trace.finish(status)
        captured.append(trace)

    with patch("docsgpt.tracing.flush", side_effect=_fake_flush):
        yield captured


def _headless(events, monkeypatch, **kwargs):
    from docsgpt.agents import headless_runner as hr

    agent = MagicMock(name="agent")

    def _gen(query):
        with tracing.span(tracing.KIND_AGENT, "invoke_agent Fake"):
            yield from events

    agent.gen.side_effect = _gen
    agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
    retriever = MagicMock(name="retriever")

    def _search(query):
        with tracing.span(tracing.KIND_RETRIEVAL, "retrieval"):
            return []

    retriever.search.side_effect = _search
    tool_executor = MagicMock(name="tool_executor")
    tool_executor.headless_denials = []
    monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
    monkeypatch.setattr(
        hr.RetrieverCreator, "create_retriever", classmethod(lambda cls, *a, **kw: retriever)
    )
    monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
    monkeypatch.setattr(
        hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: agent)
    )
    with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
         patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
         patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
         patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
         patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
        return hr.run_agent_headless(
            {"user_id": "owner-1", "id": "11111111-1111-1111-1111-111111111111"},
            "do the thing",
            **kwargs,
        )


@pytest.mark.unit
class TestHeadless:
    def test_scheduled_run_is_traced_with_its_run_id(self, monkeypatch, flushed):
        _headless([{"answer": "done"}], monkeypatch, endpoint="schedule", request_id="run-1")
        (trace,) = flushed
        assert trace.source == "schedule"
        assert trace.request_id == "run-1"
        assert trace.user_id == "owner-1"
        assert trace.status == "ok"
        assert [s.kind for s in trace.spans] == ["retrieval", "agent"]

    def test_trace_can_belong_to_the_scheduling_user(self, monkeypatch, flushed):
        """A schedule on a shared agent is the scheduler's run, not the owner's."""
        _headless(
            [{"answer": "done"}],
            monkeypatch,
            endpoint="schedule",
            request_id="run-2",
            trace_user_id="scheduler-user",
        )
        assert flushed[0].user_id == "scheduler-user"

    def test_stream_error_marks_trace_error(self, monkeypatch, flushed):
        outcome = _headless([{"type": "error", "error": "boom"}], monkeypatch, endpoint="webhook")
        assert outcome["error_type"] == "stream_error"
        assert flushed[0].status == "error"

    def test_raised_error_still_flushes(self, monkeypatch, flushed):
        from docsgpt.agents import headless_runner as hr

        monkeypatch.setattr(hr, "_run_agent_headless", MagicMock(side_effect=RuntimeError("x")))
        with pytest.raises(RuntimeError):
            hr.run_agent_headless({"user_id": "u"}, "q")
        assert flushed[0].status == "error"

    def test_trace_request_id_stays_off_llm_usage_rows(self, monkeypatch, flushed):
        """The headless LLM's own request id is untouched (quota counts depend on it)."""
        from docsgpt.agents import headless_runner as hr

        created = {}

        def _create(cls, *a, **kw):
            agent = MagicMock()
            agent.gen.return_value = iter([{"answer": "x"}])
            agent.llm.token_usage = {}
            agent.llm._request_id = None
            created["agent"] = agent
            return agent

        monkeypatch.setattr(hr.AgentCreator, "create_agent", classmethod(_create))
        monkeypatch.setattr(hr, "get_prompt", lambda _pid: "p")
        monkeypatch.setattr(
            hr.RetrieverCreator, "create_retriever",
            classmethod(lambda cls, *a, **kw: MagicMock(search=MagicMock(return_value=[]))),
        )
        monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: MagicMock(headless_denials=[]))
        with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
             patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
             patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
             patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
             patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000):
            hr.run_agent_headless({"user_id": "u"}, "q", endpoint="schedule", request_id="run-9")
        assert created["agent"].llm._request_id is None


@contextmanager
def _search_env(agent):
    repo = MagicMock()
    repo.find_by_key.return_value = agent

    @contextmanager
    def _conn():
        yield MagicMock()

    store = MagicMock()
    store.search.return_value = [{"text": "hit", "metadata": {"title": "T", "source": "s"}}]
    with patch("docsgpt.api.user.team_sharing.can_access", return_value=True), \
         patch("docsgpt.services.search_service.db_readonly", _conn), \
         patch("docsgpt.services.search_service.AgentsRepository", return_value=repo), \
         patch(
             "docsgpt.services.search_service.VectorCreator.create_vectorstore",
             return_value=store,
         ):
        yield


@pytest.mark.unit
class TestSearch:
    def test_search_is_traced(self, flushed):
        from docsgpt.services.search_service import search

        agent = {"id": "a-1", "source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        with _search_env(agent):
            results = search("k", "what is x", 3)
        assert results
        (trace,) = flushed
        assert trace.source == "search"
        assert trace.user_id == "owner"
        retrieval = trace.spans[0]
        assert retrieval.kind == tracing.KIND_RETRIEVAL
        assert retrieval.attributes["docsgpt.chunk_count"] == 1

    def test_mcp_source_name(self, flushed):
        from docsgpt.services.search_service import search

        agent = {"id": "a-1", "source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        with _search_env(agent):
            search("k", "q", 3, source="mcp")
        assert flushed[0].source == "mcp"

    def test_no_sources_records_nothing(self, flushed):
        from docsgpt.services.search_service import search

        with _search_env({"id": "a-1", "source_id": None, "user_id": "owner"}):
            assert search("k", "q", 3) == []
        assert flushed == []
