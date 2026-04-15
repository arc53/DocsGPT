"""Extended tests for application/api/answer/routes/base.py.

The previous suite depended on mock_mongo_db + bson.ObjectId, both removed
post Mongo -> Postgres cutover. Tests will be rebuilt on top of pg_conn
+ the new repositories in a follow-up pass.
"""

import pytest


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


# =====================================================================
# Continuation / paused stream path tests (lines 296-378)
# =====================================================================


@pytest.mark.unit
class TestCompleteStreamPausedContinuation:
    """Cover lines 296-378: tool_calls_pending pauses stream and saves state."""

    def test_paused_stream_yields_id_and_end(self, mock_mongo_db, flask_app):
        """When agent signals tool_calls_pending, stream yields id + end."""
        import json
        from unittest.mock import MagicMock, patch

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            pending_data = {
                "type": "tool_calls_pending",
                "data": {
                    "pending_tool_calls": [{"id": "call_1", "function": {"name": "search"}}]
                },
            }
            mock_agent.gen.return_value = iter([pending_data])
            mock_agent._pending_continuation = {
                "messages": [{"role": "user", "content": "Q"}],
                "pending_tool_calls": [{"id": "call_1"}],
                "tools_dict": {"search": {}},
            }
            mock_agent.tools = []
            mock_agent.tool_executor = MagicMock()
            mock_agent.tool_executor.client_tools = None

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "conv_paused"

            with patch("application.api.answer.routes.base.ContinuationService") as MockCS:
                mock_cs_instance = MagicMock()
                MockCS.return_value = mock_cs_instance

                stream = list(
                    resource.complete_stream(
                        question="Q",
                        agent=mock_agent,
                        conversation_id="conv_paused",
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_save_conversation=True,
                        model_id="gpt-4",
                    )
                )

            # Must have id and end events
            id_chunks = [s for s in stream if '"type": "id"' in s]
            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(id_chunks) == 1
            assert len(end_chunks) == 1

            # ContinuationService.save_state must have been called
            mock_cs_instance.save_state.assert_called_once()

    def test_paused_stream_creates_conversation_when_none(self, mock_mongo_db, flask_app):
        """When paused and no conversation_id, one is created first."""
        import json
        from unittest.mock import MagicMock, patch

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            pending_data = {
                "type": "tool_calls_pending",
                "data": {"pending_tool_calls": []},
            }
            mock_agent.gen.return_value = iter([pending_data])
            mock_agent._pending_continuation = {
                "messages": [],
                "pending_tool_calls": [],
                "tools_dict": {},
            }
            mock_agent.tools = []
            mock_agent.tool_executor = MagicMock()
            mock_agent.tool_executor.client_tools = None

            resource.conversation_service = MagicMock()
            resource.conversation_service.save_conversation.return_value = "new_conv_id"

            with patch("application.api.answer.routes.base.ContinuationService") as MockCS, \
                 patch("application.api.answer.routes.base.LLMCreator.create_llm") as mock_llm_create, \
                 patch("application.api.answer.routes.base.get_api_key_for_provider") as mock_api_key:
                mock_cs_instance = MagicMock()
                MockCS.return_value = mock_cs_instance
                mock_api_key.return_value = "sys_key"
                mock_llm_create.return_value = MagicMock()

                stream = list(
                    resource.complete_stream(
                        question="Q",
                        agent=mock_agent,
                        conversation_id=None,  # No existing conv_id
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_save_conversation=True,
                        model_id="gpt-4",
                    )
                )

            # save_conversation should have been called to create the conversation
            resource.conversation_service.save_conversation.assert_called_once()
            id_chunks = [s for s in stream if '"type": "id"' in s]
            assert len(id_chunks) == 1

    def test_paused_stream_continuation_save_error_handled(self, mock_mongo_db, flask_app):
        """When ContinuationService.save_state raises, stream still ends cleanly."""
        import json
        from unittest.mock import MagicMock, patch

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            pending_data = {
                "type": "tool_calls_pending",
                "data": {"pending_tool_calls": []},
            }
            mock_agent.gen.return_value = iter([pending_data])
            mock_agent._pending_continuation = {
                "messages": [],
                "pending_tool_calls": [],
                "tools_dict": {},
            }
            mock_agent.tools = []
            mock_agent.tool_executor = MagicMock()
            mock_agent.tool_executor.client_tools = None

            resource.conversation_service = MagicMock()

            with patch("application.api.answer.routes.base.ContinuationService") as MockCS:
                mock_cs_instance = MagicMock()
                mock_cs_instance.save_state.side_effect = Exception("save error")
                MockCS.return_value = mock_cs_instance

                stream = list(
                    resource.complete_stream(
                        question="Q",
                        agent=mock_agent,
                        conversation_id="conv_err",
                        user_api_key=None,
                        decoded_token={"sub": "u"},
                        should_save_conversation=True,
                        model_id="gpt-4",
                    )
                )

            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(end_chunks) == 1

    def test_paused_stream_no_pending_continuation_still_ends(self, mock_mongo_db, flask_app):
        """When paused=True but _pending_continuation is None, still yield id+end."""
        import json
        from unittest.mock import MagicMock

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()

            pending_data = {
                "type": "tool_calls_pending",
                "data": {"pending_tool_calls": []},
            }
            mock_agent.gen.return_value = iter([pending_data])
            # _pending_continuation is None
            del mock_agent._pending_continuation
            mock_agent._pending_continuation = None

            resource.conversation_service = MagicMock()

            stream = list(
                resource.complete_stream(
                    question="Q",
                    agent=mock_agent,
                    conversation_id="conv_npc",
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                )
            )

            # Should have id and end events
            id_chunks = [s for s in stream if '"type": "id"' in s]
            end_chunks = [s for s in stream if '"type": "end"' in s]
            assert len(id_chunks) == 1
            assert len(end_chunks) == 1


@pytest.mark.unit
class TestValidateRequestContinuationMode:
    """Cover lines 50-52: tool_actions present requires conversation_id."""

    def test_tool_actions_requires_conversation_id(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {"tool_actions": [{"id": "call_1", "result": "ok"}]}
            result = resource.validate_request(data)
            # Missing conversation_id should fail
            assert result is not None
            assert result.status_code == 400

    def test_tool_actions_with_conversation_id_passes(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {
                "tool_actions": [{"id": "call_1", "result": "ok"}],
                "conversation_id": str(ObjectId()),
            }
            result = resource.validate_request(data)
            assert result is None


@pytest.mark.unit
class TestCompleteStreamContinuationMode:
    """Cover lines 223-229: _continuation kwarg routes to gen_continuation."""

    def test_continuation_mode_calls_gen_continuation(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            mock_agent = MagicMock()
            mock_agent.gen_continuation.return_value = iter([{"answer": "resumed"}])

            stream = list(
                resource.complete_stream(
                    question="",
                    agent=mock_agent,
                    conversation_id="conv_cont",
                    user_api_key=None,
                    decoded_token={"sub": "u"},
                    should_save_conversation=False,
                    _continuation={
                        "messages": [{"role": "user", "content": "Q"}],
                        "tools_dict": {"search": {}},
                        "pending_tool_calls": [{"id": "call_1"}],
                        "tool_actions": [{"id": "call_1", "result": "found it"}],
                    },
                )
            )

            mock_agent.gen_continuation.assert_called_once()
            mock_agent.gen.assert_not_called()
            answer_chunks = [s for s in stream if '"type": "answer"' in s]
            assert len(answer_chunks) == 1
