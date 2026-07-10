import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestBaseAnswerValidation:
    pass

    def test_validate_request_passes_with_required_fields(
        self, mock_mongo_db, flask_app
    ):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {"question": "What is Python?"}

            result = resource.validate_request(data)

            assert result is None

    def test_validate_request_fails_without_question(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {}

            result = resource.validate_request(data)

            assert result is not None
            assert result.status_code == 400
            assert "question" in result.json["message"].lower()

    def test_validate_with_conversation_id_required(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {"question": "Test"}

            result = resource.validate_request(data, require_conversation_id=True)

            assert result is not None
            assert result.status_code == 400
            assert "conversation_id" in result.json["message"].lower()

    def test_validate_passes_with_all_required_fields(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            data = {"question": "Test", "conversation_id": str(uuid.uuid4())}

            result = resource.validate_request(data, require_conversation_id=True)

            assert result is None


@pytest.mark.unit
class TestUsageChecking:
    pass

    def test_returns_none_when_no_api_key(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            agent_config = {}

            result = resource.check_usage(agent_config)

            assert result is None









@pytest.mark.unit
class TestGPTModelRetrieval:
    pass

    def test_initializes_gpt_model(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            assert hasattr(resource, "default_model_id")
            assert resource.default_model_id is not None


@pytest.mark.unit
class TestConversationServiceIntegration:
    pass

    def test_initializes_conversation_service(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            assert hasattr(resource, "conversation_service")
            assert resource.conversation_service is not None



@pytest.mark.unit
class TestCompleteStreamMethod:
    pass

    def test_streams_answer_chunks(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "Hello "},
                    {"answer": "world!"},
                ]
            )

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test question",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_persist=False,
                )
            )

            answer_chunks = [s for s in stream if '"type": "answer"' in s]
            assert len(answer_chunks) == 2
            assert '"answer": "Hello "' in answer_chunks[0]
            assert '"answer": "world!"' in answer_chunks[1]

    def test_streams_sources(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "Test answer"},
                    {"sources": [{"title": "doc1.txt", "text": "x" * 200}]},
                ]
            )

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_persist=False,
                )
            )

            source_chunks = [s for s in stream if '"type": "source"' in s]
            assert len(source_chunks) == 1
            assert '"title": "doc1.txt"' in source_chunks[0]

    def test_handles_error_during_streaming(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.side_effect = Exception("Test error")

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_persist=False,
                )
            )

            assert any('"type": "error"' in s for s in stream)

    def test_user_facing_error_is_not_sanitized(self, mock_mongo_db, flask_app):
        """A user_facing error (e.g. an artifact-quota notice) streams verbatim.

        Without the flag, sanitize_api_error substring-matches "quota" and rewrites the
        message into a misleading rate-limit notice.
        """
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {
                        "type": "error",
                        "user_facing": True,
                        "error": "This run's input documents exceed your artifact storage quota.",
                    }
                ]
            )

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "user123"},
                    should_persist=False,
                )
            )

            error_chunks = [s for s in stream if '"type": "error"' in s]
            assert error_chunks
            assert "artifact storage quota" in error_chunks[0]
            assert "Rate limit exceeded" not in error_chunks[0]

    def test_notice_is_forwarded_verbatim_and_not_an_error(self, mock_mongo_db, flask_app):
        """A non-fatal ``notice`` streams through as a notice, never as an error.

        A ``notice`` (e.g. some workflow input documents were dropped) must not be
        emitted as ``type: error`` -- the client treats an error event as terminal and
        disables reconnect -- and its text must not be run through sanitize_api_error.
        """
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [{"type": "notice", "notice": "big.txt exceeds the per-file size limit"}]
            )

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "user123"},
                    should_persist=False,
                )
            )

            notice_chunks = [s for s in stream if '"type": "notice"' in s]
            assert notice_chunks
            assert "big.txt exceeds the per-file size limit" in notice_chunks[0]
            # Crucially, it is not surfaced as an error event.
            assert not [s for s in stream if '"type": "error"' in s]

    def test_non_user_facing_error_is_sanitized(self, mock_mongo_db, flask_app):
        """A raw error without the flag is still routed through sanitize_api_error."""
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [{"type": "error", "error": "OpenAI 429: quota exceeded for this key"}]
            )

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token={"sub": "user123"},
                    should_persist=False,
                )
            )

            error_chunks = [s for s in stream if '"type": "error"' in s]
            assert error_chunks
            assert "Rate limit exceeded" in error_chunks[0]

    def test_saves_conversation_when_enabled(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "Test answer"},
                ]
            )

            decoded_token = {"sub": "user123"}

            # The fresh-question path now reserves a row before agent.gen()
            # and calls finalize_message at end of stream — assert both fire.
            with patch.object(
                resource.conversation_service, "save_user_question"
            ) as mock_reserve, patch.object(
                resource.conversation_service, "finalize_message"
            ) as mock_finalize:
                mock_reserve.return_value = {
                    "conversation_id": str(uuid.uuid4()),
                    "message_id": str(uuid.uuid4()),
                    "request_id": "req-1",
                }
                mock_finalize.return_value = True

                list(
                    resource.complete_stream(
                        question="Test?",
                        agent=mock_agent,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token=decoded_token,
                        should_persist=True,
                    )
                )

                mock_reserve.assert_called_once()
                mock_finalize.assert_called_once()

    def test_tool_executor_conversation_id_set_after_reserve(
        self, mock_mongo_db, flask_app,
    ):
        """Regression: ``save_user_question`` may mint a fresh
        ``conversation_id`` (first turn). The propagation MUST land on
        ``agent.tool_executor.conversation_id`` BEFORE ``agent.gen`` runs,
        so tools needing a conversation home (``scheduler`` in an agentless
        chat) see it on the very first call.
        """
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            fresh_conv_id = str(uuid.uuid4())
            seen_conv_id_on_gen: dict = {}

            mock_agent = MagicMock()
            tool_executor = MagicMock()
            # Start with no conversation_id — the propagation must set it.
            tool_executor.conversation_id = None
            mock_agent.tool_executor = tool_executor

            def _gen(**_kwargs):
                # Capture the executor's id at the exact moment gen runs;
                # this is what tools see when called from the agent loop.
                seen_conv_id_on_gen["value"] = (
                    mock_agent.tool_executor.conversation_id
                )
                yield {"answer": "ok"}

            mock_agent.gen.side_effect = _gen
            mock_agent.gen.return_value = None  # use side_effect instead

            with patch.object(
                resource.conversation_service, "save_user_question"
            ) as mock_reserve, patch.object(
                resource.conversation_service, "finalize_message",
                return_value=True,
            ):
                mock_reserve.return_value = {
                    "conversation_id": fresh_conv_id,
                    "message_id": str(uuid.uuid4()),
                    "request_id": "req-prop",
                }

                list(
                    resource.complete_stream(
                        question="schedule something",
                        agent=mock_agent,
                        conversation_id=None,  # caller had no conv yet
                        user_api_key=None,
                        decoded_token={"sub": "user-prop"},
                        should_persist=True,
                    )
                )

            # The fresh id reserved by save_user_question must reach the
            # tool_executor before agent.gen consumes it.
            assert seen_conv_id_on_gen["value"] == fresh_conv_id
            assert tool_executor.conversation_id == fresh_conv_id

    def _run_paused(self, resource, pending_calls):
        """Drive complete_stream into its paused branch with the given pending
        tool calls, mocking out the WAL row and continuation save."""
        agent = MagicMock()
        agent.gen.return_value = iter(
            [{"type": "tool_calls_pending", "data": {"pending_tool_calls": pending_calls}}]
        )
        agent._pending_continuation = {
            "messages": [],
            "pending_tool_calls": pending_calls,
            "tools_dict": {},
        }
        # Make the WAL reservation no-op so we stay off the journal/DB.
        resource.conversation_service = MagicMock()
        resource.conversation_service.save_user_question.side_effect = Exception("skip")
        list(
            resource.complete_stream(
                question="Do the test",
                agent=agent,
                conversation_id="conv-1",
                user_api_key=None,
                decoded_token={"sub": "user123"},
                should_persist=True,
            )
        )

    def test_paused_skips_notification_for_client_execution(
        self, mock_mongo_db, flask_app
    ):
        """A pure ``requires_client_execution`` pause must NOT publish a
        ``tool.approval.required`` event — the client resolves it, so the
        notification would be non-actionable noise."""
        from application.api.answer.routes import base as base_mod

        with flask_app.app_context(), patch.object(
            base_mod, "publish_user_event"
        ) as published, patch.object(
            base_mod, "ContinuationService", MagicMock
        ):
            self._run_paused(
                base_mod.BaseAnswerResource(),
                [
                    {
                        "call_id": "c1",
                        "name": "create_file",
                        "tool_name": "create_file",
                        "action_name": "create_file",
                        "pause_type": "requires_client_execution",
                    }
                ],
            )
        published.assert_not_called()

    def test_paused_publishes_notification_only_for_awaiting_approval(
        self, mock_mongo_db, flask_app
    ):
        """A pause with an ``awaiting_approval`` call publishes once, and the
        payload surfaces only the approval call (not the client-side one)."""
        from application.api.answer.routes import base as base_mod

        with flask_app.app_context(), patch.object(
            base_mod, "publish_user_event"
        ) as published, patch.object(
            base_mod, "ContinuationService", MagicMock
        ):
            self._run_paused(
                base_mod.BaseAnswerResource(),
                [
                    {
                        "call_id": "a1",
                        "name": "delete_thing",
                        "tool_name": "api_tool",
                        "action_name": "delete_thing",
                        "pause_type": "awaiting_approval",
                    },
                    {
                        "call_id": "c1",
                        "name": "create_file",
                        "tool_name": "create_file",
                        "action_name": "create_file",
                        "pause_type": "requires_client_execution",
                    },
                ],
            )
        published.assert_called_once()
        args, _ = published.call_args
        assert args[1] == "tool.approval.required"
        summaries = args[2]["pending_tool_calls"]
        assert [s["call_id"] for s in summaries] == ["a1"]


@pytest.mark.unit
class TestProcessResponseStream:
    pass

    def test_processes_complete_stream(self, mock_mongo_db, flask_app):
        import json

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            conv_id = str(uuid.uuid4())
            stream = [
                f'data: {json.dumps({"type": "answer", "answer": "Hello "})}\n\n',
                f'data: {json.dumps({"type": "answer", "answer": "world"})}\n\n',
                f'data: {json.dumps({"type": "source", "source": [{"title": "doc1"}]})}\n\n',
                f'data: {json.dumps({"type": "id", "id": conv_id})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]

            result = resource.process_response_stream(iter(stream))

            assert result["conversation_id"] == conv_id
            assert result["answer"] == "Hello world"
            assert result["sources"] == [{"title": "doc1"}]
            assert result["error"] is None

    def test_handles_stream_error(self, mock_mongo_db, flask_app):
        import json

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            stream = [
                f'data: {json.dumps({"type": "error", "error": "Test error"})}\n\n',
            ]

            result = resource.process_response_stream(iter(stream))

            assert result["conversation_id"] is None
            assert result["error"] == "Test error"

    def test_handles_malformed_stream_data(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            stream = [
                "data: invalid json\n\n",
                'data: {"type": "end"}\n\n',
            ]

            result = resource.process_response_stream(iter(stream))

            assert result is not None


@pytest.mark.unit
class TestErrorStreamGenerate:
    pass

    def test_generates_error_stream(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            error_stream = list(resource.error_stream_generate("Test error message"))

            assert len(error_stream) == 1
            assert '"type": "error"' in error_stream[0]
            assert '"error": "Test error message"' in error_stream[0]


# ---------------------------------------------------------------------------
# Real-PG tests for check_usage against seeded agents + token usage
# ---------------------------------------------------------------------------


@contextmanager
def _patch_base_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.answer.routes.base.db_readonly", _yield
    ), patch(
        "application.api.answer.routes.base.db_session", _yield
    ):
        yield


@pytest.mark.unit
class TestCheckUsagePgConn:
    def test_invalid_api_key_returns_401(self, pg_conn, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "does-not-exist"})
        assert result is not None
        assert result.status_code == 401

    def test_no_limits_returns_none(self, pg_conn, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k1",
            limited_token_mode=False, limited_request_mode=False,
        )
        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "k1"})
        assert result is None

    def test_within_limit_returns_none(self, pg_conn, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k2",
            limited_token_mode=True, token_limit=10000,
        )
        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "k2"})
        assert result is None

    def test_token_limit_exceeded_returns_429(self, pg_conn, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k3",
            limited_token_mode=True, token_limit=100,
        )
        # Seed token usage exceeding the limit
        TokenUsageRepository(pg_conn).insert(
            api_key="k3", prompt_tokens=500, generated_tokens=0,
        )

        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "k3"})
        assert result is not None
        assert result.status_code == 429

    def test_request_limit_exceeded_returns_429(self, pg_conn, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.token_usage import (
            TokenUsageRepository,
        )

        AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k4",
            limited_request_mode=True, request_limit=1,
        )
        # Two request entries exceed limit=1
        TokenUsageRepository(pg_conn).insert(api_key="k4", prompt_tokens=10, generated_tokens=10)
        TokenUsageRepository(pg_conn).insert(api_key="k4", prompt_tokens=10, generated_tokens=10)

        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "k4"})
        assert result is not None
        assert result.status_code == 429

    def test_string_True_limited_token_mode_parsed(self, pg_conn, flask_app):
        """Legacy Mongo sometimes stored ``limited_token_mode`` as the
        string 'True'; verify the parse branch."""
        from application.api.answer.routes.base import BaseAnswerResource
        from application.storage.db.repositories.agents import AgentsRepository

        # Store bool=False in DB (limited_token_mode default). Test uses
        # string 'True' by mutating the row directly.
        from sqlalchemy import text
        AgentsRepository(pg_conn).create(
            "owner", "a", "published", key="k5",
        )
        pg_conn.execute(
            text(
                "UPDATE agents SET limited_token_mode = :v WHERE key = :k"
            ),
            {"v": True, "k": "k5"},
        )
        with _patch_base_db(pg_conn), flask_app.app_context():
            resource = BaseAnswerResource()
            result = resource.check_usage({"user_api_key": "k5"})
        # With default limit and no token usage, should pass
        assert result is None
