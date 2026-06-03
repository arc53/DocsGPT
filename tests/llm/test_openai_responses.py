"""Unit tests for the OpenAI Responses API path in application/llm/openai.py.

Covers the api_flavor gating, Chat-Completions -> Responses request
translation, tool/structured-output mapping, reasoning-item carryover, the
streaming-event normalization into the existing handler contract, and the
previous_response_id trimming used for cross-turn chaining.
"""

import types
from unittest.mock import MagicMock

import pytest

from application.core.model_settings import ModelCapabilities


def _make_llm(monkeypatch, capabilities=None, store_responses=False):
    monkeypatch.setattr("application.llm.openai.OpenAI", MagicMock())
    monkeypatch.setattr(
        "application.llm.openai.StorageCreator",
        types.SimpleNamespace(get_storage=lambda: None),
    )
    monkeypatch.setattr(
        "application.llm.openai.settings",
        types.SimpleNamespace(
            OPENAI_API_KEY="k",
            API_KEY="k",
            OPENAI_BASE_URL="",
            AZURE_DEPLOYMENT_NAME="dep",
            OPENAI_RESPONSES_STORE=store_responses,
        ),
    )
    from application.llm.openai import OpenAILLM

    llm = OpenAILLM(api_key="k")
    llm.capabilities = capabilities
    return llm


def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _responses_caps(reasoning_effort=None):
    return ModelCapabilities(
        supports_tools=True,
        supports_structured_output=True,
        api_flavor="responses",
        reasoning_effort=reasoning_effort,
    )


# ── api_flavor gating ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_uses_responses_api_true(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    assert llm._uses_responses_api() is True


@pytest.mark.unit
def test_uses_responses_api_false_for_chat(monkeypatch):
    caps = ModelCapabilities(api_flavor="chat_completions")
    assert _make_llm(monkeypatch, caps)._uses_responses_api() is False


@pytest.mark.unit
def test_uses_responses_api_false_without_caps(monkeypatch):
    assert _make_llm(monkeypatch, None)._uses_responses_api() is False


# ── message translation ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_to_responses_input_tool_roundtrip(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "search", "arguments": '{"q":"x"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "assistant", "content": "final"},
    ]
    items = llm._to_responses_input(messages)
    assert items == [
        {"role": "system", "content": [{"type": "input_text", "text": "sys"}]},
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "search",
            "arguments": '{"q":"x"}',
        },
        {"type": "function_call_output", "call_id": "call_1", "output": "result"},
        # The Responses API requires output_text (not input_text) for the
        # assistant role; input_text 400s. Locked in here so it can't regress.
        {"role": "assistant", "content": [{"type": "output_text", "text": "final"}]},
    ]


@pytest.mark.unit
def test_to_responses_input_reinjects_reasoning(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    reasoning_item = {
        "type": "reasoning", "id": "rs_1",
        "encrypted_content": "enc", "summary": [],
    }
    llm._reasoning_for_calls = {"call_1": [reasoning_item]}
    messages = [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1",
            "type": "function",
            "function": {"name": "t", "arguments": "{}"},
        }],
    }]
    items = llm._to_responses_input(messages)
    # Reasoning item is emitted immediately before its function call.
    assert items[0] == reasoning_item
    assert items[1]["type"] == "function_call"
    assert items[1]["call_id"] == "call_1"


@pytest.mark.unit
def test_to_responses_input_multimodal_image(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
        ],
    }]
    items = llm._to_responses_input(messages)
    assert items == [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "look"},
            {
                "type": "input_image",
                "image_url": "data:image/png;base64,xx",
                "detail": "auto",
            },
        ],
    }]


@pytest.mark.unit
def test_to_responses_tools_flatten(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    tools = [{
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    assert llm._to_responses_tools(tools) == [{
        "type": "function",
        "name": "search",
        "description": "Search",
        "parameters": {"type": "object", "properties": {}},
        "strict": False,
    }]


@pytest.mark.unit
def test_responses_text_format_json_schema(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    rf = {
        "type": "json_schema",
        "json_schema": {"name": "out", "schema": {"type": "object"}, "strict": True},
    }
    assert llm._responses_text_format(rf) == {
        "type": "json_schema", "name": "out",
        "schema": {"type": "object"}, "strict": True,
    }


@pytest.mark.unit
def test_trim_for_previous_response(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old q"},
        {"role": "assistant", "content": "old a"},
        {"role": "user", "content": "new q"},
    ]
    trimmed = llm._trim_for_previous_response(messages)
    # System stays; everything up to and including the last assistant text
    # is dropped (the server already holds it), leaving the new user turn.
    assert trimmed == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "new q"},
    ]


# ── request params ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_build_responses_params_stateless(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(reasoning_effort="high"))
    params = llm._build_responses_params(
        "gpt-5.5", [{"role": "user", "content": []}], tools=None,
        response_format=None, previous_response_id=None, stream=True,
        kwargs={"max_completion_tokens": 256},
    )
    assert params["model"] == "gpt-5.5"
    assert params["stream"] is True
    assert params["max_output_tokens"] == 256
    assert params["reasoning"] == {"effort": "high", "summary": "auto"}
    assert params["store"] is False
    assert params["include"] == ["reasoning.encrypted_content"]
    assert "previous_response_id" not in params


@pytest.mark.unit
def test_build_responses_params_store_with_previous_id(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps(), store_responses=True)
    params = llm._build_responses_params(
        "gpt-5.5", [], tools=None, response_format=None,
        previous_response_id="resp_abc", stream=False, kwargs={},
    )
    assert params["store"] is True
    assert params["previous_response_id"] == "resp_abc"
    # Encrypted reasoning is always requested so in-turn carryover works
    # regardless of server-side retention.
    assert params["include"] == ["reasoning.encrypted_content"]


# ── streaming normalization into the existing handler contract ───────────────


@pytest.mark.unit
def test_responses_gen_stream_text_and_tools(monkeypatch):
    from application.llm.handlers.openai import OpenAILLMHandler

    llm = _make_llm(monkeypatch, _responses_caps())
    events = [
        _ns(type="response.output_text.delta", delta="Hel"),
        _ns(type="response.output_text.delta", delta="lo"),
        _ns(type="response.reasoning_summary_text.delta", delta="thinking"),
        _ns(
            type="response.output_item.added",
            output_index=0,
            item=_ns(type="function_call", call_id="call_1", name="search", id="fc_1"),
        ),
        _ns(type="response.function_call_arguments.delta", output_index=0, delta='{"q":'),
        _ns(
            type="response.function_call_arguments.done",
            output_index=0,
            arguments='{"q":"hi"}',
        ),
        _ns(
            type="response.output_item.done",
            item=_ns(type="reasoning", id="rs_1", encrypted_content="enc", summary=[]),
        ),
        _ns(type="response.completed", response=_ns(id="resp_1")),
    ]
    llm.client.responses.create = MagicMock(return_value=events)

    out = list(llm._responses_gen_stream("gpt-5.5", [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}]))

    assert "Hel" in out and "lo" in out
    assert {"type": "thought", "thought": "thinking"} in out
    choice = out[-1]
    parsed = OpenAILLMHandler().parse_response(choice)
    assert parsed.finish_reason == "tool_calls"
    assert len(parsed.tool_calls) == 1
    tc = parsed.tool_calls[0]
    assert tc.id == "call_1"
    assert tc.name == "search"
    assert tc.arguments == '{"q":"hi"}'
    # Reasoning captured for in-turn carryover, last response id recorded.
    assert llm._reasoning_for_calls["call_1"][0]["encrypted_content"] == "enc"
    assert llm._last_response_id == "resp_1"


@pytest.mark.unit
def test_responses_gen_stream_text_only(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    events = [
        _ns(type="response.output_text.delta", delta="Answer"),
        _ns(type="response.completed", response=_ns(id="resp_2")),
    ]
    llm.client.responses.create = MagicMock(return_value=events)
    out = list(llm._responses_gen_stream("gpt-5.5", [{"role": "user", "content": "hi"}], tools=None))
    assert out == ["Answer"]
    assert llm._last_response_id == "resp_2"


@pytest.mark.unit
def test_responses_gen_stream_parallel_tool_calls(monkeypatch):
    from application.llm.handlers.openai import OpenAILLMHandler

    llm = _make_llm(monkeypatch, _responses_caps())
    events = [
        _ns(
            type="response.output_item.added", output_index=0,
            item=_ns(type="function_call", call_id="call_a", name="t1", id="fc_a"),
        ),
        _ns(
            type="response.output_item.added", output_index=1,
            item=_ns(type="function_call", call_id="call_b", name="t2", id="fc_b"),
        ),
        _ns(type="response.function_call_arguments.delta", output_index=0, delta='{"a":'),
        _ns(type="response.function_call_arguments.done", output_index=0, arguments='{"a":1}'),
        _ns(type="response.function_call_arguments.done", output_index=1, arguments='{"b":2}'),
        _ns(type="response.completed", response=_ns(id="resp_p")),
    ]
    llm.client.responses.create = MagicMock(return_value=events)
    out = list(llm._responses_gen_stream("gpt-5.5", [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "t1", "parameters": {}}}]))
    parsed = OpenAILLMHandler().parse_response(out[-1])
    assert parsed.finish_reason == "tool_calls"
    assert [tc.id for tc in parsed.tool_calls] == ["call_a", "call_b"]
    assert [tc.index for tc in parsed.tool_calls] == [0, 1]
    assert parsed.tool_calls[0].arguments == '{"a":1}'
    assert parsed.tool_calls[1].arguments == '{"b":2}'


@pytest.mark.unit
def test_responses_gen_stream_error_event_raises(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    events = [
        _ns(type="response.output_text.delta", delta="partial"),
        _ns(type="response.failed", response=_ns(error="boom")),
    ]
    llm.client.responses.create = MagicMock(return_value=events)
    with pytest.raises(RuntimeError):
        list(llm._responses_gen_stream("gpt-5.5", [{"role": "user", "content": "hi"}], tools=None))


@pytest.mark.unit
def test_responses_gen_nonstream_tools(monkeypatch):
    from application.llm.handlers.openai import OpenAILLMHandler

    llm = _make_llm(monkeypatch, _responses_caps())
    response = _ns(
        id="resp_3",
        output=[
            _ns(type="reasoning", id="rs", encrypted_content="e", summary=[]),
            _ns(type="message", content=[_ns(type="output_text", text="Answer")]),
            _ns(type="function_call", call_id="c1", name="t", arguments="{}", id="fc"),
        ],
    )
    llm.client.responses.create = MagicMock(return_value=response)
    choice = llm._responses_gen("gpt-5.5", [{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "t", "parameters": {}}}])
    parsed = OpenAILLMHandler().parse_response(choice)
    assert parsed.finish_reason == "tool_calls"
    assert parsed.tool_calls[0].id == "c1"
    assert llm._reasoning_for_calls["c1"][0]["encrypted_content"] == "e"


@pytest.mark.unit
def test_responses_gen_nonstream_text(monkeypatch):
    llm = _make_llm(monkeypatch, _responses_caps())
    response = _ns(
        id="resp_4",
        output=[_ns(type="message", content=[_ns(type="output_text", text="Hi there")])],
    )
    llm.client.responses.create = MagicMock(return_value=response)
    result = llm._responses_gen("gpt-5.5", [{"role": "user", "content": "hi"}], tools=None)
    assert result == "Hi there"


# ── capability plumbing / yaml ───────────────────────────────────────────────


@pytest.mark.unit
def test_capability_field_rejects_bad_api_flavor():
    from application.core.model_yaml import _CapabilityFields

    with pytest.raises(ValueError):
        _CapabilityFields(api_flavor="grpc")


@pytest.mark.unit
def test_capability_field_rejects_bad_reasoning_effort():
    from application.core.model_yaml import _CapabilityFields

    with pytest.raises(ValueError):
        _CapabilityFields(reasoning_effort="extreme")


@pytest.mark.unit
def test_builtin_gpt55_opts_into_responses():
    from application.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls

    catalogs = load_model_yamls([BUILTIN_MODELS_DIR])
    models = {m.id: m for c in catalogs for m in c.models}
    gpt = models["gpt-5.5"]
    assert gpt.capabilities.api_flavor == "responses"
    assert gpt.capabilities.reasoning_effort == "medium"


@pytest.mark.unit
def test_builtin_default_models_stay_chat_completions():
    from application.core.model_yaml import BUILTIN_MODELS_DIR, load_model_yamls

    catalogs = load_model_yamls([BUILTIN_MODELS_DIR])
    models = {m.id: m for c in catalogs for m in c.models}
    assert models["gpt-5.4-mini"].capabilities.api_flavor == "chat_completions"
