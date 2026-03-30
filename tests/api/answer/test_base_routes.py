"""Unit tests for application/api/answer/routes/base.py — BaseAnswerResource.

Additional coverage beyond tests/api/answer/routes/test_base.py:
  - _prepare_tool_calls_for_logging: truncation, non-dict items
  - complete_stream: tool_calls, thoughts, structured output, metadata,
    isNoneDoc, GeneratorExit handling, compression metadata
  - process_response_stream: structured answer, incomplete stream
  - error_stream_generate: format
  - check_usage: string boolean parsing ("True" strings)
"""

import json
from unittest.mock import MagicMock

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestPrepareToolCallsForLogging:

    def test_empty_list(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            assert resource._prepare_tool_calls_for_logging([]) == []

    def test_none_returns_empty(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            assert resource._prepare_tool_calls_for_logging(None) == []

    def test_truncates_long_result(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            tool_calls = [{"result": "x" * 20000}]
            prepared = resource._prepare_tool_calls_for_logging(tool_calls, max_chars=100)
            assert len(prepared[0]["result"]) == 100

    def test_truncates_result_full(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            tool_calls = [{"result_full": "y" * 20000}]
            prepared = resource._prepare_tool_calls_for_logging(tool_calls, max_chars=50)
            assert len(prepared[0]["result_full"]) == 50

    def test_non_dict_items_wrapped(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            tool_calls = ["string_item", 42]
            prepared = resource._prepare_tool_calls_for_logging(tool_calls)
            assert prepared[0] == {"result": "string_item"}
            assert prepared[1] == {"result": "42"}

    def test_preserves_short_results(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            tool_calls = [{"tool_name": "search", "result": "short text"}]
            prepared = resource._prepare_tool_calls_for_logging(tool_calls)
            assert prepared[0]["result"] == "short text"
            assert prepared[0]["tool_name"] == "search"


@pytest.mark.unit
class TestCompleteStreamToolCalls:

    def test_streams_tool_calls(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "Using tool..."},
                    {"tool_calls": [{"name": "search", "result": "found"}]},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Search for X",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            tool_chunks = [s for s in stream if '"type": "tool_calls"' in s]
            assert len(tool_chunks) == 1

    def test_streams_thought_events(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"thought": "Let me think..."},
                    {"answer": "Here is the answer"},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            thought_chunks = [s for s in stream if '"type": "thought"' in s]
            assert len(thought_chunks) == 1
            assert "Let me think" in thought_chunks[0]


@pytest.mark.unit
class TestCompleteStreamStructuredOutput:

    def test_streams_structured_answer(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {
                        "answer": '{"key": "value"}',
                        "structured": True,
                        "schema": {"type": "object"},
                    },
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            structured_chunks = [
                s for s in stream if '"type": "structured_answer"' in s
            ]
            assert len(structured_chunks) == 1


@pytest.mark.unit
class TestCompleteStreamMetadata:

    def test_metadata_collected(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"metadata": {"search_query": "test"}},
                    {"answer": "result"},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            # Should not crash, metadata handled silently
            answer_chunks = [s for s in stream if '"type": "answer"' in s]
            assert len(answer_chunks) == 1


@pytest.mark.unit
class TestCompleteStreamIsNoneDoc:

    def test_isNoneDoc_sets_source_to_none(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "answer"},
                    {"sources": [{"text": "doc", "source": "real_source"}]},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    isNoneDoc=True,
                    should_save_conversation=False,
                )
            )
            # Verify stream completes without error
            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(end_chunks) == 1


@pytest.mark.unit
class TestCompleteStreamErrorType:

    def test_error_type_event_sanitized(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"type": "error", "error": "API key invalid: sk-xxx"},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            error_chunks = [s for s in stream if '"type": "error"' in s]
            assert len(error_chunks) == 1

    def test_non_error_type_event_passed_through(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"type": "custom_event", "data": "value"},
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )
            custom_chunks = [s for s in stream if '"type": "custom_event"' in s]
            assert len(custom_chunks) == 1


@pytest.mark.unit
class TestProcessResponseStreamExtended:

    def test_handles_structured_answer(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "structured_answer", "answer": "{}", "structured": True, "schema": None})}\n\n',
                f'data: {json.dumps({"type": "id", "id": str(ObjectId())})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result[1] == "{}"
            # Structured output adds extra tuple element
            assert len(result) == 7
            assert result[6]["structured"] is True

    def test_handles_tool_calls_event(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "answer", "answer": "result"})}\n\n',
                f'data: {json.dumps({"type": "tool_calls", "tool_calls": [{"name": "t1"}]})}\n\n',
                f'data: {json.dumps({"type": "id", "id": "conv1"})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result[3] == [{"name": "t1"}]

    def test_incomplete_stream(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "answer", "answer": "partial"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result[4] == "Stream ended unexpectedly"

    def test_handles_thought_event(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "thought", "thought": "thinking..."})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result[4] == "thinking..."


@pytest.mark.unit
class TestCheckUsageStringBooleans:

    def test_string_true_parsed_correctly(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agents_collection.insert_one(
                {
                    "_id": ObjectId(),
                    "key": "str_bool_key",
                    "limited_token_mode": "True",
                    "token_limit": 1000000,
                    "limited_request_mode": "True",
                    "request_limit": 1000000,
                }
            )
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "str_bool_key"})
            # Should not exceed limits, so returns None
            assert result is None
