"""Unit tests for application/llm/anthropic.py — AnthropicLLM (Messages API).

Covers the migration off the retired Text Completions API:
  - system extraction into the top-level ``system`` parameter
  - full-history preservation (the old code kept only messages[0] and [-1])
  - OpenAI -> Anthropic tool schema translation
  - tool_use / tool_result round trip in both directions
  - streaming text / thinking / tool-call chunks and close() cleanup
  - attachments (image + PDF document blocks)
  - provider-reported token usage
"""

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Fake anthropic module
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(
        self,
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


def text_block(text):
    return types.SimpleNamespace(type="text", text=text)


def tool_use_block(block_id, name, payload):
    return types.SimpleNamespace(
        type="tool_use", id=block_id, name=name, input=payload
    )


def thinking_block(thinking):
    return types.SimpleNamespace(type="thinking", thinking=thinking)


def fake_message(content, stop_reason="end_turn", usage=None):
    return types.SimpleNamespace(
        type="message",
        role="assistant",
        content=content,
        stop_reason=stop_reason,
        usage=usage if usage is not None else _FakeUsage(10, 5),
    )


# --- streaming events -------------------------------------------------------


def ev_message_start(usage):
    return types.SimpleNamespace(
        type="message_start", message=types.SimpleNamespace(usage=usage)
    )


def ev_block_start(index, block):
    return types.SimpleNamespace(
        type="content_block_start", index=index, content_block=block
    )


def ev_text_delta(index, text):
    return types.SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=types.SimpleNamespace(type="text_delta", text=text),
    )


def ev_thinking_delta(index, thinking):
    return types.SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=types.SimpleNamespace(type="thinking_delta", thinking=thinking),
    )


def ev_json_delta(index, partial_json):
    return types.SimpleNamespace(
        type="content_block_delta",
        index=index,
        delta=types.SimpleNamespace(
            type="input_json_delta", partial_json=partial_json
        ),
    )


def ev_block_stop(index):
    return types.SimpleNamespace(type="content_block_stop", index=index)


def ev_message_delta(stop_reason, usage=None):
    return types.SimpleNamespace(
        type="message_delta",
        delta=types.SimpleNamespace(stop_reason=stop_reason),
        usage=usage if usage is not None else _FakeUsage(output_tokens=7),
    )


def ev_message_stop():
    return types.SimpleNamespace(type="message_stop")


class _FakeStream:
    """Iterable stand-in for the SDK's ``Stream``; records close()."""

    def __init__(self, events):
        self._events = list(events)
        self.closed = False

    def __iter__(self):
        return iter(self._events)

    def close(self):
        self.closed = True


class _FakeMessages:
    def __init__(self):
        self.last_kwargs = None
        self.response = fake_message([text_block("final")])
        self.stream_events = [
            ev_message_start(_FakeUsage(input_tokens=11)),
            ev_block_start(0, types.SimpleNamespace(type="text", text="")),
            ev_text_delta(0, "s1"),
            ev_text_delta(0, "s2"),
            ev_block_stop(0),
            ev_message_delta("end_turn", _FakeUsage(output_tokens=3)),
            ev_message_stop(),
        ]
        self.last_stream = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            self.last_stream = _FakeStream(self.stream_events)
            return self.last_stream
        return self.response


class _FakeAnthropic:
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url
        self.messages = _FakeMessages()


@pytest.fixture(autouse=True)
def patch_anthropic():
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeAnthropic

    modules_to_remove = [key for key in sys.modules if key.startswith("anthropic")]
    for key in modules_to_remove:
        sys.modules.pop(key, None)
    sys.modules["anthropic"] = fake

    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]
    yield
    sys.modules.pop("anthropic", None)
    if "application.llm.anthropic" in sys.modules:
        del sys.modules["application.llm.anthropic"]


def _ctx_manager(data):
    """Create a simple context manager returning an object with .read()."""
    import contextlib

    @contextlib.contextmanager
    def cm():
        yield types.SimpleNamespace(read=lambda: data)

    return cm()


@pytest.fixture
def llm():
    from application.llm.anthropic import AnthropicLLM

    instance = AnthropicLLM(api_key="test-key")
    instance.storage = types.SimpleNamespace(
        get_file=lambda path: _ctx_manager(b"img_bytes"),
    )
    return instance


def _sent(llm):
    """kwargs of the most recent messages.create call."""
    return llm.anthropic.messages.last_kwargs


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnthropicConstructor:

    def test_api_key_set(self):
        from application.llm.anthropic import AnthropicLLM

        assert AnthropicLLM(api_key="custom-key").api_key == "custom-key"

    def test_base_url_passed(self):
        from application.llm.anthropic import AnthropicLLM

        instance = AnthropicLLM(api_key="k", base_url="https://custom.api")
        assert instance.anthropic.base_url == "https://custom.api"

    def test_no_base_url(self):
        from application.llm.anthropic import AnthropicLLM

        assert AnthropicLLM(api_key="k").anthropic.base_url is None

    def test_provider_name(self):
        from application.llm.anthropic import AnthropicLLM

        assert AnthropicLLM.provider_name == "anthropic"


# ---------------------------------------------------------------------------
# Message mapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMessageMapping:

    def test_uses_messages_api_not_completions(self, llm):
        llm._raw_gen(llm, model="claude-x", messages=[{"role": "user", "content": "hi"}])
        assert _sent(llm)["model"] == "claude-x"
        assert "prompt" not in _sent(llm)
        assert "max_tokens_to_sample" not in _sent(llm)

    def test_system_extracted_to_system_param(self, llm):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)
        assert sent["system"] == "You are helpful."
        assert [m["role"] for m in sent["messages"]] == ["user"]

    def test_multiple_system_messages_concatenated(self, llm):
        messages = [
            {"role": "system", "content": "A"},
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "B"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        assert _sent(llm)["system"] == "A\n\nB"

    def test_no_system_param_when_absent(self, llm):
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert "system" not in _sent(llm)

    def test_system_list_content_extracted(self, llm):
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "sys text"}]},
            {"role": "user", "content": "hi"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        assert _sent(llm)["system"] == "sys text"

    def test_full_history_preserved(self, llm):
        """Regression: the old code flattened to messages[0] + messages[-1],
        silently discarding every intermediate turn."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q3"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        assert [m["role"] for m in sent] == [
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
        ]
        texts = [m["content"][0]["text"] for m in sent]
        assert texts == ["q1", "a1", "q2", "a2", "q3"]

    def test_consecutive_same_role_merged(self, llm):
        messages = [
            {"role": "user", "content": "part one"},
            {"role": "user", "content": "part two"},
            {"role": "assistant", "content": "ok"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        assert [m["role"] for m in sent] == ["user", "assistant"]
        assert [b["text"] for b in sent[0]["content"]] == ["part one", "part two"]

    def test_leading_assistant_gets_synthetic_user(self, llm):
        messages = [
            {"role": "assistant", "content": "I spoke first"},
            {"role": "user", "content": "hi"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        assert sent[0]["role"] == "user"
        assert sent[1]["role"] == "assistant"

    def test_empty_messages_does_not_crash(self, llm):
        llm._raw_gen(llm, model="m", messages=[])
        sent = _sent(llm)["messages"]
        assert len(sent) == 1
        assert sent[0]["role"] == "user"

    def test_system_only_messages_still_sends_a_user_turn(self, llm):
        llm._raw_gen(llm, model="m", messages=[{"role": "system", "content": "s"}])
        sent = _sent(llm)
        assert sent["system"] == "s"
        assert sent["messages"][0]["role"] == "user"

    def test_empty_content_messages_dropped(self, llm):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "again"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        # Empty assistant turn is dropped, so the two user turns merge.
        assert [m["role"] for m in sent] == ["user"]
        assert [b["text"] for b in sent[0]["content"]] == ["hi", "again"]

    def test_native_image_blocks_passed_through(self, llm):
        image = {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
        }
        messages = [{"role": "user", "content": [{"type": "text", "text": "look"}, image]}]
        llm._raw_gen(llm, model="m", messages=messages)
        content = _sent(llm)["messages"][0]["content"]
        assert content[1] == image

    def test_unknown_content_block_dropped(self, llm):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
                ],
            }
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        content = _sent(llm)["messages"][0]["content"]
        assert content == [{"type": "text", "text": "hello"}]


# ---------------------------------------------------------------------------
# Tool schema translation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolTranslation:

    def test_openai_tool_schema_translated(self, llm):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "parameters": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                },
            }
        ]
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}], tools=tools)
        sent_tools = _sent(llm)["tools"]
        assert sent_tools == [
            {
                "name": "get_weather",
                "description": "Get the weather",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            }
        ]

    def test_tool_without_parameters_gets_empty_object_schema(self, llm):
        tools = [{"type": "function", "function": {"name": "ping"}}]
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}], tools=tools)
        assert _sent(llm)["tools"][0]["input_schema"] == {
            "type": "object",
            "properties": {},
        }

    def test_no_tools_key_when_none(self, llm):
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert "tools" not in _sent(llm)

    def test_tools_dropped_when_capabilities_deny(self, llm):
        llm.capabilities = types.SimpleNamespace(supports_tools=False)
        tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}], tools=tools)
        assert "tools" not in _sent(llm)


# ---------------------------------------------------------------------------
# tool_use / tool_result round trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolRoundTrip:

    def test_assistant_tool_calls_become_tool_use_blocks(self, llm):
        messages = [
            {"role": "user", "content": "weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Paris"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "sunny"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        assert [m["role"] for m in sent] == ["user", "assistant", "user"]
        assert sent[1]["content"] == [
            {
                "type": "tool_use",
                "id": "call_1",
                "name": "get_weather",
                "input": {"city": "Paris"},
            }
        ]
        assert sent[2]["content"] == [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "sunny"}
        ]

    def test_assistant_text_and_tool_calls_both_kept(self, llm):
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "Let me check.",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {"name": "look", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        assistant = _sent(llm)["messages"][1]["content"]
        assert assistant[0] == {"type": "text", "text": "Let me check."}
        assert assistant[1]["type"] == "tool_use"

    def test_malformed_tool_arguments_become_empty_input(self, llm):
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "f", "arguments": "not json"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "r"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        assert _sent(llm)["messages"][1]["content"][0]["input"] == {}

    def test_parallel_tool_results_merged_into_one_user_message(self, llm):
        """Anthropic requires every tool_result for a batch in a single user
        turn; the internal format emits one ``role: tool`` message per call."""
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        sent = _sent(llm)["messages"]
        assert [m["role"] for m in sent] == ["user", "assistant", "user"]
        assert len(sent[1]["content"]) == 2
        results = sent[2]["content"]
        assert [b["tool_use_id"] for b in results] == ["c1", "c2"]
        assert all(b["type"] == "tool_result" for b in results)

    def test_tool_message_content_stringified(self, llm):
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "f", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": {"k": "v"}},
        ]
        llm._raw_gen(llm, model="m", messages=messages)
        block = _sent(llm)["messages"][2]["content"][0]
        assert isinstance(block["content"], str)
        assert "k" in block["content"]


# ---------------------------------------------------------------------------
# Non-streaming return shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGen:

    def test_returns_text_when_no_tools(self, llm):
        llm.anthropic.messages.response = fake_message(
            [text_block("hello "), text_block("world")]
        )
        out = llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert out == "hello world"

    def test_returns_message_object_when_tools(self, llm):
        message = fake_message(
            [tool_use_block("c1", "f", {"a": 1})], stop_reason="tool_use"
        )
        llm.anthropic.messages.response = message
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
        out = llm._raw_gen(
            llm, model="m", messages=[{"role": "user", "content": "hi"}], tools=tools
        )
        assert out is message

    def test_default_max_tokens_is_workable(self, llm):
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert _sent(llm)["max_tokens"] >= 4096

    def test_explicit_max_tokens_forwarded(self, llm):
        llm._raw_gen(
            llm, model="m", messages=[{"role": "user", "content": "hi"}], max_tokens=1234
        )
        assert _sent(llm)["max_tokens"] == 1234

    def test_sampling_params_forwarded(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.3,
            top_p=0.9,
        )
        assert _sent(llm)["temperature"] == 0.3
        assert _sent(llm)["top_p"] == 0.9

    def test_openai_only_params_not_forwarded(self, llm):
        """OpenAI-shaped request params reach every provider via
        ``llm_params``; forwarding them verbatim would 400 on Anthropic."""
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            frequency_penalty=0.5,
            response_format={"type": "json_object"},
            reasoning_effort="high",
        )
        sent = _sent(llm)
        assert "frequency_penalty" not in sent
        assert "response_format" not in sent
        assert "reasoning_effort" not in sent

    def test_sets_finish_reason(self, llm):
        llm.anthropic.messages.response = fake_message(
            [text_block("x")], stop_reason="max_tokens"
        )
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert llm._last_finish_reason == "length"


# ---------------------------------------------------------------------------
# OpenAI-shaped request params (application/api/v1/translator.py forwards the
# caller's sampling params verbatim into ``llm_params``, which the agent merges
# into the gen kwargs for every provider).
# ---------------------------------------------------------------------------


TOOLS = [{"type": "function", "function": {"name": "f", "parameters": {}}}]


@pytest.mark.unit
class TestOpenAIParamTranslation:

    # --- tool_choice --------------------------------------------------------

    @pytest.mark.parametrize(
        "openai_value,expected",
        [
            ("auto", {"type": "auto"}),
            ("none", {"type": "none"}),
            ("required", {"type": "any"}),
        ],
    )
    def test_openai_string_tool_choice_translated(self, llm, openai_value, expected):
        """Anthropic 400s on the bare OpenAI strings; it wants an object."""
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_choice=openai_value,
        )
        assert _sent(llm)["tool_choice"] == expected

    def test_openai_function_tool_choice_translated(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_choice={"type": "function", "function": {"name": "f"}},
        )
        assert _sent(llm)["tool_choice"] == {"type": "tool", "name": "f"}

    def test_anthropic_shaped_tool_choice_passed_through(self, llm):
        choice = {"type": "tool", "name": "f", "disable_parallel_tool_use": True}
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_choice=choice,
        )
        assert _sent(llm)["tool_choice"] == choice

    def test_unrecognised_tool_choice_dropped(self, llm):
        """Dropping degrades to auto; forwarding would 400 the whole request."""
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            tool_choice="whatever",
        )
        assert "tool_choice" not in _sent(llm)

    def test_tool_choice_dropped_when_no_tools(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tool_choice="auto",
        )
        assert "tool_choice" not in _sent(llm)

    def test_tool_choice_translated_on_stream_path(self, llm):
        list(
            llm._raw_gen_stream(
                llm,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                tools=TOOLS,
                tool_choice="required",
            )
        )
        assert _sent(llm)["tool_choice"] == {"type": "any"}

    # --- max_completion_tokens ---------------------------------------------

    def test_max_completion_tokens_honoured(self, llm):
        """OpenAI's newer alias; ignoring it silently caps output at the default."""
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            max_completion_tokens=200,
        )
        assert _sent(llm)["max_tokens"] == 200

    def test_max_tokens_wins_over_alias(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=111,
            max_completion_tokens=222,
        )
        assert _sent(llm)["max_tokens"] == 111

    # --- stop ---------------------------------------------------------------

    def test_openai_stop_list_becomes_stop_sequences(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            stop=["END", "STOP"],
        )
        sent = _sent(llm)
        assert sent["stop_sequences"] == ["END", "STOP"]
        assert "stop" not in sent

    def test_openai_stop_string_becomes_single_sequence(self, llm):
        llm._raw_gen(
            llm, model="m", messages=[{"role": "user", "content": "hi"}], stop="END"
        )
        assert _sent(llm)["stop_sequences"] == ["END"]

    def test_explicit_stop_sequences_wins(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            stop=["from_openai"],
            stop_sequences=["native"],
        )
        assert _sent(llm)["stop_sequences"] == ["native"]

    def test_empty_stop_not_forwarded(self, llm):
        llm._raw_gen(
            llm, model="m", messages=[{"role": "user", "content": "hi"}], stop=[]
        )
        assert "stop_sequences" not in _sent(llm)


# ---------------------------------------------------------------------------
# Extended thinking
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtendedThinking:

    def test_thinking_forwarded_without_tools(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            thinking={"type": "adaptive"},
        )
        assert _sent(llm)["thinking"] == {"type": "adaptive"}

    @pytest.mark.parametrize("mode", ["enabled", "adaptive"])
    def test_thinking_dropped_when_tools_offered(self, llm, mode):
        """Anthropic requires the complete, signed thinking block to be replayed
        on the assistant turn that carries ``tool_use``. The signature is not
        available to this adapter (the stream drops ``signature_delta`` and the
        internal assistant-message shape has nowhere to carry it), so the
        follow-up round would 400. Drop thinking instead of breaking the turn."""
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            thinking={"type": mode, "budget_tokens": 2000},
        )
        assert "thinking" not in _sent(llm)

    def test_disabled_thinking_kept_with_tools(self, llm):
        llm._raw_gen(
            llm,
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            tools=TOOLS,
            thinking={"type": "disabled"},
        )
        assert _sent(llm)["thinking"] == {"type": "disabled"}

    def test_thinking_dropped_when_tools_offered_on_stream_path(self, llm):
        list(
            llm._raw_gen_stream(
                llm,
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                tools=TOOLS,
                thinking={"type": "adaptive"},
            )
        )
        assert "thinking" not in _sent(llm)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRawGenStream:

    def test_yields_text_deltas(self, llm):
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        )
        assert [c for c in chunks if isinstance(c, str)] == ["s1", "s2"]

    def test_stream_flag_sent(self, llm):
        list(llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}]))
        assert _sent(llm)["stream"] is True

    def test_yields_thought_chunks(self, llm):
        llm.anthropic.messages.stream_events = [
            ev_message_start(_FakeUsage(input_tokens=1)),
            ev_block_start(0, types.SimpleNamespace(type="thinking", thinking="")),
            ev_thinking_delta(0, "pondering"),
            ev_block_stop(0),
            ev_block_start(1, types.SimpleNamespace(type="text", text="")),
            ev_text_delta(1, "answer"),
            ev_block_stop(1),
            ev_message_delta("end_turn"),
        ]
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        )
        assert {"type": "thought", "thought": "pondering"} in chunks
        assert "answer" in chunks

    def test_yields_completed_tool_use_chunk(self, llm):
        llm.anthropic.messages.stream_events = [
            ev_message_start(_FakeUsage(input_tokens=1)),
            ev_block_start(
                0, types.SimpleNamespace(type="tool_use", id="c1", name="get_weather", input={})
            ),
            ev_json_delta(0, '{"ci'),
            ev_json_delta(0, 'ty": "Paris"}'),
            ev_block_stop(0),
            ev_message_delta("tool_use"),
        ]
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        )
        tool_chunks = [c for c in chunks if isinstance(c, dict) and c.get("type") == "tool_use"]
        assert tool_chunks == [
            {
                "type": "tool_use",
                "id": "c1",
                "name": "get_weather",
                "arguments": '{"city": "Paris"}',
            }
        ]

    def test_tool_use_with_no_input_deltas_gets_empty_object(self, llm):
        llm.anthropic.messages.stream_events = [
            ev_block_start(
                0, types.SimpleNamespace(type="tool_use", id="c1", name="ping", input={})
            ),
            ev_block_stop(0),
            ev_message_delta("tool_use"),
        ]
        chunks = list(
            llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        )
        tool_chunk = next(c for c in chunks if isinstance(c, dict) and c.get("type") == "tool_use")
        assert tool_chunk["arguments"] == "{}"

    def test_calls_close_on_response(self, llm):
        list(llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}]))
        assert llm.anthropic.messages.last_stream.closed is True

    def test_closes_response_on_early_abandon(self, llm):
        gen = llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        next(gen)
        gen.close()
        assert llm.anthropic.messages.last_stream.closed is True

    def test_sets_stream_reached_finish(self, llm):
        gen = llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}])
        assert llm._stream_reached_finish is False
        list(gen)
        assert llm._stream_reached_finish is True
        assert llm._last_finish_reason == "stop"

    def test_tool_stream_sets_tool_calls_finish_reason(self, llm):
        llm.anthropic.messages.stream_events = [
            ev_block_start(
                0, types.SimpleNamespace(type="tool_use", id="c1", name="f", input={})
            ),
            ev_json_delta(0, "{}"),
            ev_block_stop(0),
            ev_message_delta("tool_use"),
        ]
        list(llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}]))
        assert llm._last_finish_reason == "tool_calls"

    def test_stream_preserves_full_history(self, llm):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        list(llm._raw_gen_stream(llm, model="m", messages=messages))
        sent = _sent(llm)
        assert sent["system"] == "sys"
        assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]


# ---------------------------------------------------------------------------
# Token usage
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUsageReporting:

    def test_non_streaming_usage_recorded(self, llm):
        llm.anthropic.messages.response = fake_message(
            [text_block("x")], usage=_FakeUsage(input_tokens=100, output_tokens=20)
        )
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert llm._last_usage["prompt_tokens"] == 100
        assert llm._last_usage["completion_tokens"] == 20
        assert llm._last_usage["total_tokens"] == 120
        assert llm._last_usage_claimed is False

    def test_cache_tokens_folded_into_prompt_tokens(self, llm):
        """Anthropic reports cache reads/writes in bins SEPARATE from
        ``input_tokens``; dropping them under-bills the prompt."""
        llm.anthropic.messages.response = fake_message(
            [text_block("x")],
            usage=_FakeUsage(
                input_tokens=10,
                output_tokens=5,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=300,
            ),
        )
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert llm._last_usage["prompt_tokens"] == 510
        details = llm._last_usage["prompt_tokens_details"]
        assert details["cached_tokens"] == 300
        assert details["cache_creation_tokens"] == 200

    def test_zero_usage_does_not_clobber_estimates(self, llm):
        llm.anthropic.messages.response = fake_message(
            [text_block("x")], usage=_FakeUsage(0, 0)
        )
        llm._raw_gen(llm, model="m", messages=[{"role": "user", "content": "hi"}])
        assert llm._last_usage is None

    def test_streaming_usage_recorded(self, llm):
        llm.anthropic.messages.stream_events = [
            ev_message_start(
                _FakeUsage(input_tokens=40, cache_read_input_tokens=60)
            ),
            ev_block_start(0, types.SimpleNamespace(type="text", text="")),
            ev_text_delta(0, "hi"),
            ev_block_stop(0),
            ev_message_delta("end_turn", _FakeUsage(output_tokens=9)),
        ]
        list(llm._raw_gen_stream(llm, model="m", messages=[{"role": "user", "content": "q"}]))
        assert llm._last_usage["prompt_tokens"] == 100
        assert llm._last_usage["completion_tokens"] == 9
        assert llm._last_usage_claimed is False


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCapabilities:

    def test_supports_tools_default(self, llm):
        assert llm._supports_tools() is True

    def test_supports_tools_respects_capabilities(self, llm):
        llm.capabilities = types.SimpleNamespace(supports_tools=False)
        assert llm._supports_tools() is False


# ---------------------------------------------------------------------------
# get_supported_attachment_types
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetSupportedAttachmentTypes:

    def test_returns_image_types(self, llm):
        result = llm.get_supported_attachment_types()
        assert "image/png" in result
        assert "image/jpeg" in result
        assert "image/webp" in result
        assert "image/gif" in result

    def test_pdf_supported_natively(self, llm):
        assert "application/pdf" in llm.get_supported_attachment_types()


# ---------------------------------------------------------------------------
# prepare_messages_with_attachments
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrepareMessagesWithAttachments:

    def test_no_attachments_returns_same(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        assert llm.prepare_messages_with_attachments(msgs) == msgs

    def test_empty_attachments_returns_same(self, llm):
        msgs = [{"role": "user", "content": "hi"}]
        assert llm.prepare_messages_with_attachments(msgs, []) == msgs

    def test_image_with_preconverted_data(self, llm):
        msgs = [{"role": "user", "content": "look"}]
        result = llm.prepare_messages_with_attachments(
            msgs, [{"mime_type": "image/png", "data": "AABBCC"}]
        )
        user_msg = next(m for m in result if m["role"] == "user")
        img = next(p for p in user_msg["content"] if p.get("type") == "image")
        assert img["source"] == {
            "type": "base64",
            "media_type": "image/png",
            "data": "AABBCC",
        }

    def test_image_from_storage(self, llm):
        llm.storage = types.SimpleNamespace(
            get_file=lambda p: _ctx_manager(b"raw_image_bytes"),
        )
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "look"}],
            [{"mime_type": "image/jpeg", "path": "/tmp/img.jpg"}],
        )
        img = next(
            p
            for p in result[0]["content"]
            if p.get("type") == "image"
        )
        assert img["source"]["media_type"] == "image/jpeg"
        assert len(img["source"]["data"]) > 0

    def test_jpg_media_type_normalised_to_jpeg(self, llm):
        """``image/jpg`` is not a media type the Messages API accepts."""
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "look"}],
            [{"mime_type": "image/jpg", "data": "AAA"}],
        )
        img = next(p for p in result[0]["content"] if p.get("type") == "image")
        assert img["source"]["media_type"] == "image/jpeg"

    def test_pdf_becomes_document_block(self, llm):
        llm.storage = types.SimpleNamespace(get_file=lambda p: _ctx_manager(b"%PDF-1.4"))
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "read"}],
            [{"mime_type": "application/pdf", "path": "/tmp/f.pdf"}],
        )
        doc = next(p for p in result[0]["content"] if p.get("type") == "document")
        assert doc["source"]["type"] == "base64"
        assert doc["source"]["media_type"] == "application/pdf"
        assert len(doc["source"]["data"]) > 0

    def test_pdf_blocks_survive_message_mapping(self, llm):
        """The document block must reach ``messages.create`` intact."""
        llm.storage = types.SimpleNamespace(get_file=lambda p: _ctx_manager(b"%PDF-1.4"))
        prepared = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "read"}],
            [{"mime_type": "application/pdf", "path": "/tmp/f.pdf"}],
        )
        llm._raw_gen(llm, model="m", messages=prepared)
        content = _sent(llm)["messages"][0]["content"]
        assert any(b.get("type") == "document" for b in content)

    def test_no_user_message_creates_one(self, llm):
        result = llm.prepare_messages_with_attachments(
            [{"role": "system", "content": "sys"}],
            [{"mime_type": "image/png", "data": "AAA"}],
        )
        assert len([m for m in result if m["role"] == "user"]) == 1

    def test_image_error_adds_text_fallback(self, llm):
        def bad_storage(path):
            raise Exception("storage error")

        llm.storage = types.SimpleNamespace(get_file=bad_storage)
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "look"}],
            [{"mime_type": "image/png", "path": "/bad.png", "content": "fb"}],
        )
        text_parts = [
            p
            for p in result[0]["content"]
            if p.get("type") == "text" and "could not" in p.get("text", "").lower()
        ]
        assert len(text_parts) == 1

    def test_unsupported_attachment_ignored(self, llm):
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": "look"}],
            [{"mime_type": "text/csv"}],
        )
        assert isinstance(result[0]["content"], list)
        assert len(result[0]["content"]) == 1

    def test_content_not_list_becomes_empty(self, llm):
        result = llm.prepare_messages_with_attachments(
            [{"role": "user", "content": 999}],
            [{"mime_type": "image/png", "data": "AAA"}],
        )
        assert isinstance(result[0]["content"], list)


# ---------------------------------------------------------------------------
# _get_base64_image
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetBase64Image:

    def test_raises_for_no_path(self, llm):
        with pytest.raises(ValueError, match="No file path"):
            llm._get_base64_image({})

    def test_raises_for_file_not_found(self, llm):
        import contextlib

        @contextlib.contextmanager
        def bad_file(path):
            raise FileNotFoundError("not found")

        llm.storage = types.SimpleNamespace(get_file=bad_file)
        with pytest.raises(FileNotFoundError):
            llm._get_base64_image({"path": "/nonexistent"})

    def test_returns_base64_encoded(self, llm):
        import base64

        llm.storage = types.SimpleNamespace(get_file=lambda p: _ctx_manager(b"test_data"))
        assert base64.b64decode(llm._get_base64_image({"path": "/tmp/img.png"})) == b"test_data"
