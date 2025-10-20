import datetime
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId


@pytest.mark.unit
class TestBaseAnswerValidation:
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
            data = {"question": "Test", "conversation_id": str(ObjectId())}

            result = resource.validate_request(data, require_conversation_id=True)

            assert result is None


@pytest.mark.unit
class TestUsageChecking:
    def test_returns_none_when_no_api_key(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            agent_config = {}

            result = resource.check_usage(agent_config)

            assert result is None

    def test_returns_error_for_invalid_api_key(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "invalid_key_123"}

            result = resource.check_usage(agent_config)

            assert result is not None
            assert result.status_code == 401
            assert result.json["success"] is False
            assert "invalid" in result.json["message"].lower()

    def test_checks_token_limit_when_enabled(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": True,
                    "token_limit": 1000,
                    "limited_request_mode": False,
                }
            )

            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is None

    def test_checks_request_limit_when_enabled(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": False,
                    "limited_request_mode": True,
                    "request_limit": 100,
                }
            )

            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is None

    def test_uses_default_limits_when_not_specified(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": True,
                    "limited_request_mode": True,
                }
            )

            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is None

    def test_exceeds_token_limit(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            token_usage_collection = mock_mongo_db[settings.MONGO_DB_NAME][
                "token_usage"
            ]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": True,
                    "token_limit": 100,
                    "limited_request_mode": False,
                }
            )

            token_usage_collection.insert_one(
                {
                    "_id": ObjectId(),
                    "api_key": "test_key",
                    "prompt_tokens": 60,
                    "generated_tokens": 50,
                    "timestamp": datetime.datetime.now(),
                }
            )

            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is not None
            assert result.status_code == 429
            assert result.json["success"] is False
            assert "usage limit" in result.json["message"].lower()

    def test_exceeds_request_limit(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            token_usage_collection = mock_mongo_db[settings.MONGO_DB_NAME][
                "token_usage"
            ]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": False,
                    "limited_request_mode": True,
                    "request_limit": 2,
                }
            )

            now = datetime.datetime.now()
            for i in range(3):
                token_usage_collection.insert_one(
                    {
                        "_id": ObjectId(),
                        "api_key": "test_key",
                        "prompt_tokens": 10,
                        "generated_tokens": 10,
                        "timestamp": now,
                    }
                )
            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is not None
            assert result.status_code == 429
            assert result.json["success"] is False

    def test_both_limits_disabled_returns_none(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            agents_collection = mock_mongo_db[settings.MONGO_DB_NAME]["agents"]
            agent_id = ObjectId()

            agents_collection.insert_one(
                {
                    "_id": agent_id,
                    "key": "test_key",
                    "limited_token_mode": False,
                    "limited_request_mode": False,
                }
            )

            resource = BaseAnswerResource()
            agent_config = {"user_api_key": "test_key"}

            result = resource.check_usage(agent_config)

            assert result is None


@pytest.mark.unit
class TestGPTModelRetrieval:
    def test_initializes_gpt_model(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            assert hasattr(resource, "gpt_model")
            assert resource.gpt_model is not None


@pytest.mark.unit
class TestConversationServiceIntegration:
    def test_initializes_conversation_service(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            assert hasattr(resource, "conversation_service")
            assert resource.conversation_service is not None

    def test_has_access_to_user_logs_collection(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            assert hasattr(resource, "user_logs_collection")
            assert resource.user_logs_collection is not None


@pytest.mark.unit
class TestCompleteStreamMethod:
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

            mock_retriever = MagicMock()
            mock_retriever.get_params.return_value = {}

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test question",
                    agent=mock_agent,
                    retriever=mock_retriever,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_save_conversation=False,
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

            mock_retriever = MagicMock()
            mock_retriever.get_params.return_value = {}

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    retriever=mock_retriever,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_save_conversation=False,
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

            mock_retriever = MagicMock()
            mock_retriever.get_params.return_value = {}

            decoded_token = {"sub": "user123"}

            stream = list(
                resource.complete_stream(
                    question="Test?",
                    agent=mock_agent,
                    retriever=mock_retriever,
                    conversation_id=None,
                    user_api_key=None,
                    decoded_token=decoded_token,
                    should_save_conversation=False,
                )
            )

            assert any('"type": "error"' in s for s in stream)

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

            mock_retriever = MagicMock()
            mock_retriever.get_params.return_value = {}

            decoded_token = {"sub": "user123"}

            with patch.object(
                resource.conversation_service, "save_conversation"
            ) as mock_save:
                mock_save.return_value = str(ObjectId())

                list(
                    resource.complete_stream(
                        question="Test?",
                        agent=mock_agent,
                        retriever=mock_retriever,
                        conversation_id=None,
                        user_api_key=None,
                        decoded_token=decoded_token,
                        should_save_conversation=True,
                    )
                )

                mock_save.assert_called_once()

    def test_logs_to_user_logs_collection(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource
        from application.core.settings import settings

        with flask_app.app_context():
            resource = BaseAnswerResource()
            user_logs = mock_mongo_db[settings.MONGO_DB_NAME]["user_logs"]

            mock_agent = MagicMock()
            mock_agent.gen.return_value = iter(
                [
                    {"answer": "Test answer"},
                ]
            )

            mock_retriever = MagicMock()
            mock_retriever.get_params.return_value = {"retriever": "test"}

            decoded_token = {"sub": "user123"}

            list(
                resource.complete_stream(
                    question="Test question?",
                    agent=mock_agent,
                    retriever=mock_retriever,
                    conversation_id=None,
                    user_api_key="test_key",
                    decoded_token=decoded_token,
                    should_save_conversation=False,
                )
            )

            assert user_logs.count_documents({}) == 1
            log_entry = user_logs.find_one({})
            assert log_entry["action"] == "stream_answer"
            assert log_entry["user"] == "user123"
            assert log_entry["api_key"] == "test_key"
            assert log_entry["question"] == "Test question?"


@pytest.mark.unit
class TestProcessResponseStream:
    def test_processes_complete_stream(self, mock_mongo_db, flask_app):
        import json

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            conv_id = str(ObjectId())
            stream = [
                f'data: {json.dumps({"type": "answer", "answer": "Hello "})}\n\n',
                f'data: {json.dumps({"type": "answer", "answer": "world"})}\n\n',
                f'data: {json.dumps({"type": "source", "source": [{"title": "doc1"}]})}\n\n',
                f'data: {json.dumps({"type": "id", "id": conv_id})}\n\n',
                f'data: {json.dumps({"type": "end"})}\n\n',
            ]

            result = resource.process_response_stream(iter(stream))

            assert result[0] == conv_id
            assert result[1] == "Hello world"
            assert result[2] == [{"title": "doc1"}]
            assert result[5] is None

    def test_handles_stream_error(self, mock_mongo_db, flask_app):
        import json

        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            stream = [
                f'data: {json.dumps({"type": "error", "error": "Test error"})}\n\n',
            ]

            result = resource.process_response_stream(iter(stream))

            assert len(result) == 5
            assert result[0] is None
            assert result[4] == "Test error"

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
    def test_generates_error_stream(self, mock_mongo_db, flask_app):
        from application.api.answer.routes.base import BaseAnswerResource

        with flask_app.app_context():
            resource = BaseAnswerResource()

            error_stream = list(resource.error_stream_generate("Test error message"))

            assert len(error_stream) == 1
            assert '"type": "error"' in error_stream[0]
            assert '"error": "Test error message"' in error_stream[0]
