"""Gap-coverage tests for application.api.user.agents.webhooks.

These tests use only stdlib IDs (uuid / hex strings) — no bson/ObjectId.
The agent routes still read from Mongo collections internally; we mock
those collection objects so the tests run without pymongo installed.
"""

from unittest.mock import Mock, patch
import uuid

import pytest
from flask import Flask


def _fake_oid():
    """24-character hex string used as a substitute for a Mongo ObjectId string."""
    return uuid.uuid4().hex[:24]


@pytest.fixture
def app():
    return Flask(__name__)


# ---------------------------------------------------------------------------
# AgentWebhook.get — additional coverage beyond test_webhooks.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookGetGaps:

    def test_returns_400_on_invalid_agent_id(self, app):
        """Exception raised by ObjectId(bad_id) is caught and returns 400."""
        from application.api.user.agents.webhooks import AgentWebhook

        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("invalid id")

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/agent_webhook?id=not-an-objectid"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 400
        assert response.json["success"] is False

    def test_webhook_url_contains_base_url(self, app):
        """Returned webhook_url is prefixed with settings.API_URL."""
        from application.api.user.agents.webhooks import AgentWebhook

        agent_id = _fake_oid()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            "incoming_webhook_token": "tok123",
        }

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ), patch(
            "application.api.user.agents.webhooks.settings",
            Mock(API_URL="https://my.api.example.com/"),
        ):
            with app.test_request_context(f"/api/agent_webhook?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 200
        assert response.json["webhook_url"].startswith("https://my.api.example.com")
        assert "tok123" in response.json["webhook_url"]

    def test_generates_token_and_updates_collection(self, app):
        """When incoming_webhook_token is absent, a new one is generated and saved."""
        from application.api.user.agents.webhooks import AgentWebhook

        agent_id = _fake_oid()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            # no incoming_webhook_token key at all
        }

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ), patch(
            "application.api.user.agents.webhooks.settings",
            Mock(API_URL="https://api.example.com"),
        ), patch(
            "application.api.user.agents.webhooks.secrets.token_urlsafe",
            return_value="fresh_token_xyz",
        ):
            with app.test_request_context(f"/api/agent_webhook?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 200
        assert "fresh_token_xyz" in response.json["webhook_url"]
        mock_collection.update_one.assert_called_once()


# ---------------------------------------------------------------------------
# AgentWebhookListener — additional POST / GET edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookListenerGaps:

    def test_post_empty_payload_still_enqueues(self, app):
        """Empty dict payload does not block task enqueue (warning only)."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_empty"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
                json={},
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task("agent1", {}, "POST")

        assert response.status_code == 200
        assert response.json["task_id"] == "task_empty"

    def test_get_empty_query_string(self, app):
        """GET request with no query params produces an empty payload dict."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_noqs"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="GET",
            ):
                listener = AgentWebhookListener()
                response = listener.get(
                    webhook_token="tok",
                    agent={"_id": uuid.uuid4().hex},
                    agent_id_str="agentXYZ",
                )

        assert response.status_code == 200
        call_kwargs = mock_process.delay.call_args[1]
        assert call_kwargs["payload"] == {}

    def test_enqueue_returns_task_id_in_response(self, app):
        """Success response body includes task_id from the Celery task."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "celery-task-99"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
                json={"k": "v"},
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task("a1", {"k": "v"}, "POST")

        assert response.json["success"] is True
        assert response.json["task_id"] == "celery-task-99"

    def test_enqueue_error_returns_500_with_message(self, app):
        """Queue failure returns 500 with a human-readable message."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.side_effect = RuntimeError("celery is down")
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
                json={"x": 1},
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task("a1", {"x": 1}, "POST")

        assert response.status_code == 500
        assert response.json["success"] is False
        assert "message" in response.json
