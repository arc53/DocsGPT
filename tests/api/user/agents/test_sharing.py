"""Tests for application/api/user/agents/sharing.py.

Uses the ephemeral ``pg_conn`` fixture to exercise the real PG repository
code paths (agents, users).
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.sharing.db_session", _yield
    ), patch(
        "application.api.user.agents.sharing.db_readonly", _yield
    ):
        yield


def _make_agent(pg_conn, user_id="owner", *, shared=False, shared_token=None):
    from application.storage.db.repositories.agents import AgentsRepository
    agent = AgentsRepository(pg_conn).create(
        user_id,
        "Agent",
        "published",
        description="desc",
    )
    if shared:
        AgentsRepository(pg_conn).update(
            str(agent["id"]), user_id,
            {"shared": True, "shared_token": shared_token},
        )
        agent = AgentsRepository(pg_conn).get(str(agent["id"]), user_id)
    return agent


class TestSharedAgentGet:
    def test_returns_400_missing_token(self, app):
        from application.api.user.agents.sharing import SharedAgent

        with app.test_request_context("/api/shared_agent"):
            from flask import request
            request.decoded_token = None
            response = SharedAgent().get()
        assert response.status_code == 400

    def test_returns_404_for_unknown_token(self, app, pg_conn):
        from application.api.user.agents.sharing import SharedAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agent?token=unknown"
        ):
            from flask import request
            request.decoded_token = None
            response = SharedAgent().get()
        assert response.status_code == 404

    def test_returns_agent_for_known_token(self, app, pg_conn):
        from application.api.user.agents.sharing import SharedAgent

        _make_agent(pg_conn, shared=True, shared_token="abc123")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agent?token=abc123"
        ):
            from flask import request
            request.decoded_token = None
            response = SharedAgent().get()
        assert response.status_code == 200
        data = response.json
        assert data["shared_token"] == "abc123"
        assert data["shared"] is True

    def test_records_shared_with_different_user(self, app, pg_conn):
        from application.api.user.agents.sharing import SharedAgent

        _make_agent(pg_conn, user_id="owner", shared=True, shared_token="tk1")

        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agent?token=tk1"
        ):
            from flask import request
            request.decoded_token = {"sub": "other-user"}
            response = SharedAgent().get()
        assert response.status_code == 200

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.sharing import SharedAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.sharing.db_readonly", _broken
        ), app.test_request_context("/api/shared_agent?token=x"):
            from flask import request
            request.decoded_token = None
            response = SharedAgent().get()
        assert response.status_code == 400


class TestSharedAgents:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.sharing import SharedAgents

        with app.test_request_context("/api/shared_agents"):
            from flask import request
            request.decoded_token = None
            response = SharedAgents().get()
        assert response.status_code == 401

    def test_returns_empty_list_for_new_user(self, app, pg_conn):
        from application.api.user.agents.sharing import SharedAgents

        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agents"
        ):
            from flask import request
            request.decoded_token = {"sub": "new-user"}
            response = SharedAgents().get()
        assert response.status_code == 200
        assert response.json == []

    def test_returns_shared_agents_for_user(self, app, pg_conn):
        """After SharedAgent adds an agent to the user's shared_with_me, it
        should appear in SharedAgents."""
        from application.api.user.agents.sharing import SharedAgent, SharedAgents

        _make_agent(pg_conn, user_id="owner", shared=True, shared_token="tk2")

        # Trigger add-shared flow via SharedAgent
        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agent?token=tk2"
        ):
            from flask import request
            request.decoded_token = {"sub": "viewer-user"}
            SharedAgent().get()

        with _patch_db(pg_conn), app.test_request_context(
            "/api/shared_agents"
        ):
            from flask import request
            request.decoded_token = {"sub": "viewer-user"}
            response = SharedAgents().get()
        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["shared"] is True

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.sharing import SharedAgents

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.sharing.db_session", _broken
        ), app.test_request_context("/api/shared_agents"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = SharedAgents().get()
        assert response.status_code == 400


class TestShareAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent", method="PUT", json={"id": "x", "shared": True}
        ):
            from flask import request
            request.decoded_token = None
            response = ShareAgent().put()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent", method="PUT", json={"shared": True}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ShareAgent().put()
        assert response.status_code == 400

    def test_returns_400_missing_shared(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent", method="PUT", json={"id": "x"}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ShareAgent().put()
        assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app, pg_conn):
        from application.api.user.agents.sharing import ShareAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": "00000000-0000-0000-0000-000000000000", "shared": True},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ShareAgent().put()
        assert response.status_code == 404

    def test_shares_agent(self, app, pg_conn):
        from application.api.user.agents.sharing import ShareAgent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = _make_agent(pg_conn, user_id="owner")
        agent_id = str(agent["id"])

        with _patch_db(pg_conn), app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": agent_id, "shared": True, "username": "alice"},
        ):
            from flask import request
            request.decoded_token = {"sub": "owner"}
            response = ShareAgent().put()

        assert response.status_code == 200
        assert response.json["success"] is True
        assert response.json["shared_token"]  # non-empty token generated
        got = AgentsRepository(pg_conn).get(agent_id, "owner")
        assert got["shared"] is True
        assert got["shared_token"]
        assert got["shared_metadata"]["shared_by"] == "alice"

    def test_unshares_agent(self, app, pg_conn):
        from application.api.user.agents.sharing import ShareAgent
        from application.storage.db.repositories.agents import AgentsRepository

        agent = _make_agent(pg_conn, user_id="owner", shared=True, shared_token="tk")
        agent_id = str(agent["id"])

        with _patch_db(pg_conn), app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": agent_id, "shared": False},
        ):
            from flask import request
            request.decoded_token = {"sub": "owner"}
            response = ShareAgent().put()
        assert response.status_code == 200
        got = AgentsRepository(pg_conn).get(agent_id, "owner")
        assert got["shared"] is False
        assert got["shared_token"] is None

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.sharing import ShareAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.sharing.db_session", _broken
        ), app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": "x", "shared": True},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = ShareAgent().put()
        assert response.status_code == 400
