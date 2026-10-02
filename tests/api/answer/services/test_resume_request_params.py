"""A stateful tool-result resume runs with the resuming request's params.

Background (b2b-sl rerun, 2026-10-02): a ``/v1`` client forces a final answer
by sending its tool results with ``tool_choice: "none"``. The translator puts
that into ``llm_params``, a fresh turn hands them to the agent, but the
stateful resume (``resume_from_tool_actions``) built its agent without them:
the call went out with ``tool_choice`` unset, the model called a tool again,
and the client got an empty answer. ``max_tokens``, ``json_object`` mode and
``strict: false`` were lost the same way.
"""

from __future__ import annotations

import copy
import types
import uuid
from unittest.mock import MagicMock

import pytest

from docsgpt.core.model_settings import ModelCapabilities

pytestmark = pytest.mark.unit

AGENT = "11111111-1111-1111-1111-111111111111"
OWNER = "owner"

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search the corpus.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "k": {"type": "integer"}},
            "required": ["query"],
        },
    },
}

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

MESSAGES = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "find the invoice total"},
]


def _state(**agent_config) -> dict:
    return {
        "messages": copy.deepcopy(MESSAGES),
        "pending_tool_calls": [
            {
                "call_id": "call_1",
                "name": "search",
                "tool_name": "search",
                "action_name": "search",
                "llm_name": "search",
                "arguments": {"query": "invoice", "k": 3},
            }
        ],
        "tools_dict": {},
        "tool_schemas": [SEARCH_TOOL],
        "client_tools": [SEARCH_TOOL],
        "agent_config": {
            "model_id": "gpt-test",
            "llm_name": "openai",
            "api_key": "k",
            "user_api_key": None,
            "agent_type": "ClassicAgent",
            "agent_id": None,
            "prompt": "sys",
            "json_schema": None,
            **agent_config,
        },
    }


def _openai_llm(monkeypatch, api_flavor: str):
    """A real ``OpenAILLM`` with its client mocked out."""
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
            OPENAI_RESPONSES_STORE=False,
            OPENAI_REASONING_SUMMARY="auto",
            OPENAI_RESPONSES_TRUNCATION_AUTO=False,
            OPENAI_PROMPT_CACHE_KEY=False,
            OPENAI_PROMPT_CACHE_RETENTION=None,
        ),
    )
    from docsgpt.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = ModelCapabilities(
        supports_tools=True, supports_structured_output=True, api_flavor=api_flavor,
    )
    # Skip the cache and token-usage decorators: the raw call is what is sent.
    llm.gen_stream = lambda **kwargs: llm._raw_gen_stream(llm, **kwargs)
    done = types.SimpleNamespace(
        type="response.completed",
        response=types.SimpleNamespace(id="resp_1", output=[], usage=None, status="completed"),
    )
    llm.client.responses.create = MagicMock(return_value=[done])
    llm.client.chat.completions.create = MagicMock(return_value=[])
    return llm


@pytest.fixture
def resume(monkeypatch):
    """Resume a saved state with a given request body; returns the agent kwargs."""
    from docsgpt.agents import agent_creator as ac_mod
    from docsgpt.api.answer.services import continuation_service as cont_mod
    from docsgpt.api.answer.services import stream_processor as sp_mod
    from docsgpt.llm import llm_creator as llm_creator_mod
    from docsgpt.llm.handlers import handler_creator as handler_mod

    def _run(state: dict, data: dict, *, llm=None, real_agent: bool = False):
        cont_service = MagicMock()
        cont_service.claim_state.return_value = copy.deepcopy(state)
        monkeypatch.setattr(cont_mod, "ContinuationService", lambda: cont_service)
        monkeypatch.setattr(
            llm_creator_mod.LLMCreator, "create_llm", lambda *a, **kw: llm or MagicMock(),
        )
        created = {}
        if not real_agent:
            monkeypatch.setattr(handler_mod.LLMHandlerCreator, "create_handler", lambda *a, **kw: MagicMock())
            monkeypatch.setattr(
                ac_mod.AgentCreator, "create_agent", lambda *a, **kw: created.update(kw) or MagicMock(),
            )
        processor = sp_mod.StreamProcessor(dict(data), {"sub": OWNER})
        processor.trace_source = "v1"
        result = processor.resume_from_tool_actions(
            tool_actions=[{"call_id": "call_1", "result": "total: 41.20"}],
            conversation_id=str(uuid.uuid4()),
        )
        return result[0], created

    return _run


class TestResumeAgentKwargs:
    def test_request_llm_params_reach_the_resumed_agent(self, resume):
        params = {"tool_choice": "none", "max_completion_tokens": 512, "temperature": 0.1}
        _, kwargs = resume(_state(), {"llm_params": params})
        assert kwargs["llm_params"] == params

    def test_no_request_params_means_none_not_the_paused_ones(self, resume):
        _, kwargs = resume(_state(), {})
        assert kwargs["llm_params"] == {}
        assert kwargs["json_object"] is False

    def test_json_object_mode_survives_the_resume(self, resume):
        _, kwargs = resume(_state(json_schema=SCHEMA), {"json_object": True})
        assert kwargs["json_object"] is True
        # As on a fresh turn, json_object beats a configured schema.
        assert kwargs["json_schema"] is None

    def test_a_request_schema_and_strict_false_win(self, resume):
        other = {"type": "object", "properties": {"total": {"type": "number"}}}
        _, kwargs = resume(
            _state(json_schema=SCHEMA, json_schema_strict=True),
            {"json_schema": other, "json_schema_strict": False},
        )
        assert kwargs["json_schema"] == other
        assert kwargs["json_schema_strict"] is False

    def test_without_a_request_schema_the_paused_one_and_its_strictness_stay(self, resume):
        _, kwargs = resume(_state(json_schema=SCHEMA, json_schema_strict=False), {})
        assert kwargs["json_schema"] == SCHEMA
        assert kwargs["json_schema_strict"] is False

    def test_paused_state_without_strict_defaults_to_strict(self, resume):
        _, kwargs = resume(_state(json_schema=SCHEMA), {})
        assert kwargs["json_schema_strict"] is True


class TestResumedCallCarriesTheParams:
    """Through a real agent and ``OpenAILLM``, down to the provider request."""

    def test_responses_request(self, monkeypatch, resume):
        llm = _openai_llm(monkeypatch, "responses")
        spy = MagicMock(wraps=llm._build_responses_params)
        monkeypatch.setattr(llm, "_build_responses_params", spy)
        agent, _ = resume(
            _state(),
            {"llm_params": {"tool_choice": "none", "max_tokens": 256, "parallel_tool_calls": False}},
            llm=llm,
            real_agent=True,
        )

        list(agent._llm_gen(copy.deepcopy(MESSAGES)))

        assert spy.call_args.kwargs["kwargs"]["tool_choice"] == "none"
        sent = llm.client.responses.create.call_args.kwargs
        assert sent["tool_choice"] == "none"
        assert sent["max_output_tokens"] == 256
        assert sent["parallel_tool_calls"] is False

    def test_responses_request_json_object(self, monkeypatch, resume):
        llm = _openai_llm(monkeypatch, "responses")
        agent, _ = resume(_state(), {"json_object": True}, llm=llm, real_agent=True)

        list(agent._llm_gen(copy.deepcopy(MESSAGES)))

        sent = llm.client.responses.create.call_args.kwargs
        assert sent["text"]["format"]["type"] == "json_object"

    def test_chat_completions_request(self, monkeypatch, resume):
        llm = _openai_llm(monkeypatch, "chat_completions")
        agent, _ = resume(
            _state(),
            {"llm_params": {"tool_choice": "none", "max_tokens": 256, "temperature": 0.2, "seed": 7}},
            llm=llm,
            real_agent=True,
        )

        list(agent._llm_gen(copy.deepcopy(MESSAGES)))

        sent = llm.client.chat.completions.create.call_args.kwargs
        assert sent["tool_choice"] == "none"
        assert sent["max_completion_tokens"] == 256
        assert sent["temperature"] == 0.2
        assert sent["seed"] == 7
