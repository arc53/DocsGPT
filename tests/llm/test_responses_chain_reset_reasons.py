"""Every Responses turn that does not chain says why.

Background (b2b-sl experiments, 2026-10-01): chained turns were 99-100%
cached, and every reset turned the next calls into full cache writes. Two
resets left no log line at all; this pins one ``responses_chain_reset``
INFO line per unchained turn, with its reason and the conversation and
activity it belongs to.
"""

import logging
import types
from unittest.mock import MagicMock

import pytest

from docsgpt.core import log_context
from docsgpt.core.model_settings import ModelCapabilities

pytestmark = pytest.mark.unit

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _make_llm(monkeypatch, store_responses=True):
    monkeypatch.setattr("docsgpt.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr(
        "docsgpt.llm.openai.StorageCreator",
        types.SimpleNamespace(get_storage=lambda: None),
    )
    monkeypatch.setattr(
        "docsgpt.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k",
            API_KEY="k",
            OPENAI_BASE_URL="",
            AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=store_responses,
            OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False,
            OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(supports_tools=True, supports_structured_output=True, api_flavor="responses")
    return llm


def _answers(llm, *ids):
    """Each call streams one answer and completes as the next response id."""
    calls = iter(ids)

    def _create(**params):
        llm.sent.append(params)
        rid = next(calls)
        if isinstance(rid, Exception):
            raise rid
        return [
            types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
            types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(id=rid, output=[], usage=None)),
        ]

    llm.sent = []
    llm.client.responses.create = MagicMock(side_effect=_create)


def _call(llm, previous_response_id=None):
    kwargs = {"previous_response_id": previous_response_id} if previous_response_id else {}
    return list(llm._raw_gen_stream(llm, "gpt-6.1-sol", MESSAGES, **kwargs))


def _resets(caplog):
    return [r for r in caplog.records if r.getMessage() == "responses_chain_reset"]


@pytest.fixture
def bound():
    token = log_context.bind(conversation_id="conv-9", activity_id="act-1")
    yield
    log_context.reset(token)


class TestLlmReasons:
    def test_an_unchained_turn_logs_its_reason_with_the_conversation(self, monkeypatch, caplog, bound):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_1")
        llm.note_chain_turn("first_turn")

        with caplog.at_level(logging.INFO):
            _call(llm)

        (record,) = _resets(caplog)
        assert record.reason == "first_turn"
        assert record.conversation_id == "conv-9"
        assert record.activity_id == "act-1"
        assert record.model == "gpt-6.1-sol"
        assert llm._chain_reset_reason == "first_turn"

    def test_a_chained_turn_logs_nothing(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_2", "resp_3")
        llm.note_chain_turn(None)

        with caplog.at_level(logging.INFO):
            _call(llm, previous_response_id="resp_1")
            _call(llm)

        assert _resets(caplog) == []
        assert llm._chain_reset_reason is None
        assert llm.sent[1]["previous_response_id"] == "resp_2"

    def test_one_line_per_turn_for_the_same_reason(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch, store_responses=False)
        _answers(llm, "resp_1", "resp_2", "resp_3")
        llm.note_chain_turn("disabled")

        with caplog.at_level(logging.INFO):
            _call(llm)
            _call(llm)
            llm.note_chain_turn("disabled")
            _call(llm)

        assert [r.reason for r in _resets(caplog)] == ["disabled", "disabled"]

    def test_a_compression_mid_turn_resets_with_its_reason(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_2", "resp_3")
        llm.note_chain_turn(None)

        with caplog.at_level(logging.INFO):
            _call(llm, previous_response_id="resp_1")
            llm.start_responses_turn(reason="compression")
            _call(llm)

        assert [r.reason for r in _resets(caplog)] == ["compression"]
        assert "previous_response_id" not in llm.sent[1]

    def test_a_round_after_a_failed_call_says_so(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_2", RuntimeError("upstream 500"), "resp_4")
        llm.note_chain_turn(None)

        with caplog.at_level(logging.INFO):
            _call(llm, previous_response_id="resp_1")
            with pytest.raises(RuntimeError):
                _call(llm)
            _call(llm)

        assert [r.reason for r in _resets(caplog)] == ["previous_call_failed"]

    def test_a_previous_response_the_provider_lost_is_not_found(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        lost = RuntimeError("Previous response with id 'resp_1' not found.")
        lost.code = "previous_response_not_found"
        _answers(llm, lost, "resp_2")
        llm.note_chain_turn(None)

        with caplog.at_level(logging.INFO):
            with pytest.raises(RuntimeError):
                _call(llm, previous_response_id="resp_1")
            _call(llm)

        assert [r.reason for r in _resets(caplog)] == ["not_found"]

    def test_a_history_that_does_not_answer_the_chained_calls(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_2")
        llm.note_chain_turn(None)
        # The chained response asked for a tool output this history lacks.
        llm._last_response_call_ids = {"call_missing"}

        with caplog.at_level(logging.INFO):
            _call(llm, previous_response_id="resp_1")

        assert [r.reason for r in _resets(caplog)] == ["history_mismatch"]

    def test_an_llm_no_agent_turn_tracks_logs_nothing(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        _answers(llm, "resp_1")

        with caplog.at_level(logging.INFO):
            _call(llm)

        assert _resets(caplog) == []
        assert llm._chain_reset_reason is None


def test_the_reason_is_a_span_attribute(monkeypatch):
    from docsgpt.tracing import llm as tracing_llm

    monkeypatch.setattr(tracing_llm.settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(tracing_llm, "record_llm_metrics", lambda **kwargs: None)
    span = MagicMock()
    llm = types.SimpleNamespace(provider_name="openai", _chain_reset_reason="compression")

    tracing_llm.finish_llm_call(span, llm, "gpt-6.1-sol", {}, duration_ms=1, error=None)

    assert span.end.call_args.kwargs["attributes"]["docsgpt.chain_reset_reason"] == "compression"


# ── agent: why the turn does not chain ──────────────────────────────────────


def _agent(monkeypatch, history, last_compression_at=None, **overrides):
    from docsgpt.agents import base as base_mod
    from docsgpt.agents.base import BaseAgent

    class _Agent(BaseAgent):
        def _gen_inner(self, query, log_context):
            yield from ()

    agent = _Agent.__new__(_Agent)
    agent.chat_history = history
    agent.llm = types.SimpleNamespace(responses_chain_key=lambda: "key", _uses_responses_api=lambda: True)
    agent.model_id = "m"
    agent.model_user_id = None
    agent.user = "u"
    agent.last_compression_at = last_compression_at
    defaults = {
        "OPENAI_RESPONSES_STORE": True,
        "OPENAI_RESPONSES_CHAIN_ACROSS_TURNS": True,
        "OPENAI_RESPONSES_CHAIN_BUDGET_TOKENS": None,
        "ATTACHMENT_MAX_NATIVE_PARTS": 40,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        monkeypatch.setattr(base_mod.settings, key, value, raising=False)
    monkeypatch.setattr("docsgpt.core.model_utils.get_token_limit", lambda *a, **k: 1000)
    return agent


def _turn(prompt_tokens=10, **meta):
    base = {"response_id": "resp_1", "response_chain_key": "key", "usage": {"prompt_tokens": prompt_tokens}}
    base.update(meta)
    return {"prompt": "q", "response": "a", "metadata": {k: v for k, v in base.items() if v is not None}}


class TestAgentReasons:
    @pytest.mark.parametrize(
        "history, overrides, compression, reason",
        [
            ([], {}, None, "first_turn"),
            ([_turn()], {"OPENAI_RESPONSES_CHAIN_ACROSS_TURNS": False}, None, "disabled"),
            ([{"prompt": "q", "response": "a"}], {}, None, "no_previous_response"),
            ([_turn(response_id=None, response_chain_key=None)], {}, None, "no_previous_response"),
            (
                [_turn(response_id=None, answered_by=[{"model": "kimi-k3", "fallback": True}])],
                {},
                None,
                "fallback_answered",
            ),
            ([_turn(response_chain_key="other")], {}, None, "chain_key_mismatch"),
            ([_turn()], {}, "2026-09-03T10:00:00+00:00", "compression"),
            ([_turn(prompt_tokens=1000)], {}, None, "chain_budget"),
        ],
    )
    def test_the_reason_a_turn_starts_unchained(self, monkeypatch, history, overrides, compression, reason):
        agent = _agent(monkeypatch, history, last_compression_at=compression, **overrides)

        assert agent._previous_response_choice() == (None, reason)
        assert agent._previous_response_id() is None

    def test_the_native_parts_cap(self, monkeypatch):
        agent = _agent(monkeypatch, [_turn()], ATTACHMENT_MAX_NATIVE_PARTS=1)
        agent.earlier_attachments = [{"id": f"e{i}", "mime_type": "image/png"} for i in range(2)]

        assert agent._previous_response_choice() == (None, "native_parts_cap")

    def test_a_chained_turn_has_no_reason(self, monkeypatch):
        assert _agent(monkeypatch, [_turn()])._previous_response_choice() == ("resp_1", None)
