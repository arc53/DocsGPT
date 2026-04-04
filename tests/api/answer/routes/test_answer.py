"""Tests for application/api/answer/routes/answer.py"""

import json
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId


@pytest.fixture
def mock_stream_processor():
    """Create a mock StreamProcessor."""
    with patch(
        "application.api.answer.routes.answer.StreamProcessor"
    ) as MockProcessor:
         processor = MagicMock()
        processor.decoded_token = {"sub": "test_user"}
        processor.conversation_id = str(ObjectId())
        processor.agent_config = {}
        processor.agent_id = str(ObjectId())
        processor.is_shared_usage = False
        processor.shared_token = None
        processor.model_id = "gpt-4"
        processor.build_agent.return_value = MagicMock()
        processor.pre_fetch_docs.return_value = ("docs_together_content", [])  
        processor.pre_fetch_tools.return_value = None
        MockProcessor.return_value = processor
        yield processor


@pytest.fixture
def answer_client(mock_mongo_db, flask_app):
    """Create a test client with the answer route registered."""
    from flask_restx import Api

    from application.api.answer.routes.answer import answer_ns

    api = Api(flask_app)
    api.add_namespace(answer_ns)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.mark.unit
class TestAnswerResourcePost:
    def test_missing_question_returns_400(self, answer_client, mock_stream_processor):
        resp = answer_client.post(
            "/api/answer",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_successful_answer(self, answer_client, mock_stream_processor):
        conv_id = str(ObjectId())
        with patch.object(
            mock_stream_processor.build_agent.return_value,
            "gen",
            return_value=iter([]),
        ):
            with patch(
                "application.api.answer.routes.answer.AnswerResource.validate_request",
                return_value=None,
            ), patch(
                "application.api.answer.routes.answer.AnswerResource.check_usage",
                return_value=None,
            ), patch(
                "application.api.answer.routes.answer.AnswerResource.complete_stream",
                return_value=iter(
                    [
                        f'data: {json.dumps({"type": "answer", "answer": "Hello"})}\n\n',
                        f'data: {json.dumps({"type": "id", "id": conv_id})}\n\n',
                        f'data: {json.dumps({"type": "end"})}\n\n',
                    ]
                ),
            ), patch(
                "application.api.answer.routes.answer.AnswerResource.process_response_stream",
                return_value={"conversation_id": conv_id, "answer": "Hello", "sources": [], "tool_calls": [], "thought": "", "error": None},
            ):
                resp = answer_client.post(
                    "/api/answer",
                    data=json.dumps({"question": "What is Python?"}),
                    content_type="application/json",
                )
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["answer"] == "Hello"
                assert data["conversation_id"] == conv_id

    def test_unauthorized_returns_401(self, answer_client, mock_stream_processor):
        mock_stream_processor.decoded_token = None
        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ):
            resp = answer_client.post(
                "/api/answer",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 401
            assert resp.get_json()["error"] == "Unauthorized"

    def test_usage_exceeded_returns_error(self, answer_client, mock_stream_processor):

        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.check_usage",
        ) as mock_check:
            with flask_app_context(answer_client):
                mock_check.return_value = ({"error": "Usage limit exceeded"}, 429)

                resp = answer_client.post(
                    "/api/answer",
                    data=json.dumps({"question": "test"}),
                    content_type="application/json",
                )
                assert resp.status_code == 429

    def test_stream_error_returns_400(self, answer_client, mock_stream_processor):
        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.complete_stream",
            return_value=iter([]),
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.process_response_stream",
            return_value={"conversation_id": None, "answer": None, "sources": None, "tool_calls": None, "thought": None, "error": "Stream error"},
        ):
            resp = answer_client.post(
                "/api/answer",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 400
            assert resp.get_json()["error"] == "Stream error"

    def test_exception_returns_500(self, answer_client, mock_stream_processor):
        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.complete_stream",
            side_effect=RuntimeError("unexpected"),
        ):
            resp = answer_client.post(
                "/api/answer",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 500
            assert "error" in resp.get_json()

    def test_structured_info_merged_into_result(
        self, answer_client, mock_stream_processor
    ):
        conv_id = str(ObjectId())
        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.complete_stream",
            return_value=iter([]),
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.process_response_stream",
            return_value={"conversation_id": conv_id, "answer": '{"key": "val"}', "sources": [], "tool_calls": [], "thought": "", "error": None, "extra": {"structured": True, "schema": {"type": "object"}}},
        ):
            resp = answer_client.post(
                "/api/answer",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["structured"] is True
            assert data["schema"] == {"type": "object"}

    def test_result_contains_all_expected_fields(
        self, answer_client, mock_stream_processor
    ):
        conv_id = str(ObjectId())
        with patch(
            "application.api.answer.routes.answer.AnswerResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.complete_stream",
            return_value=iter([]),
        ), patch(
            "application.api.answer.routes.answer.AnswerResource.process_response_stream",
            return_value={"conversation_id": conv_id, "answer": "answer text", "sources": [{"title": "src"}], "tool_calls": [{"tool": "t"}], "thought": "thinking...", "error": None},
        ):
            resp = answer_client.post(
                "/api/answer",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            data = resp.get_json()
            assert data["conversation_id"] == conv_id
            assert data["answer"] == "answer text"
            assert data["sources"] == [{"title": "src"}]
            assert data["tool_calls"] == [{"tool": "t"}]
            assert data["thought"] == "thinking..."


def flask_app_context(client):
    """Helper to get app context from test client."""
    return client.application.app_context()
