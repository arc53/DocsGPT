"""Gap-filling tests for application.api.user.agents.webhooks.

These tests cover the uncovered lines not reached by tests/api/user/test_webhooks.py:
  - webhooks.py:53-57  exception in AgentWebhook.get returns 400
  - webhooks.py:72     empty payload logging branch in _enqueue_webhook_task
  - webhooks.py:112    AgentWebhookListener.post with actual method invocation (not helper)
"""

from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# AgentWebhook.get – exception branch (lines 53-57)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookGetException:

    def test_returns_400_on_db_exception(self, app):
        """Lines 53-57: exception inside the try block returns 400."""
        from application.api.user.agents.webhooks import AgentWebhook

        mock_collection = Mock()
        mock_collection.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.webhooks.agents_collection", mock_collection
        ):
            with app.test_request_context(f"/api/agent_webhook?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentWebhook().get()

        assert response.status_code == 400
        assert "Error generating webhook URL" in response.json.get("message", "")


# ---------------------------------------------------------------------------
# AgentWebhookListener._enqueue_webhook_task – empty payload warning (line 72)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookListenerEmptyPayload:

    def test_empty_payload_logs_warning_and_still_enqueues(self, app):
        """Line 72: empty payload triggers the warning log but task is still enqueued."""
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
                # Empty dict is falsy — triggers the warning branch
                response = listener._enqueue_webhook_task("agent123", {}, "POST")

        assert response.status_code == 200
        assert response.json["task_id"] == "task_empty"

    def test_none_payload_logs_warning_and_still_enqueues(self, app):
        """Line 72: None payload also triggers the warning log."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_none"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/tok",
                method="POST",
            ):
                listener = AgentWebhookListener()
                response = listener._enqueue_webhook_task("agent123", None, "POST")

        assert response.status_code == 200
        assert response.json["task_id"] == "task_none"


# ---------------------------------------------------------------------------
# AgentWebhookListener.post – direct method call (line 112)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookListenerPostMethod:

    def test_post_method_enqueues_task_with_json_payload(self, app):
        """Line 112: the .post() method passes JSON body to _enqueue_webhook_task."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_post"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.delay.return_value = mock_task
            with app.test_request_context(
                "/api/webhooks/agents/mytoken",
                method="POST",
                json={"key": "value"},
            ):
                listener = AgentWebhookListener()
                response = listener.post(
                    webhook_token="mytoken",
                    agent={"_id": ObjectId(), "user": "user1"},
                    agent_id_str="agent999",
                )

        assert response.status_code == 200
        mock_process.delay.assert_called_once_with(
            agent_id="agent999", payload={"key": "value"}
        )
