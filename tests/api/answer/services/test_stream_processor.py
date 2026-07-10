"""Tests for application/api/answer/services/stream_processor.py.

The previous suite was tightly coupled to Mongo (mock_mongo_db fixture,
bson.ObjectId, bson.DBRef, find_one, etc.) which no longer exist after the
Mongo -> Postgres cutover. Rewriting these ~18 tests against the new
repositories (AgentsRepository / PromptsRepository / ConversationsRepository)
requires meaningful setup that is best done alongside the migration of the
StreamProcessor internals themselves.
"""

import pytest


# A static 24-hex-char string that is a valid ObjectId hex representation.
_STATIC_OID = "507f1f77bcf86cd799439011"


@pytest.mark.unit
class TestGetPromptFunction:
    pass

@pytest.mark.unit
class TestStreamProcessorInitialization:
    pass

    def test_initializes_with_decoded_token(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        conv_id = _STATIC_OID
        request_data = {
            "question": "What is Python?",
            "conversation_id": conv_id,
        }
        decoded_token = {"sub": "user_123", "email": "test@example.com"}

        processor = StreamProcessor(request_data, decoded_token)

        assert processor.data == request_data
        assert processor.decoded_token == decoded_token
        assert processor.initial_user_id == "user_123"
        assert processor.conversation_id == request_data["conversation_id"]

    def test_initializes_without_token(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test question"}

        processor = StreamProcessor(request_data, None)

        assert processor.decoded_token is None
        assert processor.initial_user_id is None
        assert processor.data == request_data

    def test_initializes_default_attributes(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"question": "Test"}, {"sub": "user_123"})

        assert processor.source == {}
        assert processor.all_sources == []
        assert processor.attachments == []
        assert processor.history == []
        assert processor.agent_config == {}
        assert processor.retriever_config == {}
        assert processor.is_shared_usage is False
        assert processor.shared_token is None

    def test_extracts_conversation_id_from_request(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        conv_id = _STATIC_OID
        request_data = {"question": "Test", "conversation_id": conv_id}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id == conv_id


@pytest.mark.unit
class TestStreamProcessorHistoryLoading:
    pass

    def test_uses_request_history_when_no_conversation_id(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "What is Python?",
            "history": [{"prompt": "Hello", "response": "Hi there!"}],
        }

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.conversation_id is None


@pytest.mark.unit
class TestStreamProcessorAgentConfiguration:
    pass

    def test_uses_default_config_without_api_key(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Test"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert isinstance(processor.agent_config, dict)
        assert processor.agent_id is None

    def test_embedded_workflow_without_saved_id(self):
        """A preview run with no saved workflow id carries no ``workflow_id``."""
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "Test",
            "workflow": {"nodes": [], "edges": []},
        }
        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert processor.agent_config["agent_type"] == "workflow"
        assert processor.agent_config["workflow"] == {"nodes": [], "edges": []}
        assert "workflow_id" not in processor.agent_config

    def test_embedded_workflow_with_saved_id_persists_run(self):
        """A saved workflow id alongside the embedded graph is captured so the
        run can persist a ``workflow_runs`` row for artifact listing."""
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {
            "question": "Test",
            "workflow": {"nodes": [], "edges": []},
            "workflow_id": "11111111-1111-1111-1111-111111111111",
        }
        processor = StreamProcessor(request_data, {"sub": "user_123"})
        processor._configure_agent()

        assert processor.agent_config["agent_type"] == "workflow"
        assert (
            processor.agent_config["workflow_id"]
            == "11111111-1111-1111-1111-111111111111"
        )
        assert processor.agent_config["workflow_owner"] == "user_123"



@pytest.mark.unit
class TestStreamProcessorDocPrefetch:
    pass

    def test_prefetch_skipped_when_no_active_docs(self):
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(
            {"question": "Hi there"},
            {"sub": "user_123"},
        )
        processor.initialize()
        processor.create_retriever = MagicMock()

        docs_together, docs = processor.pre_fetch_docs("Hi there")

        processor.create_retriever.assert_not_called()
        assert docs_together is None
        assert docs is None

    def test_prefetch_skipped_when_active_docs_is_default(self):
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor(
            {"question": "Hi", "active_docs": "default"},
            {"sub": "user_123"},
        )
        processor.initialize()
        processor.create_retriever = MagicMock()

        docs_together, docs = processor.pre_fetch_docs("Hi")

        processor.create_retriever.assert_not_called()
        assert docs_together is None
        assert docs is None





@pytest.mark.unit
class TestStreamProcessorAttachments:
    pass

    def test_handles_empty_attachments(self):
        from application.api.answer.services.stream_processor import StreamProcessor

        request_data = {"question": "Simple question"}

        processor = StreamProcessor(request_data, {"sub": "user_123"})

        assert processor.attachments == []
        assert (
            "attachments" not in processor.data
            or processor.data.get("attachments") is None
        )


@pytest.mark.unit
class TestToolPreFetch:
    """Tests for tool pre-fetching with saved parameter values."""


@pytest.mark.unit
class TestBuildContinuationFromMessages:
    """Stateless tool continuation rebuilt from the resent messages array.

    OpenAI-compatible clients (opencode, etc.) resend the full conversation but
    carry no conversation_id, so the agent + pending tool calls are reconstructed
    directly from the request instead of from server-side ``pending_tool_state``.
    """

    @staticmethod
    def _make_processor():
        from unittest.mock import MagicMock

        from application.api.answer.services.stream_processor import StreamProcessor

        processor = StreamProcessor({"question": ""}, {"sub": "user_123"})
        fake_agent = MagicMock()
        fake_agent.tool_executor.get_tools.return_value = {"search": object()}
        # build_agent touches the DB / config; stub it for this unit test.
        processor.build_agent = MagicMock(return_value=fake_agent)
        return processor, fake_agent

    def _messages_with_tool_call(self, arguments):
        return [
            {"role": "system", "content": "You are a bot"},
            {"role": "user", "content": "search the docs"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "search", "arguments": arguments},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "found it"},
        ]

    def test_rebuilds_pending_tool_calls_and_prior_messages(self):
        processor, fake_agent = self._make_processor()
        messages = self._messages_with_tool_call('{"q": "docs"}')
        tool_actions = [{"call_id": "call_1", "result": "found it"}]

        (
            agent,
            prior_messages,
            tools_dict,
            pending_tool_calls,
            returned_actions,
            reasoning,
        ) = processor.build_continuation_from_messages(messages, tool_actions)

        assert agent is fake_agent
        assert tools_dict == fake_agent.tool_executor.get_tools.return_value
        assert returned_actions is tool_actions
        assert reasoning == ""
        # prior_messages stop before the assistant-with-tool_calls message.
        assert prior_messages == messages[:2]
        assert len(pending_tool_calls) == 1
        call = pending_tool_calls[0]
        assert call["call_id"] == "call_1"
        assert call["name"] == "search"
        assert call["tool_name"] == "search"
        assert call["action_name"] == "search"
        assert call["arguments"] == {"q": "docs"}
        processor.build_agent.assert_called_once_with("")

    def test_invalid_json_arguments_default_to_empty_dict(self):
        processor, _ = self._make_processor()
        messages = self._messages_with_tool_call("not-json")

        _, _, _, pending_tool_calls, _, _ = (
            processor.build_continuation_from_messages(messages, [])
        )

        assert pending_tool_calls[0]["arguments"] == {}

    def test_dict_arguments_passed_through(self):
        processor, _ = self._make_processor()
        messages = self._messages_with_tool_call({"already": "parsed"})

        _, _, _, pending_tool_calls, _, _ = (
            processor.build_continuation_from_messages(messages, [])
        )

        assert pending_tool_calls[0]["arguments"] == {"already": "parsed"}

    def test_uses_last_assistant_tool_call_message(self):
        processor, _ = self._make_processor()
        messages = [
            {"role": "user", "content": "first"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "old", "content": "r1"},
            {"role": "user", "content": "second"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "new",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "new", "content": "r2"},
        ]

        _, prior_messages, _, pending_tool_calls, _, _ = (
            processor.build_continuation_from_messages(messages, [])
        )

        assert pending_tool_calls[0]["call_id"] == "new"
        # Everything up to (not including) the last assistant tool_calls message.
        assert prior_messages == messages[:4]

    def test_raises_when_no_assistant_tool_calls(self):
        processor, _ = self._make_processor()
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "no tools here"},
        ]

        with pytest.raises(ValueError, match="No assistant message with tool_calls"):
            processor.build_continuation_from_messages(messages, [])


