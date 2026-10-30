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


# ── the agent ────────────────────────────────────────────────────────────────

WINDOW = 200000
LIMIT = 20000


def _words(count: int) -> str:
    return "word " * count


@pytest.fixture
def window(monkeypatch):
    """Every model reports a 200k window."""
    monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda *a, **k: WINDOW)


@pytest.mark.unit
class TestAgentReadsTheLimit:
    def test_from_the_agent_config(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent(**agent_base_params, agent_config={"context_window_limit": 32000})
        assert agent.context_window_limit == 32000

    def test_none_without_one(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        from docsgpt.agents.classic_agent import ClassicAgent

        assert ClassicAgent(**agent_base_params).context_window_limit is None

    def test_an_explicit_limit_wins(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent(
            **agent_base_params, agent_config={"context_window_limit": 32000}, context_window_limit=64000
        )
        assert agent.context_window_limit == 64000


@pytest.mark.unit
class TestAgentBudgets:
    @pytest.fixture
    def make(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator, window):
        from docsgpt.agents.classic_agent import ClassicAgent

        def _make(limit=LIMIT, **params):
            return ClassicAgent(**{**agent_base_params, **params}, context_window_limit=limit)

        return _make

    def test_compression_triggers_at_the_limit(self, make):
        messages = [{"role": "user", "content": "hi"}]
        capped, uncapped = make(), make(limit=None)
        with patch.object(capped, "_calculate_current_context_tokens", return_value=int(LIMIT * 0.9)), \
                patch.object(uncapped, "_calculate_current_context_tokens", return_value=int(LIMIT * 0.9)):
            assert capped._check_context_limit(messages) is True
            assert uncapped._check_context_limit(messages) is False

    def test_skipping_tools_keeps_the_model_threshold(self, make):
        """Crossing the limit compresses; only the model's own threshold stops tools."""
        messages = [{"role": "user", "content": "hi"}]
        capped, uncapped = make(), make(limit=None)
        for agent in (capped, uncapped):
            with patch.object(agent, "_calculate_current_context_tokens", return_value=int(LIMIT * 0.9)):
                assert agent._over_model_threshold(messages) is False
            with patch.object(agent, "_calculate_current_context_tokens", return_value=int(WINDOW * 0.9)):
                assert agent._over_model_threshold(messages) is True

    def test_a_smaller_fallback_that_answered_lowers_the_model_threshold(self, make, monkeypatch):
        """A turn a smaller fallback answered stops its tools before outgrowing that fallback."""
        from types import SimpleNamespace

        small = 30_000
        monkeypatch.setattr(
            "docsgpt.core.model_utils.get_token_limit",
            lambda model_id, user_id=None: small if model_id == "fb-small" else WINDOW,
        )
        messages = [{"role": "user", "content": "hi"}]
        agent = make(limit=None)
        agent.llm._fallback_llm = SimpleNamespace(model_id="fb-small", model_user_id=None)
        tokens = int(small * 0.9)

        with patch.object(agent, "_calculate_current_context_tokens", return_value=tokens):
            agent.llm.answered_by = [{"model": "primary", "provider": "openai", "fallback": False}]
            assert agent._over_model_threshold(messages) is False
            agent.llm.answered_by.append({"model": "fb-small", "provider": "openai", "fallback": True})
            assert agent._over_model_threshold(messages) is True
            # Still the smaller window once the primary answers again.
            agent.llm.answered_by.append({"model": "primary", "provider": "openai", "fallback": False})
            assert agent._over_model_threshold(messages) is True

    def test_a_byom_fallback_is_measured_by_its_registry_id(self, make, monkeypatch):
        """``model_id`` is the upstream name; the registry knows a BYOM model by its UUID."""
        from types import SimpleNamespace

        small = 30_000
        monkeypatch.setattr(
            "docsgpt.core.model_utils.get_token_limit",
            lambda model_id, user_id=None: small if model_id == "byom-uuid" else WINDOW,
        )
        agent = make(limit=None)
        agent.llm._fallback_llm = SimpleNamespace(
            model_id="llama3:70b", _canonical_model_id="byom-uuid", model_user_id="owner"
        )
        agent.llm.answered_by = [{"model": "llama3:70b", "provider": "openai", "fallback": True}]
        with patch.object(agent, "_calculate_current_context_tokens", return_value=int(small * 0.9)):
            assert agent._over_model_threshold([{"role": "user", "content": "hi"}]) is True

    def test_a_larger_fallback_keeps_the_primary_threshold(self, make, monkeypatch):
        from types import SimpleNamespace

        monkeypatch.setattr(
            "docsgpt.core.model_utils.get_token_limit",
            lambda model_id, user_id=None: WINDOW * 2 if model_id == "fb-big" else WINDOW,
        )
        agent = make(limit=None)
        agent.llm._fallback_llm = SimpleNamespace(model_id="fb-big", model_user_id=None)
        agent.llm.answered_by = [{"model": "fb-big", "provider": "openai", "fallback": True}]
        with patch.object(agent, "_calculate_current_context_tokens", return_value=int(WINDOW * 0.9)):
            assert agent._over_model_threshold([{"role": "user", "content": "hi"}]) is True

    def test_tool_result_room_is_measured_against_the_limit(self, make):
        agent = make()
        with patch.object(agent, "_calculate_current_context_tokens", return_value=1000):
            assert agent._context_room_tokens([]) == int(LIMIT * 0.8) - 1000

    def test_history_is_trimmed_to_the_limit(self, make):
        from docsgpt.api.answer.services.compression.token_counter import TokenCounter

        history = [{"prompt": _words(500), "response": _words(500)} for _ in range(40)]
        capped = make(chat_history=history)._build_messages("sys", "question")
        uncapped = make(limit=None, chat_history=history)._build_messages("sys", "question")

        assert TokenCounter.count_message_tokens(capped) <= LIMIT
        assert len(uncapped) == 2 + 2 * len(history)
        assert len(capped) < len(uncapped)
        # The newest turns are the ones kept.
        assert capped[-2]["content"] == history[-1]["response"]

    def test_documents_are_shed_to_the_limit(self, make):
        docs = [{"text": _words(3000), "title": f"d{i}", "source": f"s{i}"} for i in range(10)]
        capped = make(retrieved_docs=[dict(d) for d in docs])
        capped._build_messages("sys", "question")
        uncapped = make(limit=None, retrieved_docs=[dict(d) for d in docs])
        uncapped._build_messages("sys", "question")

        assert 0 < len(capped.retrieved_docs) < len(docs)
        assert len(uncapped.retrieved_docs) == len(docs)

    def test_shedding_stops_when_no_documents_are_left(self, make):
        """A searched turn keeps its "nothing matched" note, which shedding cannot remove.

        A question between the limit's turn budget and the model's used to
        spin forever, dropping documents from an empty list.
        """
        from docsgpt.agents import base as agent_base

        real_drop = agent_base.drop_least_relevant

        def drop(docs):
            assert docs, "shed from an empty document list"
            return real_drop(docs)

        docs = [{"text": _words(3000), "title": f"d{i}", "source": f"s{i}"} for i in range(3)]
        agent = make(retrieved_docs=docs, sources_were_searched=True)
        query = _words(int(LIMIT * 1.1))
        with patch.object(agent_base, "drop_least_relevant", side_effect=drop):
            messages = agent._build_messages("sys", query)

        assert agent.retrieved_docs == []
        assert agent.EMPTY_RETRIEVAL_NOTE in messages[-1]["content"]
        assert query in messages[-1]["content"]

    def test_a_message_longer_than_the_limit_is_still_sent(self, make):
        """The limit is a budget, not a refusal: a message the model can take is never failed by it."""
        query = _words(LIMIT * 2)
        messages = make(chat_history=[{"prompt": "p", "response": "r"}])._build_messages("sys", query)

        assert messages[-1]["content"] == query
        assert [m["role"] for m in messages] == ["system", "user"]

    def test_a_system_prompt_longer_than_the_limit_is_still_sent(self, make):
        system = _words(LIMIT * 2)
        assert make()._build_messages(system, "q")[0]["content"] == system

    def test_the_pre_send_gate_keeps_the_model_window(self, make):
        tool_result = _words(LIMIT * 2)
        messages = [{"role": "user", "content": "q"}, {"role": "tool", "content": tool_result}]
        assert make()._enforce_context_window(messages)[1]["content"] == tool_result

    def test_turn_capabilities_window_is_the_limit(self, make):
        agent = make()
        with patch("docsgpt.agents.base.build_turn_capabilities") as build:
            agent._compute_turn_capabilities({})
        assert build.call_args.kwargs["window"] == LIMIT


@pytest.mark.unit
class TestResponsesChain:
    def _agent(self, monkeypatch, limit, prompt_tokens):
        from docsgpt.agents import base as base_mod
        from docsgpt.agents.base import BaseAgent

        class _Agent(BaseAgent):
            def _gen_inner(self, query, log_context):
                yield from ()

        agent = _Agent.__new__(_Agent)
        agent.chat_history = [{"prompt": "q", "response": "a", "metadata": {
            "response_id": "resp_1", "response_chain_key": "key", "usage": {"prompt_tokens": prompt_tokens},
        }}]
        agent.llm = type("L", (), {"responses_chain_key": staticmethod(lambda: "key")})()
        agent.model_id, agent.model_user_id, agent.user = "m", None, "u"
        agent.last_compression_at = None
        agent.context_window_limit = limit
        for key, value in {
            "OPENAI_RESPONSES_CHAIN_ACROSS_TURNS": True,
            "OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS": None,
            "ATTACHMENT_MAX_NATIVE_PARTS": 40,
        }.items():
            monkeypatch.setattr(base_mod.settings, key, value, raising=False)
        monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda *a, **k: WINDOW)
        return agent

    def test_a_chain_past_the_limit_starts_over(self, monkeypatch):
        assert self._agent(monkeypatch, LIMIT, LIMIT + 1)._previous_response_choice() == (None, "chain_budget")

    def test_without_a_limit_it_chains(self, monkeypatch):
        assert self._agent(monkeypatch, None, LIMIT + 1)._previous_response_choice() == ("resp_1", None)

    def test_an_operator_budget_below_the_limit_still_applies(self, monkeypatch):
        from docsgpt.agents import base as base_mod

        agent = self._agent(monkeypatch, LIMIT, 5000)
        monkeypatch.setattr(base_mod.settings, "OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS", 4000, raising=False)
        assert agent._previous_response_choice() == (None, "chain_budget")


# ── compression and history helpers ──────────────────────────────────────────


@pytest.mark.unit
class TestCompressionThreshold:
    def _conversation(self, tokens: int) -> dict:
        return {"queries": [{"prompt": _words(tokens), "response": ""}]}

    def test_should_compress_at_the_limit(self):
        from docsgpt.api.answer.services.compression.threshold_checker import CompressionThresholdChecker

        checker = CompressionThresholdChecker(threshold_percentage=0.8)
        conversation = self._conversation(int(LIMIT * 0.9))
        with patch("docsgpt.api.answer.services.compression.threshold_checker.get_token_limit",
                   return_value=WINDOW):
            assert checker.should_compress(conversation, "m", 0, context_window_limit=LIMIT) is True
            assert checker.should_compress(conversation, "m", 0) is False

    def test_the_orchestrator_passes_the_limit_on(self):
        from docsgpt.api.answer.services.compression.orchestrator import CompressionOrchestrator

        service = type("S", (), {"get_conversation": lambda self, *a: {"queries": []}})()
        orchestrator = CompressionOrchestrator(service)
        with patch.object(orchestrator.threshold_checker, "should_compress", return_value=False) as check:
            orchestrator.compress_if_needed("c", "u", "m", {}, context_window_limit=LIMIT)
        assert check.call_args.kwargs["context_window_limit"] == LIMIT


@pytest.mark.unit
class TestHistoryHelpers:
    def test_doc_budget_is_taken_from_the_limit(self):
        from docsgpt.utils import calculate_doc_token_budget

        with patch("docsgpt.utils.get_token_limit", return_value=WINDOW):
            assert calculate_doc_token_budget("m", context_window_limit=LIMIT) < LIMIT
            assert calculate_doc_token_budget("m") > LIMIT

    def test_limit_chat_history_trims_to_the_limit(self):
        from docsgpt.utils import limit_chat_history

        history = [{"prompt": _words(500), "response": _words(500)} for _ in range(60)]
        with patch("docsgpt.utils.get_token_limit", return_value=WINDOW):
            capped = limit_chat_history(history, max_token_limit=LIMIT, model_id="m")
            uncapped = limit_chat_history(history, model_id="m")
        assert len(capped) < LIMIT // 1000
        assert len(uncapped) == len(history)


# ── the paths that build an agent ────────────────────────────────────────────


def _processor(config=None, **attrs):
    from docsgpt.api.answer.services.stream_processor import StreamProcessor

    sp = StreamProcessor.__new__(StreamProcessor)
    sp.data = {}
    sp.decoded_token = {"sub": "u"}
    sp.initial_user_id = "u"
    sp.model_id = "m"
    sp.model_user_id = None
    sp.agent_key = None
    sp._agent_data = None
    sp.attachments = []
    sp.earlier_attachments = []
    sp.agent_config = {"config": config if config is not None else {"context_window_limit": LIMIT}}
    for key, value in attrs.items():
        setattr(sp, key, value)
    return sp


@pytest.fixture
def sp_window(monkeypatch):
    monkeypatch.setattr("docsgpt.api.answer.services.stream_processor.get_token_limit", lambda *a, **k: WINDOW)


@pytest.mark.unit
class TestStreamProcessor:
    def test_reads_the_agent_limit(self):
        assert _processor()._context_window_limit() == LIMIT
        assert _processor(config={})._context_window_limit() is None
        assert _processor(config={"context_window_limit": 3})._context_window_limit() is None
        assert _processor(agent_config={})._context_window_limit() is None

    def test_budget_window_is_capped_and_window_is_not(self, sp_window):
        sp = _processor()
        assert sp._budget_window() == LIMIT
        assert sp._window() == WINDOW

    def test_compression_gets_the_limit(self):
        from docsgpt.api.answer.services.compression.types import CompressionResult

        orchestrator = type("O", (), {})()
        calls = []
        orchestrator.compress_if_needed = lambda **kw: calls.append(kw) or CompressionResult.failure("x")
        sp = _processor(compression_orchestrator=orchestrator, conversation_id="c")
        with patch.object(sp, "_turn_token_estimate", return_value=10):
            sp._handle_compression({"queries": []})
        assert calls[0]["context_window_limit"] == LIMIT

    def test_doc_budget_gets_the_limit(self):
        sp = _processor(_agent_data={"retriever": None, "chunks": None})
        with patch("docsgpt.api.answer.services.stream_processor.calculate_doc_token_budget",
                   return_value=1000) as budget:
            sp._configure_retriever()
        assert budget.call_args.kwargs["context_window_limit"] == LIMIT

    def test_client_history_is_trimmed_to_the_limit(self):
        sp = _processor(conversation_id=None, data={"history": "[]"})
        with patch.object(sp, "_ensure_turn_fits"), \
                patch.object(sp, "_with_request_earlier_attachments", return_value=[]), \
                patch("docsgpt.api.answer.services.stream_processor.limit_chat_history",
                      return_value=[]) as trim:
            sp._load_conversation_history()
        assert trim.call_args.kwargs["max_token_limit"] == LIMIT

    def test_a_long_message_still_fits_the_turn(self, sp_window):
        sp = _processor(data={"question": _words(LIMIT * 2)})
        with patch.object(sp, "_system_prompt_tokens", return_value=100):
            sp._ensure_turn_fits()

    def test_attachments_are_planned_against_the_limit(self, sp_window):
        sp = _processor(attachments=[{"id": "a1", "mime_type": "text/plain"}])
        sp_mod = "docsgpt.api.answer.services.stream_processor"
        with patch(f"{sp_mod}.get_model_capabilities", return_value={}), \
                patch(f"{sp_mod}.build_turn_capabilities") as caps, \
                patch(f"{sp_mod}.compute_attachment_budget", return_value=1) as budget, \
                patch(f"{sp_mod}.plan_attachments"):
            sp._preliminary_attachment_reserve()
        assert caps.call_args.kwargs["window"] == LIMIT
        assert budget.call_args.kwargs["window"] == LIMIT


@pytest.mark.unit
class TestPauseAndResume:
    def test_a_paused_turn_saves_the_limit(self, agent_base_params, mock_llm_creator, mock_llm_handler_creator):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent(**agent_base_params, context_window_limit=LIMIT)
        assert agent.paused_turn_state()["context_window_limit"] == LIMIT

    def test_the_resumed_agent_gets_it_back(self, monkeypatch):
        from unittest.mock import MagicMock

        from docsgpt.agents import agent_creator as ac_mod
        from docsgpt.agents import tool_executor as te_mod
        from docsgpt.api.answer.services import continuation_service as cont_mod
        from docsgpt.llm import llm_creator as llm_creator_mod
        from docsgpt.llm.handlers import handler_creator as handler_mod

        cont_service = MagicMock()
        cont_service.claim_state.return_value = {
            "messages": [], "pending_tool_calls": [], "tools_dict": {}, "tool_schemas": [], "client_tools": None,
            "agent_config": {
                "model_id": "m1", "llm_name": "openai", "api_key": "k", "agent_type": "ClassicAgent",
                "context_window_limit": LIMIT,
            },
        }
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
        monkeypatch.setattr(te_mod, "ToolExecutor", lambda **kw: MagicMock(client_tools=None))
        created = {}
        monkeypatch.setattr(
            ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock(),
        )
        sp = _processor(agent_config={}, conversation_id="00000000-0000-0000-0000-000000000001")

        sp.resume_from_tool_actions(tool_actions=[], conversation_id="00000000-0000-0000-0000-000000000001")

        assert created["context_window_limit"] == LIMIT


@pytest.mark.unit
class TestHeadlessAndBackground:
    def test_a_headless_run_budgets_documents_to_the_limit(self, monkeypatch):
        from unittest.mock import MagicMock

        from docsgpt.agents import headless_runner as hr

        agent = MagicMock(name="agent")
        agent.gen.return_value = iter([{"answer": "ok"}])
        agent.llm.token_usage = {"prompt_tokens": 1, "generated_tokens": 1}
        tool_executor = MagicMock(name="tool_executor")
        tool_executor.headless_denials = []
        created = {}
        monkeypatch.setattr(hr, "get_prompt", lambda _pid: "system prompt")
        monkeypatch.setattr(hr, "ToolExecutor", lambda *a, **kw: tool_executor)
        monkeypatch.setattr(
            hr.AgentCreator, "create_agent", classmethod(lambda cls, *a, **kw: created.update(kw) or agent),
        )
        config = {
            "user_id": "u1", "id": "agent-1", "default_model_id": "m", "chunks": 0,
            "config": {"context_window_limit": LIMIT},
        }
        with patch("docsgpt.core.model_utils.validate_model_id", return_value=True), \
                patch("docsgpt.core.model_utils.get_default_model_id", return_value="m"), \
                patch("docsgpt.core.model_utils.get_provider_from_model_id", return_value="openai"), \
                patch("docsgpt.core.model_utils.get_api_key_for_provider", return_value="k"), \
                patch("docsgpt.utils.calculate_doc_token_budget", return_value=1000) as budget:
            hr.run_agent_headless(config, "do the thing")

        assert budget.call_args.kwargs["context_window_limit"] == LIMIT
        assert created["agent_config"]["context_window_limit"] == LIMIT

    def test_a_continuation_replays_history_to_the_limit(self):
        from docsgpt.background import continuation

        messages = [{"prompt": _words(500), "response": _words(500)} for _ in range(60)]
        with patch("docsgpt.utils.get_token_limit", return_value=WINDOW):
            capped = continuation._replay({"id": "c"}, messages, "m", "u", context_window_limit=LIMIT)[1]
            uncapped = continuation._replay({"id": "c"}, messages, "m", "u")[1]
        assert len(capped) < LIMIT // 1000
        assert len(uncapped) == len(messages)


@pytest.mark.unit
class TestWorkflowNodes:
    def _node_kwargs(self, monkeypatch, limit):
        from types import SimpleNamespace

        from docsgpt.agents.workflows.node_agent import WorkflowNodeAgentFactory
        from docsgpt.agents.workflows.schemas import NodeType, Workflow, WorkflowGraph, WorkflowNode
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        built = []

        class _NodeAgent:
            tool_executor = SimpleNamespace()

            def gen(self, _prompt):
                yield {"answer": "ok"}

        monkeypatch.setattr(
            WorkflowNodeAgentFactory, "create",
            staticmethod(lambda agent_type, **kw: built.append(kw) or _NodeAgent()),
        )
        monkeypatch.setattr("docsgpt.core.model_utils.get_api_key_for_provider", lambda _name: None)
        agent = SimpleNamespace(
            endpoint="stream", llm_name="openai", model_id="gpt-4o-mini", api_key="k", chat_history=[],
            decoded_token={"sub": "alice"}, user="alice", _resolve_owner_id=lambda: "alice",
            tool_executor=SimpleNamespace(), context_window_limit=limit,
        )
        engine = WorkflowEngine(WorkflowGraph(workflow=Workflow(name="wf"), nodes=[], edges=[]), agent)
        engine.state["query"] = "q"
        node = WorkflowNode(
            id="a1", workflow_id="wf", type=NodeType.AGENT, title="A", position={"x": 0, "y": 0},
            config={"agent_type": "classic", "system_prompt": "s", "tools": []},
        )
        list(engine._execute_agent_node(node))
        return built[0]

    def test_a_node_inherits_the_workflow_agent_limit(self, monkeypatch):
        assert self._node_kwargs(monkeypatch, LIMIT)["context_window_limit"] == LIMIT

    def test_a_node_without_one_uses_its_model_window(self, monkeypatch):
        assert self._node_kwargs(monkeypatch, None)["context_window_limit"] is None
