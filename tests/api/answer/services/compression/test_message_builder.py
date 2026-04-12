"""Tests for application/api/answer/services/compression/message_builder.py"""


import pytest

from application.api.answer.services.compression.message_builder import MessageBuilder


@pytest.mark.unit
class TestBuildFromCompressedContext:
    def test_no_compression_returns_system_only(self):
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="You are helpful.",
            compressed_summary=None,
            recent_queries=[],
        )
        assert len(messages) == 1
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful."

    def test_with_recent_queries_no_compression(self):
        queries = [
            {"prompt": "Hello", "response": "Hi there!"},
            {"prompt": "How are you?", "response": "I'm fine."},
        ]
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System prompt",
            compressed_summary=None,
            recent_queries=queries,
        )
        # system + 2 * (user + assistant) = 5
        assert len(messages) == 5
        assert messages[1] == {"role": "user", "content": "Hello"}
        assert messages[2] == {"role": "assistant", "content": "Hi there!"}
        assert messages[3] == {"role": "user", "content": "How are you?"}
        assert messages[4] == {"role": "assistant", "content": "I'm fine."}

    def test_with_compressed_summary_appended_to_system(self):
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="You are helpful.",
            compressed_summary="Previous: user asked about Python.",
            recent_queries=[{"prompt": "More?", "response": "Sure."}],
        )
        system_content = messages[0]["content"]
        assert "This session is being continued" in system_content
        assert "Previous: user asked about Python." in system_content

    def test_mid_execution_context_type(self):
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System",
            compressed_summary="Summary here",
            recent_queries=[{"prompt": "q", "response": "r"}],
            context_type="mid_execution",
        )
        system_content = messages[0]["content"]
        assert "Context window limit reached" in system_content

    def test_include_tool_calls(self):
        queries = [
            {
                "prompt": "Search for X",
                "response": "Found X",
                "tool_calls": [
                    {
                        "call_id": "call-1",
                        "action_name": "search",
                        "arguments": {"q": "X"},
                        "result": "X found",
                    }
                ],
            }
        ]
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System",
            compressed_summary=None,
            recent_queries=queries,
            include_tool_calls=True,
        )
        # system + user + assistant + tool_call_assistant + tool_response = 5
        assert len(messages) == 5
        assert messages[3]["role"] == "assistant"
        assert messages[3].get("tool_calls") is not None
        assert messages[3]["tool_calls"][0]["function"]["name"] == "search"
        assert messages[4]["role"] == "tool"
        assert messages[4].get("tool_call_id") == "call-1"

    def test_tool_calls_not_included_by_default(self):
        queries = [
            {
                "prompt": "Search",
                "response": "Found",
                "tool_calls": [
                    {
                        "call_id": "c1",
                        "action_name": "search",
                        "arguments": {},
                        "result": "ok",
                    }
                ],
            }
        ]
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System",
            compressed_summary=None,
            recent_queries=queries,
            include_tool_calls=False,
        )
        # system + user + assistant = 3 (no tool messages)
        assert len(messages) == 3

    def test_tool_call_without_call_id_generates_uuid(self):
        queries = [
            {
                "prompt": "q",
                "response": "r",
                "tool_calls": [
                    {
                        "action_name": "act",
                        "arguments": {},
                        "result": "res",
                    }
                ],
            }
        ]
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="S",
            compressed_summary=None,
            recent_queries=queries,
            include_tool_calls=True,
        )
        assistant_msg = messages[3]
        call_id = assistant_msg["tool_calls"][0]["id"]
        assert call_id is not None
        assert len(call_id) > 0

    def test_continuation_message_when_no_recent_queries_but_has_summary(self):
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System",
            compressed_summary="Everything was compressed",
            recent_queries=[],
        )
        # system + continuation user message = 2
        assert len(messages) == 2
        assert messages[1]["role"] == "user"
        assert "continue" in messages[1]["content"].lower()

    def test_no_continuation_when_no_summary(self):
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="System",
            compressed_summary=None,
            recent_queries=[],
        )
        assert len(messages) == 1

    def test_queries_without_prompt_or_response_skipped(self):
        queries = [
            {"other_field": "value"},
            {"prompt": "real", "response": "answer"},
        ]
        messages = MessageBuilder.build_from_compressed_context(
            system_prompt="S",
            compressed_summary=None,
            recent_queries=queries,
        )
        # system + 1 valid query (user + assistant) = 3
        assert len(messages) == 3


@pytest.mark.unit
class TestAppendCompressionContext:
    def test_pre_request_context(self):
        result = MessageBuilder._append_compression_context(
            "Original prompt", "Summary text", "pre_request"
        )
        assert "This session is being continued" in result
        assert "Summary text" in result
        assert result.startswith("Original prompt")

    def test_mid_execution_context(self):
        result = MessageBuilder._append_compression_context(
            "Original prompt", "Summary text", "mid_execution"
        )
        assert "Context window limit reached" in result
        assert "Summary text" in result

    def test_removes_existing_compression_context(self):
        prompt_with_existing = (
            "Original prompt\n\n---\n\nThis session is being continued from old"
        )
        result = MessageBuilder._append_compression_context(
            prompt_with_existing, "New summary", "pre_request"
        )
        # Should not contain old context twice
        assert result.count("This session is being continued") == 1
        assert "New summary" in result

    def test_removes_mid_execution_context(self):
        prompt_with_existing = (
            "Original\n\n---\n\nContext window limit reached during execution. Old."
        )
        result = MessageBuilder._append_compression_context(
            prompt_with_existing, "New", "mid_execution"
        )
        assert result.count("Context window limit reached") == 1


@pytest.mark.unit
class TestRebuildMessagesAfterCompression:
    def test_basic_rebuild(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "old reply"},
        ]
        recent = [{"prompt": "new q", "response": "new r"}]

        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary="Everything was compressed.",
            recent_queries=recent,
        )
        assert result is not None
        # system + user + assistant = 3
        assert len(result) == 3
        assert "Context window limit reached" in result[0]["content"]
        assert result[1] == {"role": "user", "content": "new q"}
        assert result[2] == {"role": "assistant", "content": "new r"}

    def test_returns_none_without_system_message(self):
        messages = [
            {"role": "user", "content": "hello"},
        ]
        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary="summary",
            recent_queries=[],
        )
        assert result is None

    def test_no_summary_keeps_system_unchanged(self):
        messages = [{"role": "system", "content": "Be helpful."}]
        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary=None,
            recent_queries=[],
        )
        assert result is not None
        assert result[0]["content"] == "Be helpful."

    def test_include_tool_calls_in_rebuild(self):
        messages = [{"role": "system", "content": "S"}]
        recent = [
            {
                "prompt": "q",
                "response": "r",
                "tool_calls": [
                    {
                        "call_id": "c1",
                        "action_name": "act",
                        "arguments": {"a": 1},
                        "result": "done",
                    }
                ],
            }
        ]
        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary="s",
            recent_queries=recent,
            include_tool_calls=True,
        )
        # system + user + assistant + tool_call + tool_response = 5
        assert len(result) == 5

    def test_continuation_added_when_no_recent_queries(self):
        messages = [{"role": "system", "content": "S"}]
        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary="All compressed",
            recent_queries=[],
        )
        assert len(result) == 2
        assert result[1]["role"] == "user"
        assert "continue" in result[1]["content"].lower()

    def test_include_current_execution_preserves_extra_messages(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "r1"},
            {"role": "user", "content": "current execution msg"},
        ]
        recent = [{"prompt": "q1", "response": "r1"}]

        result = MessageBuilder.rebuild_messages_after_compression(
            messages=messages,
            compressed_summary="summary",
            recent_queries=recent,
            include_current_execution=True,
        )
        assert result is not None
        # Should include the current execution message
        contents = [m.get("content") for m in result]
        assert "current execution msg" in contents
