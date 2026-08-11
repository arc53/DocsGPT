"""Gap-coverage tests for application.api.user.agents.webhooks.

These tests use only stdlib IDs (uuid / hex strings) — no bson/ObjectId.
The agent routes still read from Mongo collections internally; we mock
those collection objects so the tests run without pymongo installed.
"""

import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch

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
    pass





# ---------------------------------------------------------------------------
# AgentWebhookListener — additional POST / GET edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentWebhookListenerGaps:
    pass

    def test_post_empty_payload_still_enqueues(self, app):
        """Empty dict payload does not block task enqueue (warning only)."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "task_empty"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.apply_async.return_value = mock_task
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
            mock_process.apply_async.return_value = mock_task
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
        call_kwargs = mock_process.apply_async.call_args[1]
        # apply_async wraps task args under ``kwargs=``.
        assert call_kwargs["kwargs"]["payload"] == {}

    def test_enqueue_returns_task_id_in_response(self, app):
        """Success response body includes task_id from the Celery task."""
        from application.api.user.agents.webhooks import AgentWebhookListener

        mock_task = Mock()
        mock_task.id = "celery-task-99"

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook"
        ) as mock_process:
            mock_process.apply_async.return_value = mock_task
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
            mock_process.apply_async.side_effect = RuntimeError("celery is down")
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


# ---------------------------------------------------------------------------
# Real-PG tests for AgentWebhook (get) and AgentWebhookListener
# ---------------------------------------------------------------------------


@contextmanager
def _patch_webhooks_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.webhooks.db_session", _yield
    ), patch(
        "application.api.user.agents.webhooks.db_readonly", _yield
    ):
        yield


@contextmanager
def _patch_base_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.base.db_readonly", _yield
    ), patch(
        "application.api.user.base.db_session", _yield
    ):
        yield


class TestAgentWebhookGet:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        with app.test_request_context("/api/agent_webhook?id=x"):
            from flask import request
            request.decoded_token = None
            response = AgentWebhook().get()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.webhooks import AgentWebhook

        with app.test_request_context("/api/agent_webhook"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentWebhook().get()
        assert response.status_code == 400

    def test_returns_404_missing_agent(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhook

        with _patch_webhooks_db(pg_conn), app.test_request_context(
            "/api/agent_webhook?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentWebhook().get()
        assert response.status_code == 404

    def test_generates_webhook_url(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhook
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-wh"
        agent = AgentsRepository(pg_conn).create(user, "a", "published")

        with _patch_webhooks_db(pg_conn), patch(
            "application.api.user.agents.webhooks.settings.API_URL",
            "https://api.test",
        ), app.test_request_context(
            f"/api/agent_webhook?id={agent['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentWebhook().get()
        assert response.status_code == 200
        assert response.json["webhook_url"].startswith(
            "https://api.test/api/webhooks/agents/"
        )

    def test_reuses_existing_webhook_token(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhook
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-wh-reuse"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", incoming_webhook_token="existing-tok",
        )

        with _patch_webhooks_db(pg_conn), patch(
            "application.api.user.agents.webhooks.settings.API_URL",
            "https://api.test",
        ), app.test_request_context(
            f"/api/agent_webhook?id={agent['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentWebhook().get()
        assert "existing-tok" in response.json["webhook_url"]


class TestAgentWebhookListener:
    def test_post_valid_enqueues_task(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhookListener
        from application.storage.db.repositories.agents import AgentsRepository
        from unittest.mock import MagicMock

        user = "u-wh-enq"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", incoming_webhook_token="tk-enq",
        )
        fake_task = MagicMock(id="task-post")

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-enq", method="POST",
            json={"event": "x"},
        ):
            listener = AgentWebhookListener()
            # Call directly with manually-injected kwargs (bypass decorator)
            response = listener.post(
                webhook_token="tk-enq",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 200
        assert response.json["task_id"] == "task-post"

    def test_get_collects_query_params(self, app, pg_conn):
        from application.api.user.agents.webhooks import AgentWebhookListener
        from application.storage.db.repositories.agents import AgentsRepository
        from unittest.mock import MagicMock

        user = "u-wh-get"
        agent = AgentsRepository(pg_conn).create(
            user, "a", "published", incoming_webhook_token="tk-get",
        )
        fake_task = MagicMock(id="task-get")

        with patch(
            "application.api.user.agents.webhooks.process_agent_webhook.apply_async",
            return_value=fake_task,
        ), app.test_request_context(
            "/api/webhooks/agents/tk-get?foo=bar&baz=42"
        ):
            listener = AgentWebhookListener()
            response = listener.get(
                webhook_token="tk-get",
                agent=agent,
                agent_id_str=str(agent["id"]),
            )
        assert response.status_code == 200
