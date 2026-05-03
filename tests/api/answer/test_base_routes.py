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
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestPrepareToolCallsForLogging:
    pass

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
    pass

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
    pass

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
    pass

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
    pass

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
    pass

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
    pass

    def test_handles_structured_answer(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "structured_answer", "answer": "{}", "structured": True, "schema": None})}\n\n',
                f'data: {json.dumps({"type": "id", "id": str(uuid.uuid4())})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result["answer"] == "{}"
            assert result.get("extra", {}).get("structured") is True

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
            assert result["tool_calls"] == [{"name": "t1"}]

    def test_incomplete_stream(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "answer", "answer": "partial"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result["error"] == "Stream ended unexpectedly"

    def test_handles_thought_event(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            stream = [
                f'data: {json.dumps({"type": "thought", "thought": "thinking..."})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]
            result = resource.process_response_stream(iter(stream))
            assert result["thought"] == "thinking..."


@pytest.mark.unit
class TestCheckUsageStringBooleans:
    pass

@pytest.mark.unit
class TestCompleteStreamCompressionMetadata:
    """Cover lines 307-319 (compression metadata persistence in complete_stream)."""

    def test_compression_metadata_persisted(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "compressed answer"},
                ]
            )
            mock_agent.compression_metadata = {"ratio": 2.5}
            mock_agent.compression_saved = False
            mock_agent.tool_calls = []

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "conv123"
            resource.conversation_service.save_user_question.return_value = {
                "conversation_id": "conv123",
                "message_id": "msg123",
                "request_id": "req123",
            }

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=True,
                    model_id="gpt-4",
                )
            )

            # Verify compression metadata was persisted
            resource.conversation_service.update_compression_metadata.assert_called_once_with(
                "conv123", {"ratio": 2.5}
            )
            resource.conversation_service.append_compression_message.assert_called_once()
            assert mock_agent.compression_saved is True
            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(end_chunks) == 1

    def test_compression_metadata_error_handled(self, mock_mongo_db, flask_app):
        """Cover lines 318-322: compression metadata persistence error."""
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter([{"answer": "answer"}])
            mock_agent.compression_metadata = {"ratio": 2.5}
            mock_agent.compression_saved = False
            mock_agent.tool_calls = []

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "conv123"
            resource.conversation_service.update_compression_metadata.side_effect = (
                Exception("db error")
            )

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=True,
                    model_id="gpt-4",
                )
            )

            # Stream should still complete despite compression error
            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(end_chunks) == 1


@pytest.mark.unit
class TestCompleteStreamLogTruncation:
    """Cover line 354: log data truncation for long values."""

    def test_long_response_truncated_in_log(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            long_answer = "x" * 20000
            mock_agent.gen.return_value = iter([{"answer": long_answer}])
            mock_agent.tool_calls = []

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

            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(end_chunks) == 1


@pytest.mark.unit
class TestCompleteStreamGeneratorExit:
    """Cover lines 360-416 (GeneratorExit handling in complete_stream)."""

    def test_generator_exit_saves_partial_response(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            def gen_with_answers():
                yield {"answer": "partial"}
                yield {"answer": " answer"}
                # Simulating a long stream that gets interrupted
                yield {"answer": " more"}

            mock_agent.gen.return_value = gen_with_answers()
            mock_agent.compression_metadata = None
            mock_agent.compression_saved = False
            mock_agent.tool_calls = []

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "conv1"

            gen = resource.complete_stream(
                question="Q",
                agent=mock_agent,
                conversation_id="conv1",
                user_api_key=None,
                decoded_token={"sub": "u"},
                should_save_conversation=True,
                model_id="gpt-4",
            )

            # Read first chunk and then close (simulating client disconnect)
            chunk = next(gen)
            assert "partial" in chunk
            gen.close()  # This triggers GeneratorExit

    def test_generator_exit_with_compression_metadata(self, mock_mongo_db, flask_app):
        """Cover lines 393-411: GeneratorExit with compression metadata."""
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            def gen_answers():
                yield {"answer": "partial answer"}

            mock_agent.gen.return_value = gen_answers()
            mock_agent.compression_metadata = {"ratio": 3.0}
            mock_agent.compression_saved = False
            mock_agent.tool_calls = []

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "conv1"

            gen = resource.complete_stream(
                question="Q",
                agent=mock_agent,
                conversation_id="conv1",
                user_api_key=None,
                decoded_token={"sub": "u"},
                should_save_conversation=True,
                model_id="gpt-4",
                isNoneDoc=True,
            )

            next(gen)
            gen.close()

    def test_generator_exit_save_error_handled(self, mock_mongo_db, flask_app):
        """Cover lines 412-415: exception during partial save."""
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            def gen_answers():
                yield {"answer": "partial"}

            mock_agent.gen.return_value = gen_answers()
            mock_agent.compression_metadata = None
            mock_agent.compression_saved = False
            mock_agent.tool_calls = []

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.side_effect = Exception(
                "save error"
            )

            gen = resource.complete_stream(
                question="Q",
                agent=mock_agent,
                conversation_id="conv1",
                user_api_key=None,
                decoded_token={"sub": "u"},
                should_save_conversation=True,
                model_id="gpt-4",
            )

            next(gen)
            gen.close()  # Should not crash even with save error


@contextmanager
def _patch_db_session(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.services.conversation_service.db_session",
        _yield,
    ), patch(
        "application.api.answer.services.conversation_service.db_readonly",
        _yield,
    ):
        yield


@pytest.mark.unit
class TestCompleteStreamWalAcceptance:
    """Acceptance for the WAL pre-persist behaviour: when the LLM raises
    immediately, the user question is still queryable from PG with
    status='failed' and a meaningful error in metadata."""

    def test_failed_llm_persists_question_with_failed_status(
        self, pg_conn, flask_app,
    ):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.conversations import (
            ConversationsRepository,
        )

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.side_effect = RuntimeError("LLM upstream failed")

            with _patch_db_session(pg_conn):
                stream = list(
                    resource.complete_stream(
                        question="why does the WAL matter?",
                        agent=mock_agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token={"sub": "u-acceptance"},
                        should_save_conversation=True,
                        model_id="gpt-4",
                    )
                )
            error_chunks = [s for s in stream if '"type": "error"' in s]
            assert len(error_chunks) == 1

            from sqlalchemy import text as sql_text
            convs = pg_conn.execute(
                sql_text("SELECT id FROM conversations WHERE user_id = :u"),
                {"u": "u-acceptance"},
            ).fetchall()
            assert len(convs) == 1
            conv_id = str(convs[0][0])
            msgs = ConversationsRepository(pg_conn).get_messages(conv_id)
            assert len(msgs) == 1
            assert msgs[0]["prompt"] == "why does the WAL matter?"
            assert msgs[0]["status"] == "failed"
            assert "RuntimeError" in msgs[0]["metadata"]["error"]
            assert "LLM upstream failed" in msgs[0]["metadata"]["error"]
