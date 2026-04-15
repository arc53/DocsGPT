"""Tests for application/api/answer/routes/stream.py"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_stream_processor():
    """Create a mock StreamProcessor for stream tests."""
    with patch(
        "application.api.answer.routes.stream.StreamProcessor"
    ) as MockProcessor:
        processor = MagicMock()
        processor.decoded_token = {"sub": "test_user"}
        processor.conversation_id = uuid.uuid4().hex
        processor.agent_config = {}
        processor.agent_id = uuid.uuid4().hex
        processor.is_shared_usage = False
        processor.shared_token = None
        processor.model_id = "gpt-4"
        processor.build_agent.return_value = MagicMock()
        MockProcessor.return_value = processor
        yield processor


@pytest.fixture
def stream_client(mock_mongo_db, flask_app):
    """Create a test client with the stream route registered."""
    from flask_restx import Api

    from application.api.answer.routes.stream import answer_ns

    api = Api(flask_app)
    api.add_namespace(answer_ns)
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.mark.unit
class TestStreamResourcePost:
    def test_missing_question_returns_400(self, stream_client, mock_stream_processor):
        resp = stream_client.post(
            "/stream",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_successful_stream(self, stream_client, mock_stream_processor):
        def fake_stream(*args, **kwargs):
            yield f'data: {json.dumps({"type": "answer", "answer": "Hi"})}\n\n'
            yield f'data: {json.dumps({"type": "end"})}\n\n'

        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.stream.StreamResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.stream.StreamResource.complete_stream",
            side_effect=fake_stream,
        ):
            resp = stream_client.post(
                "/stream",
                data=json.dumps({"question": "What is Python?"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.content_type
            data = resp.get_data(as_text=True)
            assert '"type": "answer"' in data
            assert '"answer": "Hi"' in data

    def test_unauthorized_returns_401_stream(
        self, stream_client, mock_stream_processor
    ):
        mock_stream_processor.decoded_token = None
        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ):
            resp = stream_client.post(
                "/stream",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 401
            assert "text/event-stream" in resp.content_type
            data = resp.get_data(as_text=True)
            assert "Unauthorized" in data

    def test_usage_exceeded_returns_error(
        self, stream_client, mock_stream_processor
    ):
        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.stream.StreamResource.check_usage",
        ) as mock_check:
            mock_check.return_value = ({"error": "Usage limit exceeded"}, 429)
            resp = stream_client.post(
                "/stream",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 429

    def test_value_error_returns_400_stream(
        self, stream_client, mock_stream_processor
    ):
        mock_stream_processor.build_agent.side_effect = ValueError("bad data")
        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ):
            resp = stream_client.post(
                "/stream",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 400
            assert "text/event-stream" in resp.content_type
            data = resp.get_data(as_text=True)
            assert "Malformed request body" in data

    def test_general_exception_returns_400_stream(
        self, stream_client, mock_stream_processor
    ):
        mock_stream_processor.build_agent.side_effect = RuntimeError("crash")
        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ):
            resp = stream_client.post(
                "/stream",
                data=json.dumps({"question": "test"}),
                content_type="application/json",
            )
            assert resp.status_code == 400
            assert "text/event-stream" in resp.content_type
            data = resp.get_data(as_text=True)
            assert "Unknown error occurred" in data

    def test_index_in_data_requires_conversation_id(
        self, stream_client, mock_stream_processor
    ):
        """When 'index' is present, validate_request is called with require_conversation_id=True."""
        resp = stream_client.post(
            "/stream",
            data=json.dumps({"question": "test", "index": 0}),
            content_type="application/json",
        )
        # Should get 400 since conversation_id is missing
        assert resp.status_code == 400

    def test_stream_passes_attachments_and_index(
        self, stream_client, mock_stream_processor
    ):
        """Verify attachments and index params are forwarded to complete_stream."""

        def fake_stream(*args, **kwargs):
            yield f'data: {json.dumps({"type": "end"})}\n\n'

        conv_id = uuid.uuid4().hex
        with patch(
            "application.api.answer.routes.stream.StreamResource.validate_request",
            return_value=None,
        ), patch(
            "application.api.answer.routes.stream.StreamResource.check_usage",
            return_value=None,
        ), patch(
            "application.api.answer.routes.stream.StreamResource.complete_stream",
            side_effect=fake_stream,
        ) as mock_complete:
            resp = stream_client.post(
                "/stream",
                data=json.dumps(
                    {
                        "question": "test",
                        "conversation_id": conv_id,
                        "index": 3,
                        "attachments": ["att1", "att2"],
                    }
                ),
                content_type="application/json",
            )
            assert resp.status_code == 200
            call_kwargs = mock_complete.call_args
            assert call_kwargs.kwargs.get("index") == 3
            assert call_kwargs.kwargs.get("attachment_ids") == ["att1", "att2"]
