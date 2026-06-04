"""Tests for the v1 API translator.

Covers request translation, response translation, streaming event
translation, continuation detection, and history conversion.
"""

import json

import pytest

from application.api.v1.translator import (
    _get_client_tool_name,
    _split_leaked_reasoning,
    _strip_repr_quotes,
    content_to_text,
    convert_history,
    extract_response_schema,
    extract_system_prompt,
    extract_tool_results,
    is_continuation,
    translate_request,
    translate_response,
    translate_stream_event,
)


# ---------------------------------------------------------------------------
# is_continuation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsContinuation:

    def test_normal_messages_not_continuation(self):
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        assert is_continuation(messages) is False

    def test_tool_after_assistant_tool_calls_is_continuation(self):
        messages = [
            {"role": "user", "content": "What's the weather?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": '{"temp": "72F"}'},
        ]
        assert is_continuation(messages) is True

    def test_assistant_without_tool_calls_not_continuation(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
        ]
        # assistant has no tool_calls — not a valid continuation
        assert is_continuation(messages) is False

    def test_empty_messages(self):
        assert is_continuation([]) is False

    def test_multiple_tool_results(self):
        messages = [
            {"role": "user", "content": "Do stuff"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        assert is_continuation(messages) is True


# ---------------------------------------------------------------------------
# extract_tool_results
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractToolResults:

    def test_extracts_results(self):
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "content": '{"temp": "72F"}'},
        ]
        results = extract_tool_results(messages)
        assert len(results) == 1
        assert results[0]["call_id"] == "c1"
        assert results[0]["result"] == {"temp": "72F"}

    def test_string_content(self):
        messages = [
            {"role": "tool", "tool_call_id": "c1", "content": "plain text"},
        ]
        results = extract_tool_results(messages)
        assert results[0]["result"] == "plain text"

    def test_multiple_results(self):
        messages = [
            {"role": "assistant", "tool_calls": []},
            {"role": "tool", "tool_call_id": "c1", "content": "r1"},
            {"role": "tool", "tool_call_id": "c2", "content": "r2"},
        ]
        results = extract_tool_results(messages)
        assert len(results) == 2
        assert results[0]["call_id"] == "c1"
        assert results[1]["call_id"] == "c2"


# ---------------------------------------------------------------------------
# convert_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConvertHistory:

    def test_user_assistant_pairs(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good"},
            {"role": "user", "content": "What's 2+2?"},  # Last user = question
        ]
        history = convert_history(messages)
        assert len(history) == 2
        assert history[0]["prompt"] == "Hello"
        assert history[0]["response"] == "Hi there"
        assert history[1]["prompt"] == "How are you?"
        assert history[1]["response"] == "I'm good"

    def test_single_user_message(self):
        messages = [{"role": "user", "content": "Hi"}]
        history = convert_history(messages)
        assert history == []

    def test_system_messages_skipped(self):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Question"},
        ]
        history = convert_history(messages)
        assert history == []


# ---------------------------------------------------------------------------
# extract_system_prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSystemPrompt:

    def test_extracts_first_system_message(self):
        messages = [
            {"role": "system", "content": "You are a pirate"},
            {"role": "user", "content": "Hello"},
        ]
        assert extract_system_prompt(messages) == "You are a pirate"

    def test_returns_none_when_no_system_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        assert extract_system_prompt(messages) is None

    def test_returns_first_of_multiple_system_messages(self):
        messages = [
            {"role": "system", "content": "First"},
            {"role": "system", "content": "Second"},
            {"role": "user", "content": "Hello"},
        ]
        assert extract_system_prompt(messages) == "First"

    def test_empty_content_returns_empty_string(self):
        messages = [
            {"role": "system", "content": ""},
            {"role": "user", "content": "Hello"},
        ]
        assert extract_system_prompt(messages) == ""

    def test_missing_content_returns_empty_string(self):
        messages = [
            {"role": "system"},
            {"role": "user", "content": "Hello"},
        ]
        assert extract_system_prompt(messages) == ""


# ---------------------------------------------------------------------------
# translate_request
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslateRequest:

    def test_normal_request(self):
        data = {
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "What's 2+2?"},
            ],
        }
        result = translate_request(data, "test-key")
        assert result["question"] == "What's 2+2?"
        assert result["api_key"] == "test-key"
        # Conversations are not persisted by default on the v1 endpoint.
        assert result["save_conversation"] is False
        history = json.loads(result["history"])
        assert len(history) == 1
        assert history[0]["prompt"] == "Hello"

    def test_save_conversation_opt_in_via_docsgpt_extension(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "docsgpt": {"save_conversation": True},
        }
        result = translate_request(data, "key")
        assert result["save_conversation"] is True

    def test_save_conversation_default_false(self):
        data = {"messages": [{"role": "user", "content": "Hi"}]}
        result = translate_request(data, "key")
        assert result["save_conversation"] is False

    def test_continuation_request(self):
        data = {
            "messages": [
                {"role": "user", "content": "Search for X"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": '{"found": true}'},
            ],
        }
        result = translate_request(data, "key")
        assert "tool_actions" in result
        assert len(result["tool_actions"]) == 1
        assert result["tool_actions"][0]["call_id"] == "c1"

    def test_stateful_continuation_persists_by_default(self):
        """A stateful continuation (conversation_id present) implies the first
        turn was saved, so the resumed turn must persist too (otherwise the
        final answer + WAL row are lost)."""
        data = {
            "conversation_id": "conv-1",
            "messages": [
                {"role": "user", "content": "Search for X"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "done"},
            ],
        }
        result = translate_request(data, "key")
        assert result["save_conversation"] is True

    def test_stateless_continuation_does_not_persist_by_default(self):
        """A stateless continuation (no conversation_id, e.g. an OpenAI client
        such as opencode) never persisted turn 1, so it must NOT default to
        saving -- otherwise every tool round leaks an orphan conversation."""
        data = {
            "messages": [
                {"role": "user", "content": "Search for X"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "done"},
            ],
        }
        result = translate_request(data, "key")
        assert result["save_conversation"] is False

    def test_continuation_honours_explicit_save_conversation_override(self):
        """An explicit docsgpt.save_conversation=false on the continuation wins."""
        data = {
            "docsgpt": {"save_conversation": False},
            "messages": [
                {"role": "user", "content": "Search for X"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "done"},
            ],
        }
        result = translate_request(data, "key")
        assert result["save_conversation"] is False

    def test_continuation_with_top_level_conversation_id(self):
        """Standard clients send conversation_id at request level, not in messages."""
        data = {
            "conversation_id": "conv-top-level",
            "messages": [
                {"role": "user", "content": "Do stuff"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "act", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "done"},
            ],
        }
        result = translate_request(data, "key")
        assert result["conversation_id"] == "conv-top-level"

    def test_continuation_in_message_conversation_id_takes_precedence(self):
        """When both in-message and top-level conversation_id exist, in-message wins."""
        data = {
            "conversation_id": "conv-top-level",
            "messages": [
                {"role": "user", "content": "Do stuff"},
                {
                    "role": "assistant",
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "act", "arguments": "{}"}}],
                    "docsgpt": {"conversation_id": "conv-in-message"},
                },
                {"role": "tool", "tool_call_id": "c1", "content": "done"},
            ],
        }
        result = translate_request(data, "key")
        assert result["conversation_id"] == "conv-in-message"

    def test_client_tools_passed_through(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "tools": [{"type": "function", "function": {"name": "my_tool"}}],
        }
        result = translate_request(data, "key")
        assert result["client_tools"] == data["tools"]

    def test_docsgpt_attachments(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "docsgpt": {"attachments": ["att1", "att2"]},
        }
        result = translate_request(data, "key")
        assert result["attachments"] == ["att1", "att2"]

    def test_system_prompt_override_included_when_present(self):
        data = {
            "messages": [
                {"role": "system", "content": "Custom prompt"},
                {"role": "user", "content": "Hello"},
            ],
        }
        result = translate_request(data, "key")
        assert result["system_prompt_override"] == "Custom prompt"

    def test_system_prompt_override_absent_when_no_system_message(self):
        data = {
            "messages": [{"role": "user", "content": "Hello"}],
        }
        result = translate_request(data, "key")
        assert "system_prompt_override" not in result


# ---------------------------------------------------------------------------
# translate_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslateResponse:

    def test_basic_response(self):
        resp = translate_response(
            conversation_id="conv-1",
            answer="Hello!",
            sources=[],
            tool_calls=[],
            thought="",
            model_name="my-agent",
        )
        assert resp["id"] == "chatcmpl-conv-1"
        assert resp["object"] == "chat.completion"
        assert resp["model"] == "my-agent"
        assert resp["choices"][0]["message"]["content"] == "Hello!"
        assert resp["choices"][0]["finish_reason"] == "stop"
        assert "reasoning_content" not in resp["choices"][0]["message"]

    def test_response_with_thought(self):
        resp = translate_response(
            conversation_id="c1",
            answer="Result",
            sources=[],
            tool_calls=[],
            thought="Thinking about it...",
            model_name="agent",
        )
        assert resp["choices"][0]["message"]["reasoning_content"] == "Thinking about it..."

    def test_response_with_sources(self):
        sources = [{"title": "doc.txt", "text": "content", "source": "/doc.txt"}]
        resp = translate_response(
            conversation_id="c1",
            answer="Found it",
            sources=sources,
            tool_calls=[],
            thought="",
            model_name="agent",
        )
        assert resp["docsgpt"]["sources"] == sources

    def test_response_with_tool_calls(self):
        tool_calls = [{"tool_name": "notes", "call_id": "c1", "artifact_id": "a1"}]
        resp = translate_response(
            conversation_id="c1",
            answer="Done",
            sources=[],
            tool_calls=tool_calls,
            thought="",
            model_name="agent",
        )
        assert resp["docsgpt"]["tool_calls"] == tool_calls

    def test_pending_tool_calls_uses_tool_name(self):
        """Client tool responses use the original tool_name, not the LLM-visible action_name."""
        pending = [
            {
                "call_id": "c1",
                "tool_name": "get_weather",
                "action_name": "get_weather",
                "arguments": {"city": "SF"},
            }
        ]
        resp = translate_response(
            conversation_id="c1",
            answer="",
            sources=[],
            tool_calls=[],
            thought="",
            model_name="agent",
            pending_tool_calls=pending,
        )
        tc = resp["choices"][0]["message"]["tool_calls"][0]
        assert tc["function"]["name"] == "get_weather"

    def test_pending_tool_calls_tool_name_takes_precedence(self):
        """When tool_name differs from action_name, tool_name is used."""
        pending = [
            {
                "call_id": "c1",
                "tool_name": "search",
                "action_name": "search_1",
                "arguments": {"q": "test"},
            }
        ]
        resp = translate_response(
            conversation_id="c1",
            answer="",
            sources=[],
            tool_calls=[],
            thought="",
            model_name="agent",
            pending_tool_calls=pending,
        )
        tc = resp["choices"][0]["message"]["tool_calls"][0]
        assert tc["function"]["name"] == "search"

    def test_pending_tool_calls(self):
        pending = [
            {
                "call_id": "c1",
                "name": "get_weather",
                "arguments": {"city": "SF"},
            }
        ]
        resp = translate_response(
            conversation_id="c1",
            answer="",
            sources=[],
            tool_calls=[],
            thought="",
            model_name="agent",
            pending_tool_calls=pending,
        )
        assert resp["choices"][0]["finish_reason"] == "tool_calls"
        assert resp["choices"][0]["message"]["content"] is None
        assert len(resp["choices"][0]["message"]["tool_calls"]) == 1
        tc = resp["choices"][0]["message"]["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["function"]["name"] == "get_weather"

    def test_no_docsgpt_when_empty(self):
        resp = translate_response(
            conversation_id="",
            answer="Hi",
            sources=None,
            tool_calls=None,
            thought="",
            model_name="agent",
        )
        assert "docsgpt" not in resp


# ---------------------------------------------------------------------------
# translate_stream_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslateStreamEvent:

    def test_answer_event(self):
        chunks = translate_stream_event(
            {"type": "answer", "answer": "Hello"},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["choices"][0]["delta"]["content"] == "Hello"

    def test_thought_event(self):
        chunks = translate_stream_event(
            {"type": "thought", "thought": "reasoning"},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["choices"][0]["delta"]["reasoning_content"] == "reasoning"

    def test_source_event(self):
        chunks = translate_stream_event(
            {"type": "source", "source": [{"title": "t", "text": "x"}]},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["docsgpt"]["type"] == "source"
        assert len(parsed["docsgpt"]["sources"]) == 1

    def test_end_event(self):
        chunks = translate_stream_event(
            {"type": "end"},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 2
        # First chunk: finish_reason stop
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["choices"][0]["finish_reason"] == "stop"
        # Second chunk: [DONE]
        assert chunks[1].strip() == "data: [DONE]"

    def test_tool_call_client_execution(self):
        chunks = translate_stream_event(
            {
                "type": "tool_call",
                "data": {
                    "call_id": "c1",
                    "action_name": "get_weather",
                    "arguments": {"city": "SF"},
                    "status": "requires_client_execution",
                },
            },
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        tc = parsed["choices"][0]["delta"]["tool_calls"][0]
        assert tc["id"] == "c1"
        assert tc["function"]["name"] == "get_weather"

    def test_tool_call_client_execution_uses_tool_name(self):
        """Streaming tool calls use tool_name (original name) for client responses."""
        chunks = translate_stream_event(
            {
                "type": "tool_call",
                "data": {
                    "call_id": "c1",
                    "tool_name": "create",
                    "action_name": "create",
                    "arguments": {"title": "test"},
                    "status": "requires_client_execution",
                },
            },
            "chatcmpl-1", "agent",
        )
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        tc = parsed["choices"][0]["delta"]["tool_calls"][0]
        assert tc["function"]["name"] == "create"

    def test_tool_call_completed(self):
        chunks = translate_stream_event(
            {
                "type": "tool_call",
                "data": {
                    "call_id": "c1",
                    "status": "completed",
                    "result": "done",
                    "artifact_id": "a1",
                },
            },
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["docsgpt"]["type"] == "tool_call"
        assert parsed["docsgpt"]["data"]["artifact_id"] == "a1"

    def test_tool_calls_pending(self):
        chunks = translate_stream_event(
            {
                "type": "tool_calls_pending",
                "data": {"pending_tool_calls": [{"call_id": "c1"}]},
            },
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 2
        # Standard chunk with finish_reason tool_calls
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["choices"][0]["finish_reason"] == "tool_calls"
        # Extension chunk
        ext = json.loads(chunks[1].replace("data: ", "").strip())
        assert ext["docsgpt"]["type"] == "tool_calls_pending"

    def test_id_event(self):
        chunks = translate_stream_event(
            {"type": "id", "id": "conv-123"},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["docsgpt"]["conversation_id"] == "conv-123"

    def test_error_event(self):
        chunks = translate_stream_event(
            {"type": "error", "error": "Something went wrong"},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["error"]["message"] == "Something went wrong"

    def test_tool_calls_event_skipped(self):
        """The aggregate tool_calls event is redundant and should be skipped."""
        chunks = translate_stream_event(
            {"type": "tool_calls", "tool_calls": [{"call_id": "c1"}]},
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 0

    def test_research_events_skipped(self):
        assert translate_stream_event(
            {"type": "research_plan", "data": {}}, "id", "m"
        ) == []
        assert translate_stream_event(
            {"type": "research_progress", "data": {}}, "id", "m"
        ) == []

    def test_awaiting_approval_as_extension(self):
        chunks = translate_stream_event(
            {
                "type": "tool_call",
                "data": {"call_id": "c1", "status": "awaiting_approval"},
            },
            "chatcmpl-1", "agent",
        )
        assert len(chunks) == 1
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        assert parsed["docsgpt"]["type"] == "tool_call"

    def test_standard_clients_can_ignore_docsgpt(self):
        """The docsgpt namespace rides on a valid empty chat.completion.chunk.

        Standard OpenAI clients validate every streamed frame as a
        ``chat.completion.chunk``; a frame without ``choices`` is rejected.
        So docsgpt-only events (sources, ids, tool_calls) are emitted as a
        valid chunk with an empty delta plus a ``docsgpt`` extension that
        standard parsers simply ignore.
        """
        chunks = translate_stream_event(
            {"type": "source", "source": [{"title": "t"}]},
            "chatcmpl-1", "agent",
        )
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        # Valid chunk envelope: standard parsers read choices[0].delta (empty)
        assert isinstance(parsed.get("choices"), list)
        assert parsed["choices"][0]["delta"] == {}
        # docsgpt extension is present for clients that want it
        assert "docsgpt" in parsed


# ---------------------------------------------------------------------------
# _get_client_tool_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetClientToolName:

    def test_uses_tool_name_when_present(self):
        assert _get_client_tool_name({"tool_name": "create", "action_name": "create_1"}) == "create"

    def test_falls_back_to_action_name(self):
        assert _get_client_tool_name({"action_name": "get_weather"}) == "get_weather"

    def test_falls_back_to_name(self):
        assert _get_client_tool_name({"name": "search"}) == "search"

    def test_returns_empty_when_no_fields(self):
        assert _get_client_tool_name({}) == ""


# ---------------------------------------------------------------------------
# content_to_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContentToText:

    def test_plain_string_passthrough(self):
        assert content_to_text("hello") == "hello"

    def test_none_returns_empty(self):
        assert content_to_text(None) == ""

    def test_text_parts_joined(self):
        content = [
            {"type": "text", "text": "line one"},
            {"type": "text", "text": "line two"},
        ]
        assert content_to_text(content) == "line one\nline two"

    def test_image_parts_dropped(self):
        content = [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
        ]
        # Only the text part contributes; the image is dropped from the flattened text.
        assert content_to_text(content) == "describe this"

    def test_bare_string_parts_included(self):
        assert content_to_text(["a", "b"]) == "a\nb"

    def test_missing_text_field_becomes_empty(self):
        assert content_to_text([{"type": "text"}]) == ""

    def test_non_string_non_list_coerced(self):
        assert content_to_text(123) == "123"


# ---------------------------------------------------------------------------
# extract_response_schema
# ---------------------------------------------------------------------------


_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


@pytest.mark.unit
class TestExtractResponseSchema:

    def test_none_when_absent(self):
        assert extract_response_schema({}) is None

    def test_response_format_json_schema_wrapper(self):
        data = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ans", "schema": _SCHEMA},
            }
        }
        assert extract_response_schema(data) == _SCHEMA

    def test_response_format_bare_schema_under_json_schema(self):
        # A bare schema (no "schema" wrapper) but with a top-level "type" is tolerated.
        data = {
            "response_format": {
                "type": "json_schema",
                "json_schema": _SCHEMA,
            }
        }
        assert extract_response_schema(data) == _SCHEMA

    def test_response_format_json_object_carries_no_schema(self):
        data = {"response_format": {"type": "json_object"}}
        assert extract_response_schema(data) is None

    def test_response_schema_raw_object(self):
        assert extract_response_schema({"response_schema": _SCHEMA}) == _SCHEMA

    def test_response_schema_wrapper(self):
        data = {"response_schema": {"schema": _SCHEMA}}
        assert extract_response_schema(data) == _SCHEMA

    def test_response_schema_takes_precedence_over_response_format(self):
        other = {"type": "object", "properties": {}}
        data = {
            "response_schema": _SCHEMA,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"schema": other},
            },
        }
        assert extract_response_schema(data) == _SCHEMA


# ---------------------------------------------------------------------------
# _split_leaked_reasoning
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSplitLeakedReasoning:

    def test_no_marker_is_noop(self):
        assert _split_leaked_reasoning("just an answer") == ("just an answer", "")

    def test_none_is_noop(self):
        assert _split_leaked_reasoning(None) == (None, "")

    def test_extracts_single_thought(self):
        content = "{'type': 'thought', 'thought': 'let me think'}The answer is 42."
        clean, leaked = _split_leaked_reasoning(content)
        assert clean == "The answer is 42."
        assert leaked == "let me think"

    def test_extracts_multiple_thoughts(self):
        content = (
            "{'type': 'thought', 'thought': 'first'}"
            "partial"
            "{'type': 'thought', 'thought': 'second'}done"
        )
        clean, leaked = _split_leaked_reasoning(content)
        assert clean == "partialdone"
        assert leaked == "firstsecond"

    def test_double_quoted_thought_value(self):
        # When the token contains an apostrophe the repr uses double quotes.
        content = "{'type': 'thought', 'thought': \"I'll check\"}answer"
        clean, leaked = _split_leaked_reasoning(content)
        assert clean == "answer"
        assert leaked == "I'll check"

    def test_thought_value_with_brace_not_truncated(self):
        content = "{'type': 'thought', 'thought': 'use {json} here'}final"
        clean, leaked = _split_leaked_reasoning(content)
        assert clean == "final"
        assert leaked == "use {json} here"

    def test_strip_repr_quotes_unquoted_passthrough(self):
        # Defensive branch: an unquoted value is returned unchanged.
        assert _strip_repr_quotes("plain") == "plain"
        assert _strip_repr_quotes("'quoted'") == "quoted"


# ---------------------------------------------------------------------------
# translate_request — structured outputs / sampling / multimodal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTranslateRequestStructuredOutputs:

    def test_response_format_surfaces_json_schema_strict_default(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ans", "schema": _SCHEMA},
            },
        }
        result = translate_request(data, "key")
        assert result["json_schema"] == _SCHEMA
        assert result["json_schema_strict"] is True

    def test_response_format_honours_explicit_strict_false(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ans", "schema": _SCHEMA, "strict": False},
            },
        }
        result = translate_request(data, "key")
        assert result["json_schema_strict"] is False

    def test_json_object_mode_flag(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "response_format": {"type": "json_object"},
        }
        result = translate_request(data, "key")
        assert result["json_object"] is True
        assert "json_schema" not in result

    def test_sampling_params_forwarded(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.2,
            "top_p": 0.9,
            "seed": 7,
        }
        result = translate_request(data, "key")
        assert result["llm_params"] == {"temperature": 0.2, "top_p": 0.9, "seed": 7}

    def test_max_tokens_alias_dropped_when_canonical_present(self):
        data = {
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 100,
            "max_completion_tokens": 200,
        }
        result = translate_request(data, "key")
        assert result["llm_params"]["max_completion_tokens"] == 200
        assert "max_tokens" not in result["llm_params"]

    def test_multimodal_content_preserved_and_question_flattened(self):
        content = [
            {"type": "text", "text": "what is this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
        ]
        data = {"messages": [{"role": "user", "content": content}]}
        result = translate_request(data, "key")
        assert result["question"] == "what is this"
        assert result["multimodal_content"] == content

    def test_plain_text_request_has_no_multimodal_content(self):
        data = {"messages": [{"role": "user", "content": "plain"}]}
        result = translate_request(data, "key")
        assert "multimodal_content" not in result

    def test_continuation_forwards_schema_and_sampling(self):
        data = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ans", "schema": _SCHEMA},
            },
            "temperature": 0.5,
        }
        result = translate_request(data, "key")
        assert result["tool_actions"]
        assert result["json_schema"] == _SCHEMA
        assert result["json_schema_strict"] is True
        assert result["llm_params"] == {"temperature": 0.5}

    def test_continuation_forwards_tools_and_json_object(self):
        data = {
            "messages": [
                {"role": "user", "content": "Hi"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "result"},
            ],
            "tools": [{"type": "function", "function": {"name": "search"}}],
            "response_format": {"type": "json_object"},
        }
        result = translate_request(data, "key")
        assert result["client_tools"] == data["tools"]
        assert result["json_object"] is True


# ---------------------------------------------------------------------------
# translate_response / translate_stream_event — reasoning-leak handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReasoningLeakHandling:

    def test_response_strips_leak_only_when_enabled(self):
        answer = "{'type': 'thought', 'thought': 'hmm'}Final answer."
        result = translate_response(
            conversation_id="",
            answer=answer,
            sources=None,
            tool_calls=None,
            thought="",
            model_name="agent",
            strip_reasoning_leak=True,
        )
        msg = result["choices"][0]["message"]
        assert msg["content"] == "Final answer."
        assert msg["reasoning_content"] == "hmm"

    def test_response_preserves_content_when_strip_disabled(self):
        answer = "{'type': 'thought', 'thought': 'hmm'}Final answer."
        result = translate_response(
            conversation_id="",
            answer=answer,
            sources=None,
            tool_calls=None,
            thought="",
            model_name="agent",
            strip_reasoning_leak=False,
        )
        msg = result["choices"][0]["message"]
        # Untouched: the leak marker is left in content verbatim.
        assert msg["content"] == answer
        assert "reasoning_content" not in msg

    def test_response_combines_thought_and_leaked_reasoning(self):
        answer = "{'type': 'thought', 'thought': 'leaked'}Answer."
        result = translate_response(
            conversation_id="",
            answer=answer,
            sources=None,
            tool_calls=None,
            thought="explicit ",
            model_name="agent",
            strip_reasoning_leak=True,
        )
        msg = result["choices"][0]["message"]
        assert msg["reasoning_content"] == "explicit leaked"

    def test_stream_answer_splits_leak_when_enabled(self):
        chunks = translate_stream_event(
            {"type": "answer", "answer": "{'type': 'thought', 'thought': 'r'}hi"},
            "chatcmpl-1", "agent", True,
        )
        deltas = [
            json.loads(c.replace("data: ", "").strip())["choices"][0]["delta"]
            for c in chunks
        ]
        assert {"reasoning_content": "r"} in deltas
        assert {"content": "hi"} in deltas

    def test_stream_answer_preserves_content_when_disabled(self):
        raw = "{'type': 'thought', 'thought': 'r'}hi"
        chunks = translate_stream_event(
            {"type": "answer", "answer": raw}, "chatcmpl-1", "agent", False,
        )
        deltas = [
            json.loads(c.replace("data: ", "").strip())["choices"][0]["delta"]
            for c in chunks
        ]
        assert {"content": raw} in deltas
        assert all("reasoning_content" not in d for d in deltas)

    def test_stream_structured_answer_event(self):
        chunks = translate_stream_event(
            {"type": "structured_answer", "answer": '{"answer": "42"}'},
            "chatcmpl-1", "agent", True,
        )
        deltas = [
            json.loads(c.replace("data: ", "").strip())["choices"][0]["delta"]
            for c in chunks
        ]
        assert {"content": '{"answer": "42"}'} in deltas

    def test_stream_structured_answer_splits_leak(self):
        chunks = translate_stream_event(
            {
                "type": "structured_answer",
                "answer": "{'type': 'thought', 'thought': 'why'}{\"answer\": \"42\"}",
            },
            "chatcmpl-1", "agent", True,
        )
        deltas = [
            json.loads(c.replace("data: ", "").strip())["choices"][0]["delta"]
            for c in chunks
        ]
        assert {"reasoning_content": "why"} in deltas
        assert {"content": '{"answer": "42"}'} in deltas
