from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestAgentWebhook:

    def test_returns_existing_webhook_url(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        agent_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            "incoming_webhook_token": "existing_token",
        }

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ), patch(
            "application.api.user.agents.webhooks.settings",
            Mock(API_URL="https://api.example.com"),
        ):
            with app.test_request_context(
                f"/api/agent_webhook?id={agent_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert "existing_token" in response.json["webhook_url"]
        mock_collection.update_one.assert_not_called()

    def test_generates_new_webhook_token(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        agent_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            "incoming_webhook_token": None,
        }

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ), patch(
            "application.api.user.agents.webhooks.settings",
            Mock(API_URL="https://api.example.com"),
        ), patch(
            "application.api.user.agents.webhooks.secrets.token_urlsafe",
            return_value="new_generated_token",
        ):
            with app.test_request_context(
                f"/api/agent_webhook?id={agent_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 200
        assert "new_generated_token" in response.json["webhook_url"]
        mock_collection.update_one.assert_called_once()

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        with app.test_request_context(f"/api/agent_webhook?id={ObjectId()}"):
            from flask import request

            request.decoded_token = None
            response = AgentWebhook().get()

        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        with app.test_request_context("/api/agent_webhook"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentWebhook().get()

        assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.agents.webhooks.agents_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/agent_webhook?id={ObjectId()}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 404


@pytest.mark.unit
class TestAgentWebhookListenerPost:

    def test_enqueues_task_on_valid_post(self, app):
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_abc"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
                json={"event": "new_message"},
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task(
                    "agent123", {"event": "new_message"}, "POST"
                )

        assert response.status_code == 200
        assert response.json["task_id"] == "task_abc"
        mock_process.delay.assert_called_once_with(
            agent_id="agent123", payload={"event": "new_message"}
        )

    def test_returns_400_on_missing_json(self, app):
        from application.api.user.agents.webhooks import AgentWebhookListener

        with app.test_request_context(
            "/api/webhooks/agents/tok",
            method="POST",
            json=None,
            content_type="application/json",
            data="",
        ):
            from flask import request as flask_request

            # Force get_json to return None (simulating empty/missing body)
            with patch.object(
                flask_request, "get_json", return_value=None
            ):
                listener = AgentWebhookListener()
                response = listener.post(
                    webhook_token="tok",
                    agent={"_id": ObjectId()},
                    agent_id_str="agent123",
                )

        assert response.status_code == 400

    def test_handles_enqueue_error(self, app):
        from application.api.user.agents.webhooks import AgentWebhookListener

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.side_effect = Exception("Queue down")
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
                json={"event": "test"},
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task(
                    "agent123", {"event": "test"}, "POST"
                )

        assert response.status_code == 500


@pytest.mark.unit
class TestAgentWebhookListenerGet:

    def test_uses_query_params_as_payload(self, app):
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_xyz"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok?event=ping&source=test",
                method="GET",
            ):
                listener = AgentWebhookListener()
                response = listener.get(
                    webhook_token="tok",
                    agent={"_id": ObjectId()},
                    agent_id_str="agent456",
                )

        assert response.status_code == 200
        call_kwargs = mock_process.delay.call_args[1]
        assert call_kwargs["payload"]["event"] == "ping"
        assert call_kwargs["payload"]["source"] == "test"
