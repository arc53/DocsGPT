"""Happy-path tests for application/api/user/agents/routes.py.

Exercises each endpoint with the ephemeral ``pg_conn`` fixture and real
repository classes so the route bodies run end-to-end.
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
        "application.api.user.agents.routes.db_session", _yield
    ), patch(
        "application.api.user.agents.routes.db_readonly", _yield
    ):
        yield


def _seed_agent(
    pg_conn, user="u", *, name="A", status="published", with_source=True,
    retriever="classic", **extra,
):
    from application.storage.db.repositories.agents import AgentsRepository
    repo = AgentsRepository(pg_conn)
    kwargs = {"description": "d", "retriever": retriever, **extra}
    if with_source:
        # Sources have a UUID FK; seed one
        from application.storage.db.repositories.sources import SourcesRepository
        src = SourcesRepository(pg_conn).create("src", user_id=user)
        kwargs["source_id"] = str(src["id"])
    return repo.create(user, name, status, **kwargs)


class TestGetAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import GetAgent

        with app.test_request_context("/api/get_agent?id=x"):
            from flask import request
            request.decoded_token = None
            response = GetAgent().get()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import GetAgent

        with app.test_request_context("/api/get_agent"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetAgent().get()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 400

    def test_returns_404_when_missing(self, app, pg_conn):
        from application.api.user.agents.routes import GetAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/get_agent?id=00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetAgent().get()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 404

    def test_returns_agent_by_id(self, app, pg_conn):
        from application.api.user.agents.routes import GetAgent

        user = "u-getA"
        agent = _seed_agent(pg_conn, user=user, name="Al")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/get_agent?id={agent['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetAgent().get()
        assert response.status_code == 200
        assert response.json["name"] == "Al"


class TestGetAgents:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import GetAgents

        with app.test_request_context("/api/get_agents"):
            from flask import request
            request.decoded_token = None
            response = GetAgents().get()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 401

    def test_returns_list_for_user(self, app, pg_conn):
        from application.api.user.agents.routes import GetAgents

        user = "u-list-agents"
        _seed_agent(pg_conn, user=user, name="B1")
        _seed_agent(pg_conn, user=user, name="B2")

        with _patch_db(pg_conn), app.test_request_context("/api/get_agents"):
            from flask import request
            request.decoded_token = {"sub": user}
            response = GetAgents().get()
        assert response.status_code == 200
        names = [a["name"] for a in response.json]
        assert "B1" in names and "B2" in names

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.routes import GetAgents

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context("/api/get_agents"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetAgents().get()
        assert response.status_code == 400


class TestDeleteAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import DeleteAgent

        with app.test_request_context(
            "/api/delete_agent?id=x", method="DELETE"
        ):
            from flask import request
            request.decoded_token = None
            response = DeleteAgent().delete()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import DeleteAgent

        with app.test_request_context(
            "/api/delete_agent", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteAgent().delete()
        assert response.status_code == 400

    def test_returns_404_missing_agent(self, app, pg_conn):
        from application.api.user.agents.routes import DeleteAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/delete_agent?id=00000000-0000-0000-0000-000000000000",
            method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = DeleteAgent().delete()
        assert response.status_code == 404

    def test_deletes_agent(self, app, pg_conn):
        from application.api.user.agents.routes import DeleteAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-delagent"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/delete_agent?id={agent['id']}", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = DeleteAgent().delete()
        assert response.status_code == 200
        assert AgentsRepository(pg_conn).get(str(agent["id"]), user) is None


class TestPinnedAgents:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import PinnedAgents

        with app.test_request_context("/api/pinned_agents"):
            from flask import request
            request.decoded_token = None
            response = PinnedAgents().get()
        assert response.status_code == 401

    def test_returns_empty_list_for_new_user(self, app, pg_conn):
        from application.api.user.agents.routes import PinnedAgents

        with _patch_db(pg_conn), app.test_request_context("/api/pinned_agents"):
            from flask import request
            request.decoded_token = {"sub": "new-user"}
            response = PinnedAgents().get()
        assert response.status_code == 200
        assert response.json == []


class TestPinAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import PinAgent

        with app.test_request_context("/api/pin_agent?id=x", method="POST"):
            from flask import request
            request.decoded_token = None
            response = PinAgent().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import PinAgent

        with app.test_request_context("/api/pin_agent", method="POST"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = PinAgent().post()
        assert response.status_code == 400

    def test_pins_agent(self, app, pg_conn):
        from application.api.user.agents.routes import PinAgent

        user = "u-pin"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/pin_agent?id={agent['id']}", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PinAgent().post()
        assert response.status_code == 200


class TestGetTemplateAgents:
    def test_returns_empty_without_templates(self, app, pg_conn):
        from application.api.user.agents.routes import GetTemplateAgents

        with _patch_db(pg_conn), app.test_request_context(
            "/api/template_agents"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTemplateAgents().get()
        assert response.status_code == 200
        assert response.json == []

    def test_returns_templates(self, app, pg_conn):
        from application.api.user.agents.routes import GetTemplateAgents
        from application.storage.db.repositories.agents import AgentsRepository

        AgentsRepository(pg_conn).create(
            "__system__", "Template One", "template",
        )

        with _patch_db(pg_conn), app.test_request_context(
            "/api/template_agents"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = GetTemplateAgents().get()
        assert response.status_code == 200
        names = [t["name"] for t in response.json]
        assert "Template One" in names


class TestAdoptAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import AdoptAgent

        with app.test_request_context(
            "/api/adopt_agent?id=x", method="POST"
        ):
            from flask import request
            request.decoded_token = None
            response = AdoptAgent().post()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import AdoptAgent

        with app.test_request_context(
            "/api/adopt_agent", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AdoptAgent().post()
        assert response.status_code == 400


class TestRemoveSharedAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        with app.test_request_context(
            "/api/remove_shared_agent?id=x", method="POST"
        ):
            from flask import request
            request.decoded_token = None
            response = RemoveSharedAgent().delete()
        assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        with app.test_request_context(
            "/api/remove_shared_agent", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = RemoveSharedAgent().delete()
        assert response.status_code == 400

    def test_removes_shared_agent(self, app, pg_conn):
        from application.api.user.agents.routes import RemoveSharedAgent
        from application.storage.db.repositories.agents import AgentsRepository
        from application.storage.db.repositories.users import UsersRepository

        owner = "owner-user"
        viewer = "u-rm-shared"
        agent = AgentsRepository(pg_conn).create(
            owner, "shared", "published", shared=True,
        )
        agent_id = str(agent["id"])
        UsersRepository(pg_conn).upsert(viewer)
        UsersRepository(pg_conn).add_shared(viewer, agent_id)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/remove_shared_agent?id={agent_id}",
            method="POST",
        ):
            from flask import request
            request.decoded_token = {"sub": viewer}
            response = RemoveSharedAgent().delete()
        assert response.status_code == 200


class TestCreateAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={"name": "n", "description": "d", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = None
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 401

    def test_returns_400_missing_required_draft(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={"description": "no name", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateAgent().post()
        assert response.status_code == 400

    def test_creates_draft_classic_agent(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-create-A"

        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={
                "name": "My Draft Agent",
                "description": "d",
                "agent_type": "classic",
                "status": "draft",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        assert response.status_code == 201
        # The agent was inserted
        agents = AgentsRepository(pg_conn).list_for_user(user)
        assert any(a["name"] == "My Draft Agent" for a in agents)
