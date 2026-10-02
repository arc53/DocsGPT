"""A chained Responses call whose prefix changed says so.

Background (b2b-sl rerun, 2026-10-02): resumed client-tool rounds chained but
hit only ~3k cached tokens, and nothing was logged. The tools block the resume
rebuilt was ordered differently from the paused call's, which breaks the
provider prompt cache even though the call chains. One
``responses_prefix_changed`` INFO line names the part that changed, next to
``responses_chain_reset``.
"""

import logging
import types
from unittest.mock import MagicMock

import pytest

from docsgpt.core import log_context
from docsgpt.core.model_settings import ModelCapabilities

pytestmark = pytest.mark.unit

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


def _tool(*names):
    return [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search.",
                "parameters": {"type": "object", "properties": {name: {"type": "string"} for name in names}},
            },
        }
    ]


TOOLS = _tool("query", "k")
REORDERED = _tool("k", "query")


def _make_llm(monkeypatch):
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
            OPENAI_RESPONSES_STORE=True,
            OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False,
            OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(supports_tools=True, supports_structured_output=True, api_flavor="responses")
    counter = iter(range(1, 100))

    def _create(**params):
        rid = f"resp_{next(counter)}"
        return [
            types.SimpleNamespace(type="response.output_text.delta", delta="ok"),
            types.SimpleNamespace(
                type="response.completed", response=types.SimpleNamespace(id=rid, output=[], usage=None),
            ),
        ]

    llm.client.responses.create = MagicMock(side_effect=_create)
    return llm


def _call(llm, messages=MESSAGES, tools=TOOLS, previous_response_id=None):
    kwargs = {"previous_response_id": previous_response_id} if previous_response_id else {}
    return list(llm._raw_gen_stream(llm, "gpt-6.1-sol", messages, tools=tools, **kwargs))


def _changes(caplog):
    return [r for r in caplog.records if r.getMessage() == "responses_prefix_changed"]


@pytest.fixture
def bound():
    token = log_context.bind(conversation_id="conv-9", activity_id="act-1")
    yield
    log_context.reset(token)


class TestPrefixChanged:
    def test_the_same_prefix_logs_nothing(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        with caplog.at_level(logging.INFO):
            _call(llm)
            _call(llm)

        assert _changes(caplog) == []
        assert llm._prefix_changed is None

    def test_reordered_tools_on_a_chained_call_are_logged(self, monkeypatch, caplog, bound):
        llm = _make_llm(monkeypatch)
        with caplog.at_level(logging.INFO):
            _call(llm)
            _call(llm, tools=REORDERED)

        (record,) = _changes(caplog)
        assert record.changed == ["tools"]
        assert record.conversation_id == "conv-9"
        assert record.activity_id == "act-1"
        assert record.model == "gpt-6.1-sol"
        assert llm._prefix_changed == "tools"

    def test_a_changed_system_head_is_logged_as_instructions(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        changed = [{"role": "system", "content": "other"}, {"role": "user", "content": "hi"}]
        with caplog.at_level(logging.INFO):
            _call(llm)
            _call(llm, messages=changed, tools=REORDERED)

        (record,) = _changes(caplog)
        assert record.changed == ["instructions", "tools"]
        assert llm._prefix_changed == "instructions,tools"

    def test_an_unchained_call_is_not_a_prefix_change(self, monkeypatch, caplog):
        llm = _make_llm(monkeypatch)
        with caplog.at_level(logging.INFO):
            _call(llm)
            llm.start_responses_turn()
            _call(llm, tools=REORDERED)

        assert _changes(caplog) == []

    def test_a_resume_compares_against_the_paused_call(self, monkeypatch, caplog):
        paused = _make_llm(monkeypatch)
        _call(paused)
        state = paused.export_responses_state()
        assert state["tools_hash"]

        resumed = _make_llm(monkeypatch)
        resumed.import_responses_state(state)
        with caplog.at_level(logging.INFO):
            _call(resumed, tools=REORDERED)

        assert [r.changed for r in _changes(caplog)] == [["tools"]]
        sent = resumed.client.responses.create.call_args.kwargs
        assert sent["previous_response_id"] == state["response_id"]

    def test_a_resume_with_the_paused_tools_logs_nothing(self, monkeypatch, caplog):
        paused = _make_llm(monkeypatch)
        _call(paused)
        resumed = _make_llm(monkeypatch)
        resumed.import_responses_state(paused.export_responses_state())
        with caplog.at_level(logging.INFO):
            _call(resumed)

        assert _changes(caplog) == []


def test_the_change_is_a_span_attribute(monkeypatch):
    from docsgpt.tracing import llm as tracing_llm

    monkeypatch.setattr(tracing_llm.settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(tracing_llm, "record_llm_metrics", lambda **kwargs: None)
    span = MagicMock()
    llm = types.SimpleNamespace(provider_name="openai", _prefix_changed="tools")

    tracing_llm.finish_llm_call(span, llm, "gpt-6.1-sol", {}, duration_ms=1, error=None)

    assert span.end.call_args.kwargs["attributes"]["docsgpt.prefix_changed"] == "tools"
