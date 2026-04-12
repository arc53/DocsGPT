"""Tests for the v1 API translator (Phase 4).

Covers request translation, response translation, streaming event
translation, continuation detection, and history conversion.
"""

import json

import pytest

from application.api.v1.translator import (
    _get_client_tool_name,
    convert_history,
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
        """Standard clients parse only 'choices' — docsgpt namespace is ignored."""
        chunks = translate_stream_event(
            {"type": "source", "source": [{"title": "t"}]},
            "chatcmpl-1", "agent",
        )
        parsed = json.loads(chunks[0].replace("data: ", "").strip())
        # No "choices" key — standard parsers skip this chunk entirely
        assert "choices" not in parsed
        # docsgpt key is present
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
