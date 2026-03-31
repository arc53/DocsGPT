from typing import Any, Dict, Generator
from unittest.mock import Mock, MagicMock, patch

import pytest

from application.llm.handlers.base import LLMHandler, LLMResponse, ToolCall


class TestToolCall:
    def test_tool_call_creation(self):
        tool_call = ToolCall(
            id="test_id", name="test_function", arguments={"arg1": "value1"}, index=0
        )
        assert tool_call.id == "test_id"
        assert tool_call.name == "test_function"
        assert tool_call.arguments == {"arg1": "value1"}
        assert tool_call.index == 0

    def test_tool_call_from_dict(self):
        data = {
            "id": "call_123",
            "name": "get_weather",
            "arguments": {"location": "New York"},
            "index": 1,
        }
        tool_call = ToolCall.from_dict(data)
        assert tool_call.id == "call_123"
        assert tool_call.name == "get_weather"
        assert tool_call.arguments == {"location": "New York"}
        assert tool_call.index == 1

    def test_tool_call_from_dict_missing_fields(self):
        data = {"name": "test_func"}
        tool_call = ToolCall.from_dict(data)
        assert tool_call.id == ""
        assert tool_call.name == "test_func"
        assert tool_call.arguments == {}
        assert tool_call.index is None

    def test_tool_call_thought_signature(self):
        tc = ToolCall(
            id="1", name="fn", arguments={}, thought_signature="sig123"
        )
        assert tc.thought_signature == "sig123"

    def test_tool_call_thought_signature_default_none(self):
        tc = ToolCall(id="1", name="fn", arguments={})
        assert tc.thought_signature is None


class TestLLMResponse:
    def test_llm_response_creation(self):
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="Hello",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
            raw_response={"test": "data"},
        )
        assert response.content == "Hello"
        assert len(response.tool_calls) == 1
        assert response.finish_reason == "tool_calls"
        assert response.raw_response == {"test": "data"}

    def test_requires_tool_call_true(self):
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="",
            tool_calls=tool_calls,
            finish_reason="tool_calls",
            raw_response={},
        )
        assert response.requires_tool_call is True

    def test_requires_tool_call_false_no_tools(self):
        response = LLMResponse(
            content="Hello", tool_calls=[], finish_reason="stop", raw_response={}
        )
        assert response.requires_tool_call is False

    def test_requires_tool_call_false_wrong_finish_reason(self):
        tool_calls = [ToolCall(id="1", name="func", arguments={})]
        response = LLMResponse(
            content="Hello",
            tool_calls=tool_calls,
            finish_reason="stop",
            raw_response={},
        )
        assert response.requires_tool_call is False


class ConcreteHandler(LLMHandler):
    def parse_response(self, response: Any) -> LLMResponse:
        return LLMResponse(
            content=str(response),
            tool_calls=[],
            finish_reason="stop",
            raw_response=response,
        )

    def create_tool_message(self, tool_call: ToolCall, result: Any) -> Dict:
        return {"role": "tool", "content": str(result), "tool_call_id": tool_call.id}

    def _iterate_stream(self, response: Any) -> Generator:
        for chunk in response:
            yield chunk


class TestLLMHandler:
    def test_handler_initialization(self):
        handler = ConcreteHandler()
        assert handler.llm_calls == []
        assert handler.tool_calls == []

    def test_prepare_messages_no_attachments(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]

        mock_agent = Mock()
        result = handler.prepare_messages(mock_agent, messages, None)
        assert result == messages

    def test_prepare_messages_with_supported_attachments(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [{"mime_type": "image/png", "path": "/test.png"}]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages

        result = handler.prepare_messages(mock_agent, messages, attachments)
        mock_agent.llm.prepare_messages_with_attachments.assert_called_once_with(
            messages, attachments
        )
        assert result == messages

    @patch("application.llm.handlers.base.logger")
    def test_prepare_messages_with_unsupported_attachments(self, mock_logger):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [{"mime_type": "text/plain", "path": "/test.txt"}]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]

        with patch.object(
            handler, "_append_unsupported_attachments", return_value=messages
        ) as mock_append:
            result = handler.prepare_messages(mock_agent, messages, attachments)
            mock_append.assert_called_once_with(messages, attachments)
            assert result == messages

    def test_prepare_messages_mixed_attachments(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "Hello"}]
        attachments = [
            {"mime_type": "image/png", "path": "/test.png"},
            {"mime_type": "text/plain", "path": "/test.txt"},
        ]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages

        with patch.object(
            handler, "_append_unsupported_attachments", return_value=messages
        ) as mock_append:
            result = handler.prepare_messages(mock_agent, messages, attachments)

            mock_agent.llm.prepare_messages_with_attachments.assert_called_once()
            mock_append.assert_called_once()
            assert result == messages

    def test_process_message_flow_non_streaming(self):
        handler = ConcreteHandler()
        mock_agent = Mock()
        initial_response = "test response"
        tools_dict = {}
        messages = [{"role": "user", "content": "Hello"}]

        with patch.object(
            handler, "prepare_messages", return_value=messages
        ) as mock_prepare:
            with patch.object(
                handler, "handle_non_streaming", return_value="final"
            ) as mock_handle:
                result = handler.process_message_flow(
                    mock_agent, initial_response, tools_dict, messages, stream=False
                )

                mock_prepare.assert_called_once_with(mock_agent, messages, None)
                mock_handle.assert_called_once_with(
                    mock_agent, initial_response, tools_dict, messages
                )
                assert result == "final"

    def test_process_message_flow_streaming(self):
        handler = ConcreteHandler()
        mock_agent = Mock()
        initial_response = "test response"
        tools_dict = {}
        messages = [{"role": "user", "content": "Hello"}]

        def mock_generator():
            yield "chunk1"
            yield "chunk2"

        with patch.object(
            handler, "prepare_messages", return_value=messages
        ) as mock_prepare:
            with patch.object(
                handler, "handle_streaming", return_value=mock_generator()
            ) as mock_handle:
                result = handler.process_message_flow(
                    mock_agent, initial_response, tools_dict, messages, stream=True
                )

                mock_prepare.assert_called_once_with(mock_agent, messages, None)
                mock_handle.assert_called_once_with(
                    mock_agent, initial_response, tools_dict, messages
                )

                chunks = list(result)
                assert chunks == ["chunk1", "chunk2"]


# ---------------------------------------------------------------------------
# _append_unsupported_attachments
# ---------------------------------------------------------------------------


class TestAppendUnsupportedAttachments:

    def test_with_content(self):
        handler = ConcreteHandler()
        messages = [{"role": "system", "content": "You are helpful."}]
        attachments = [{"id": "a1", "content": "File contents here"}]

        result = handler._append_unsupported_attachments(messages, attachments)
        assert "File contents here" in result[0]["content"]

    def test_without_content(self):
        handler = ConcreteHandler()
        messages = [{"role": "system", "content": "sys"}]
        attachments = [{"id": "a1", "mime_type": "text/plain"}]

        result = handler._append_unsupported_attachments(messages, attachments)
        # No content key → no change to system prompt
        assert result[0]["content"] == "sys"

    def test_no_system_message_creates_one(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "hello"}]
        attachments = [{"id": "a1", "content": "data"}]

        result = handler._append_unsupported_attachments(messages, attachments)
        system_msgs = [m for m in result if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert "data" in system_msgs[0]["content"]

    def test_multiple_attachments(self):
        handler = ConcreteHandler()
        messages = [{"role": "system", "content": "base"}]
        attachments = [
            {"id": "a1", "content": "content1"},
            {"id": "a2", "content": "content2"},
        ]

        result = handler._append_unsupported_attachments(messages, attachments)
        assert "content1" in result[0]["content"]
        assert "content2" in result[0]["content"]

    def test_original_messages_not_mutated(self):
        handler = ConcreteHandler()
        original = [{"role": "system", "content": "sys"}]
        handler._append_unsupported_attachments(
            original, [{"id": "a", "content": "x"}]
        )
        # The shallow copy means the dict inside IS mutated, but the list is not
        assert len(original) == 1


# ---------------------------------------------------------------------------
# _prune_messages_minimal
# ---------------------------------------------------------------------------


class TestPruneMessagesMinimal:

    def test_normal_case(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ]
        result = handler._prune_messages_minimal(messages)
        assert result is not None
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"
        assert result[1]["content"] == "second question"

    def test_no_system_message(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "hi"}]
        result = handler._prune_messages_minimal(messages)
        assert result is None

    def test_no_user_message(self):
        handler = ConcreteHandler()
        messages = [{"role": "system", "content": "sys"}]
        result = handler._prune_messages_minimal(messages)
        assert result is None

    def test_falls_back_to_non_user_role(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "response"},
        ]
        result = handler._prune_messages_minimal(messages)
        assert result is not None
        assert result[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# _extract_text_from_content
# ---------------------------------------------------------------------------


class TestExtractTextFromContent:

    def test_string(self):
        handler = ConcreteHandler()
        assert handler._extract_text_from_content("hello") == "hello"

    def test_list_with_text(self):
        handler = ConcreteHandler()
        content = [{"text": "part1"}, {"text": "part2"}]
        result = handler._extract_text_from_content(content)
        assert "part1" in result
        assert "part2" in result

    def test_list_with_function_call(self):
        handler = ConcreteHandler()
        content = [{"function_call": {"name": "search", "args": {}}}]
        result = handler._extract_text_from_content(content)
        assert "function_call" in result

    def test_list_with_function_response(self):
        handler = ConcreteHandler()
        content = [{"function_response": {"name": "search", "response": "ok"}}]
        result = handler._extract_text_from_content(content)
        assert "function_response" in result

    def test_list_with_files(self):
        handler = ConcreteHandler()
        content = [{"files": ["/tmp/a.txt"]}]
        result = handler._extract_text_from_content(content)
        assert "files" in result

    def test_list_with_none_text(self):
        handler = ConcreteHandler()
        content = [{"text": None}]
        result = handler._extract_text_from_content(content)
        assert result == ""

    def test_empty_list(self):
        handler = ConcreteHandler()
        assert handler._extract_text_from_content([]) == ""

    def test_none_returns_empty(self):
        handler = ConcreteHandler()
        assert handler._extract_text_from_content(None) == ""

    def test_integer_returns_empty(self):
        handler = ConcreteHandler()
        assert handler._extract_text_from_content(42) == ""


# ---------------------------------------------------------------------------
# _build_conversation_from_messages
# ---------------------------------------------------------------------------


class TestBuildConversationFromMessages:

    def test_basic_conversation(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        assert len(result["queries"]) == 1
        assert result["queries"][0]["prompt"] == "hello"
        assert result["queries"][0]["response"] == "hi there"

    def test_with_tool_calls(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "search for X"},
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "name": "search",
                            "args": {"q": "X"},
                            "call_id": "c1",
                        }
                    }
                ],
            },
            {
                "role": "tool",
                "content": [
                    {
                        "function_response": {
                            "name": "search",
                            "response": {"result": "found"},
                            "call_id": "c1",
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "I found X"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        queries = result["queries"]
        assert len(queries) == 1
        assert queries[0]["prompt"] == "search for X"
        assert queries[0]["response"] == "I found X"

    def test_empty_messages(self):
        handler = ConcreteHandler()
        result = handler._build_conversation_from_messages([])
        assert result is None

    def test_system_only(self):
        handler = ConcreteHandler()
        result = handler._build_conversation_from_messages(
            [{"role": "system", "content": "sys"}]
        )
        assert result is None

    def test_unfinished_prompt_committed(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "question"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        assert result["queries"][0]["prompt"] == "question"
        assert result["queries"][0]["response"] == ""

    def test_tool_response_without_matching_call(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "tool", "content": "tool output"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        # Tool output appended to last query
        assert len(result["queries"]) >= 1

    def test_compression_metadata_present(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert "compression_metadata" in result
        assert result["compression_metadata"]["is_compressed"] is False

    def test_model_role_treated_as_assistant(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "model", "content": "hi from model"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        assert result["queries"][0]["response"] == "hi from model"


# ---------------------------------------------------------------------------
# _rebuild_messages_after_compression
# ---------------------------------------------------------------------------


class TestRebuildMessagesAfterCompression:

    def test_delegates_to_message_builder(self):
        handler = ConcreteHandler()
        messages = [{"role": "system", "content": "sys"}]

        with patch(
            "application.api.answer.services.compression.message_builder.MessageBuilder.rebuild_messages_after_compression",
            return_value=[{"role": "system", "content": "rebuilt"}],
        ) as mock_rebuild:
            result = handler._rebuild_messages_after_compression(
                messages, "summary", [{"prompt": "q", "response": "a"}]
            )
            mock_rebuild.assert_called_once()
            assert result == [{"role": "system", "content": "rebuilt"}]


# ---------------------------------------------------------------------------
# _convert_pdf_to_images
# ---------------------------------------------------------------------------


class TestConvertPdfToImages:

    def test_no_path_raises(self):
        handler = ConcreteHandler()
        with pytest.raises(ValueError, match="No file path"):
            handler._convert_pdf_to_images({"mime_type": "application/pdf"})

    def test_delegates_to_utils(self):
        handler = ConcreteHandler()
        mock_storage = Mock()
        expected = [{"data": "img1", "mime_type": "image/png", "page": 1}]

        with patch(
            "application.storage.storage_creator.StorageCreator.get_storage",
            return_value=mock_storage,
        ), patch(
            "application.utils.convert_pdf_to_images",
            return_value=expected,
        ) as mock_convert:
            result = handler._convert_pdf_to_images(
                {"path": "/tmp/doc.pdf", "mime_type": "application/pdf"}
            )
            mock_convert.assert_called_once_with(
                file_path="/tmp/doc.pdf",
                storage=mock_storage,
                max_pages=20,
                dpi=150,
            )
            assert result == expected


# ---------------------------------------------------------------------------
# prepare_messages — synthetic PDF support
# ---------------------------------------------------------------------------


class TestPrepareMessagesSyntheticPDF:

    def test_pdf_converted_when_images_supported_not_pdf(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "analyse"}]
        attachments = [{"mime_type": "application/pdf", "path": "/tmp/doc.pdf"}]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages

        converted = [{"data": "b64", "mime_type": "image/png", "page": 1}]
        with patch.object(handler, "_convert_pdf_to_images", return_value=converted):
            handler.prepare_messages(mock_agent, messages, attachments)
            mock_agent.llm.prepare_messages_with_attachments.assert_called_once_with(
                messages, converted
            )

    def test_pdf_conversion_failure_falls_back(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "analyse"}]
        attachments = [{"mime_type": "application/pdf", "path": "/tmp/doc.pdf"}]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = ["image/png"]

        with patch.object(
            handler,
            "_convert_pdf_to_images",
            side_effect=RuntimeError("conversion failed"),
        ), patch.object(
            handler, "_append_unsupported_attachments", return_value=messages
        ) as mock_append:
            handler.prepare_messages(mock_agent, messages, attachments)
            mock_append.assert_called_once()

    def test_pdf_not_converted_when_natively_supported(self):
        handler = ConcreteHandler()
        messages = [{"role": "user", "content": "analyse"}]
        attachments = [{"mime_type": "application/pdf", "path": "/tmp/doc.pdf"}]

        mock_agent = Mock()
        mock_agent.llm.get_supported_attachment_types.return_value = [
            "image/png",
            "application/pdf",
        ]
        mock_agent.llm.prepare_messages_with_attachments.return_value = messages

        with patch.object(handler, "_convert_pdf_to_images") as mock_convert:
            handler.prepare_messages(mock_agent, messages, attachments)
            mock_convert.assert_not_called()


# ---------------------------------------------------------------------------
# handle_tool_calls
# ---------------------------------------------------------------------------


class TestHandleToolCalls:

    def _make_agent(self):
        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)
        return agent

    def test_single_tool_call(self):
        handler = ConcreteHandler()
        agent = self._make_agent()
        call = ToolCall(id="c1", name="action_1", arguments="{}")
        tools_dict = {"1": {"name": "tool"}}

        gen = handler.handle_tool_calls(agent, [call], tools_dict, [])
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            messages, _pending = e.value

        assert any(e.get("type") == "tool_call" for e in events)
        assert len(messages) >= 2  # function_call + tool_message

    def test_context_limit_skips_remaining(self):
        handler = ConcreteHandler()
        agent = self._make_agent()
        agent._check_context_limit = Mock(return_value=True)

        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = False

            calls = [
                ToolCall(id="c1", name="a_1", arguments="{}"),
                ToolCall(id="c2", name="b_1", arguments="{}"),
            ]
            gen = handler.handle_tool_calls(agent, calls, {}, [])
            events = list(gen)

        skip_events = [
            e for e in events
            if isinstance(e, dict)
            and e.get("type") == "tool_call"
            and e.get("data", {}).get("status") == "skipped"
        ]
        assert len(skip_events) == 2
        assert agent.context_limit_reached is True

    def test_tool_execution_error(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)
        agent._execute_tool_action = Mock(side_effect=RuntimeError("exec error"))

        call = ToolCall(id="c1", name="action_1", arguments="{}")
        gen = handler.handle_tool_calls(agent, [call], {"1": {"name": "t"}}, [])
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration:
            pass

        error_events = [
            e for e in events
            if isinstance(e, dict) and e.get("data", {}).get("status") == "error"
        ]
        assert len(error_events) == 1

    def test_thought_signature_preserved(self):
        handler = ConcreteHandler()
        agent = self._make_agent()
        call = ToolCall(
            id="c1", name="action_1", arguments="{}", thought_signature="sig"
        )

        gen = handler.handle_tool_calls(agent, [call], {"1": {"name": "t"}}, [])
        try:
            while True:
                next(gen)
        except StopIteration as e:
            messages, _pending = e.value

        # Standard format: thought_signature is on tool_calls items
        assistant_msgs = [
            m for m in messages
            if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        assert any(
            tc.get("thought_signature") == "sig"
            for m in assistant_msgs
            for tc in m["tool_calls"]
        )


# ---------------------------------------------------------------------------
# handle_non_streaming
# ---------------------------------------------------------------------------


class TestHandleNonStreaming:

    def test_no_tool_calls(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()
        response = "simple answer"

        gen = handler.handle_non_streaming(agent, response, {}, [])
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            final = e.value

        assert final == "simple answer"

    def test_with_tool_calls_loop(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()
        agent.model_id = "test"
        agent.tools = []
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        # First response requires tool call, second is final
        call_count = {"n": 0}

        def fake_parse(response):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="c1", name="fn_1", arguments="{}")],
                    finish_reason="tool_calls",
                    raw_response=response,
                )
            return LLMResponse(
                content="final",
                tool_calls=[],
                finish_reason="stop",
                raw_response=response,
            )

        handler.parse_response = fake_parse

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)
        agent.llm.gen = Mock(return_value="second_response")

        gen = handler.handle_non_streaming(agent, "first_response", {"1": {"name": "t"}}, [])
        events = []
        try:
            while True:
                events.append(next(gen))
        except StopIteration as e:
            final = e.value

        assert final == "final"
        assert agent.llm.gen.called


# ---------------------------------------------------------------------------
# handle_streaming
# ---------------------------------------------------------------------------


class TestHandleStreaming:

    def test_text_chunks(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()

        # Stream yields parsed responses with content
        chunks = [
            LLMResponse(content="hello ", tool_calls=[], finish_reason="", raw_response={}),
            LLMResponse(content="world", tool_calls=[], finish_reason="stop", raw_response={}),
        ]
        handler.parse_response = lambda c: c

        def fake_iterate(response):
            yield from response

        handler._iterate_stream = fake_iterate

        gen = handler.handle_streaming(agent, chunks, {}, [])
        results = list(gen)
        assert "hello " in results
        assert "world" in results

    def test_thought_chunks_passed_through(self):
        handler = ConcreteHandler()
        agent = Mock()

        def fake_iterate(response):
            yield {"type": "thought", "content": "thinking..."}

        handler._iterate_stream = fake_iterate

        gen = handler.handle_streaming(agent, "response", {}, [])
        results = list(gen)
        assert results[0] == {"type": "thought", "content": "thinking..."}

    def test_string_chunks_passed_through(self):
        handler = ConcreteHandler()
        agent = Mock()

        def fake_iterate(response):
            yield "raw string"

        handler._iterate_stream = fake_iterate

        gen = handler.handle_streaming(agent, "response", {}, [])
        results = list(gen)
        assert results[0] == "raw string"

    def test_tool_calls_accumulated_across_chunks(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()
        agent.model_id = "test"
        agent.tools = []
        agent._check_context_limit = Mock(return_value=False)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        # First chunk has partial tool call, second completes it
        chunk1 = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="search", arguments='{"q":', index=0)],
            finish_reason="",
            raw_response={},
        )
        chunk2 = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="", name="", arguments='"test"}', index=0)],
            finish_reason="tool_calls",
            raw_response={},
        )

        handler.parse_response = lambda c: c

        def fake_iterate(response):
            yield from response

        handler._iterate_stream = fake_iterate

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)

        # After tool calls, return final streaming response
        final_chunk = LLMResponse(
            content="done", tool_calls=[], finish_reason="stop", raw_response={}
        )
        agent.llm.gen_stream = Mock(return_value=[final_chunk])

        gen = handler.handle_streaming(agent, [chunk1, chunk2], {"1": {"name": "t"}}, [])
        list(gen)

        # The accumulated arguments should be concatenated
        tool_call_args = agent._execute_tool_action.call_args
        executed_call = tool_call_args[0][1]
        assert executed_call.arguments == '{"q":"test"}'

    def test_context_limit_adds_system_message(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.llm = Mock()
        agent.model_id = "test"
        agent.tools = [{"type": "function"}]
        agent.context_limit_reached = True
        agent._check_context_limit = Mock(return_value=True)
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        # Chunk finishes with tool_calls
        chunk = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="fn_1", arguments="{}", index=0)],
            finish_reason="tool_calls",
            raw_response={},
        )
        handler.parse_response = lambda c: c

        def fake_iterate(response):
            yield from response

        handler._iterate_stream = fake_iterate

        with patch("application.core.settings.settings") as mock_settings:
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = False

            # handle_tool_calls yields skip events and sets context_limit_reached
            def fake_handle_tool_calls(agent, calls, tools_dict, messages):
                agent.context_limit_reached = True
                yield {"type": "tool_call", "data": {"status": "skipped"}}
                return messages, None

            handler.handle_tool_calls = fake_handle_tool_calls

            final_chunk = LLMResponse(
                content="wrapping up", tool_calls=[], finish_reason="stop", raw_response={}
            )
            agent.llm.gen_stream = Mock(return_value=[final_chunk])

            gen = handler.handle_streaming(agent, [chunk], {"1": {"name": "t"}}, [])
            list(gen)

        # Should have called gen_stream with tools=None (context limit)
        gen_stream_kwargs = agent.llm.gen_stream.call_args[1]
        assert gen_stream_kwargs.get("tools") is None


# ---------------------------------------------------------------------------
# _perform_mid_execution_compression
# ---------------------------------------------------------------------------


class TestPerformMidExecutionCompression:

    def test_success_path(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_metadata = Mock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 1000
        mock_metadata.compression_ratio = 10.0
        mock_metadata.to_dict.return_value = {"ratio": 10.0}

        mock_result = Mock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "summary"
        mock_result.recent_queries = []
        mock_result.metadata = mock_metadata
        mock_result.error = None

        mock_conversation = {"queries": []}
        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = mock_conversation

        mock_orchestrator = Mock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=mock_orchestrator,
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler, "_build_conversation_from_messages", return_value={"queries": []}
        ), patch.object(
            handler,
            "_rebuild_messages_after_compression",
            return_value=[{"role": "system", "content": "rebuilt"}],
        ):
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is True
        assert messages is not None
        assert agent.compressed_summary == "summary"

    def test_failure_falls_back_to_pruning(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_result = Mock()
        mock_result.success = False
        mock_result.error = "failed"

        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = {"queries": []}

        mock_orchestrator = Mock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=mock_orchestrator,
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler, "_build_conversation_from_messages", return_value={"queries": []}
        ), patch.object(
            handler,
            "_prune_messages_minimal",
            return_value=[{"role": "system", "content": "pruned"}],
        ):
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
            )

        assert success is True
        assert messages is not None

    def test_exception_returns_false(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            side_effect=RuntimeError("import error"),
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=Mock(),
        ):
            success, messages = handler._perform_mid_execution_compression(agent, [])

        assert success is False
        assert messages is None


# ---------------------------------------------------------------------------
# _perform_in_memory_compression
# ---------------------------------------------------------------------------


class TestPerformInMemoryCompression:

    def test_no_conversation_returns_false(self):
        handler = ConcreteHandler()
        agent = Mock()

        with patch.object(
            handler, "_build_conversation_from_messages", return_value=None
        ):
            success, messages = handler._perform_in_memory_compression(agent, [])

        assert success is False
        assert messages is None

    def test_compression_doesnt_reduce_falls_back_to_prune(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.model_id = "gpt-4"
        agent.user_api_key = None
        agent.decoded_token = {}
        agent.agent_id = None
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_metadata = Mock()
        mock_metadata.compressed_token_count = 1000
        mock_metadata.original_token_count = 900  # worse!

        mock_service = Mock()
        mock_service.compress_conversation.return_value = mock_metadata

        with patch.object(
            handler,
            "_build_conversation_from_messages",
            return_value={"queries": [{"prompt": "q", "response": "a"}]},
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=Mock(),
        ), patch(
            "application.api.answer.services.compression.service.CompressionService",
            return_value=mock_service,
        ), patch.object(
            handler,
            "_prune_messages_minimal",
            return_value=[{"role": "system", "content": "pruned"}],
        ), patch(
            "application.core.settings.settings",
            MagicMock(COMPRESSION_MODEL_OVERRIDE=None),
        ):
            success, messages = handler._perform_in_memory_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is True

    def test_exception_returns_false(self):
        handler = ConcreteHandler()
        agent = Mock()

        with patch.object(
            handler,
            "_build_conversation_from_messages",
            side_effect=RuntimeError("boom"),
        ):
            success, messages = handler._perform_in_memory_compression(agent, [])

        assert success is False
        assert messages is None

    def test_not_enough_queries(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.model_id = "gpt-4"
        agent.user_api_key = None
        agent.decoded_token = {}
        agent.agent_id = None

        with patch.object(
            handler,
            "_build_conversation_from_messages",
            return_value={"queries": []},
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=Mock(),
        ), patch(
            "application.api.answer.services.compression.service.CompressionService",
            return_value=Mock(),
        ), patch(
            "application.core.settings.settings",
            MagicMock(COMPRESSION_MODEL_OVERRIDE=None),
        ):
            success, messages = handler._perform_in_memory_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is False
        assert messages is None

    def test_success_path(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.model_id = "gpt-4"
        agent.user_api_key = None
        agent.decoded_token = {}
        agent.agent_id = None
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_metadata = Mock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 1000
        mock_metadata.compression_ratio = 10.0
        mock_metadata.to_dict.return_value = {"ratio": 10.0}

        mock_service = Mock()
        mock_service.compress_conversation.return_value = mock_metadata
        mock_service.get_compressed_context.return_value = ("summary", [{"prompt": "q", "response": "a"}])

        with patch.object(
            handler,
            "_build_conversation_from_messages",
            return_value={"queries": [{"prompt": "q", "response": "a"}]},
        ), patch(
            "application.core.model_utils.get_provider_from_model_id",
            return_value="openai",
        ), patch(
            "application.core.model_utils.get_api_key_for_provider",
            return_value="key",
        ), patch(
            "application.llm.llm_creator.LLMCreator.create_llm",
            return_value=Mock(),
        ), patch(
            "application.api.answer.services.compression.service.CompressionService",
            return_value=mock_service,
        ), patch.object(
            handler,
            "_rebuild_messages_after_compression",
            return_value=[{"role": "system", "content": "rebuilt"}],
        ), patch(
            "application.core.settings.settings",
            MagicMock(COMPRESSION_MODEL_OVERRIDE=None),
        ):
            success, messages = handler._perform_in_memory_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is True
        assert messages is not None
        assert agent.compressed_summary == "summary"


# ---------------------------------------------------------------------------
# _perform_mid_execution_compression — additional edge cases
# ---------------------------------------------------------------------------


class TestPerformMidExecutionCompressionEdgeCases:

    def test_no_conversation_falls_back_to_in_memory(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}

        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = None

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=Mock(),
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler,
            "_perform_in_memory_compression",
            return_value=(True, [{"role": "system", "content": "ok"}]),
        ) as mock_in_memory:
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        mock_in_memory.assert_called_once()
        assert success is True

    def test_compression_not_performed(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}

        mock_result = Mock()
        mock_result.success = True
        mock_result.compression_performed = False

        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = {"queries": []}

        mock_orchestrator = Mock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=mock_orchestrator,
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler, "_build_conversation_from_messages", return_value={"queries": []}
        ):
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is False
        assert messages is None

    def test_compression_didnt_reduce_tokens(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_metadata = Mock()
        mock_metadata.compressed_token_count = 1000
        mock_metadata.original_token_count = 900

        mock_result = Mock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.metadata = mock_metadata

        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = {"queries": []}

        mock_orchestrator = Mock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=mock_orchestrator,
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler, "_build_conversation_from_messages", return_value={"queries": []}
        ), patch.object(
            handler,
            "_prune_messages_minimal",
            return_value=[{"role": "system", "content": "pruned"}],
        ):
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
            )

        assert success is True

    def test_rebuild_returns_none(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.conversation_id = "conv1"
        agent.initial_user_id = "user1"
        agent.model_id = "gpt-4"
        agent.decoded_token = {}
        agent.context_limit_reached = False
        agent.current_token_count = 0

        mock_metadata = Mock()
        mock_metadata.compressed_token_count = 100
        mock_metadata.original_token_count = 1000
        mock_metadata.compression_ratio = 10.0
        mock_metadata.to_dict.return_value = {}

        mock_result = Mock()
        mock_result.success = True
        mock_result.compression_performed = True
        mock_result.compressed_summary = "summary"
        mock_result.recent_queries = []
        mock_result.metadata = mock_metadata

        mock_conv_service = Mock()
        mock_conv_service.get_conversation.return_value = {"queries": []}

        mock_orchestrator = Mock()
        mock_orchestrator.compress_mid_execution.return_value = mock_result

        with patch(
            "application.api.answer.services.compression.CompressionOrchestrator",
            return_value=mock_orchestrator,
        ), patch(
            "application.api.answer.services.conversation_service.ConversationService",
            return_value=mock_conv_service,
        ), patch.object(
            handler, "_build_conversation_from_messages", return_value={"queries": []}
        ), patch.object(
            handler, "_rebuild_messages_after_compression", return_value=None
        ):
            success, messages = handler._perform_mid_execution_compression(
                agent, [{"role": "user", "content": "hi"}]
            )

        assert success is False
        assert messages is None


# ---------------------------------------------------------------------------
# _build_conversation_from_messages — additional edge cases
# ---------------------------------------------------------------------------


class TestBuildConversationEdgeCases:

    def test_function_call_without_call_id(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "name": "search",
                            "args": {"q": "X"},
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "done"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        queries = result["queries"]
        # The tool call should still be tracked
        assert len(queries) >= 1

    def test_function_response_in_assistant_content(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": [
                    {
                        "function_response": {
                            "name": "search",
                            "response": {"result": "found"},
                            "call_id": "c1",
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "final"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None

    def test_tool_role_without_function_response_format(self):
        """Tool message with plain string content, no matching call_id."""
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "calling tool"},
            {"role": "tool", "content": "tool output text"},
            {"role": "assistant", "content": "done"},
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None

    def test_pending_tool_calls_committed(self):
        handler = ConcreteHandler()
        messages = [
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": [
                    {
                        "function_call": {
                            "name": "search",
                            "args": {},
                            "call_id": "c1",
                        }
                    }
                ],
            },
        ]
        result = handler._build_conversation_from_messages(messages)
        assert result is not None
        assert len(result["queries"]) == 1
        assert len(result["queries"][0]["tool_calls"]) == 1


# ---------------------------------------------------------------------------
# handle_tool_calls — compression success path
# ---------------------------------------------------------------------------


class TestHandleToolCallsCompressionSuccess:

    def test_compression_success_continues(self):
        handler = ConcreteHandler()
        agent = Mock()
        call_count = {"n": 0}

        def check_limit(messages):
            call_count["n"] += 1
            return call_count["n"] == 1  # Only trigger on first call

        agent._check_context_limit = Mock(side_effect=check_limit)
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        def fake_execute(tools_dict, call):
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)

        with patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = True

            with patch.object(
                handler,
                "_perform_mid_execution_compression",
                return_value=(True, [{"role": "system", "content": "compressed"}]),
            ):
                calls = [ToolCall(id="c1", name="a_1", arguments="{}")]
                gen = handler.handle_tool_calls(agent, calls, {"1": {"name": "t"}}, [])
                events = []
                try:
                    while True:
                        events.append(next(gen))
                except StopIteration:
                    pass

        info_events = [
            e for e in events
            if isinstance(e, dict) and e.get("type") == "info"
        ]
        assert len(info_events) == 1

    def test_compression_failure_after_some_tools(self):
        handler = ConcreteHandler()
        agent = Mock()
        agent.context_limit_reached = False
        agent.llm.__class__.__name__ = "MockLLM"
        agent.tool_executor.check_pause = Mock(return_value=None)

        exec_count = {"n": 0}

        def check_limit(messages):
            return exec_count["n"] >= 1

        agent._check_context_limit = Mock(side_effect=check_limit)

        def fake_execute(tools_dict, call):
            exec_count["n"] += 1
            yield {"type": "tool_call", "data": {"status": "pending"}}
            return ("tool result", call.id)

        agent._execute_tool_action = Mock(side_effect=fake_execute)

        with patch(
            "application.core.settings.settings"
        ) as mock_settings:
            mock_settings.ENABLE_CONVERSATION_COMPRESSION = True

            with patch.object(
                handler,
                "_perform_mid_execution_compression",
                return_value=(False, None),
            ):
                calls = [
                    ToolCall(id="c1", name="a_1", arguments="{}"),
                    ToolCall(id="c2", name="b_1", arguments="{}"),
                ]
                gen = handler.handle_tool_calls(agent, calls, {"1": {"name": "t"}}, [])
                events = []
                try:
                    while True:
                        events.append(next(gen))
                except StopIteration:
                    pass

        skip_events = [
            e for e in events
            if isinstance(e, dict) and e.get("data", {}).get("status") == "skipped"
        ]
        assert len(skip_events) == 1  # Only second call skipped
