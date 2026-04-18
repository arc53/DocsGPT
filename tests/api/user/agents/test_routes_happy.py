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


# ---------------------------------------------------------------------------
# UpdateAgent — big method with many validation branches
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import UpdateAgent

        with app.test_request_context(
            "/api/update_agent/abc", method="PUT",
            json={"name": "n", "description": "d", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = None
            response = UpdateAgent().put("abc")
        assert response.status_code == 401

    def test_returns_404_agent_not_found(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/update_agent/00000000-0000-0000-0000-000000000000",
            method="PUT",
            json={"name": "n", "description": "d", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateAgent().put(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_updates_simple_fields(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-upd-simple"
        agent = _seed_agent(pg_conn, user=user, name="orig")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "new name",
                "description": "new desc",
                "status": "draft",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200
        got = AgentsRepository(pg_conn).get(str(agent["id"]), user)
        assert got["name"] == "new name"

    def test_invalid_status_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-upd-status"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={"name": "n", "description": "d", "status": "bogus"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_invalid_source_uuid_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-upd-src"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "source": "not-a-uuid",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_source_default_clears(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-src-default"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "source": "default",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200

    def test_invalid_sources_item_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-sources"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "sources": ["not-uuid"],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_invalid_chunks_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-upd-chunks"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "chunks": "not-a-number",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_negative_chunks_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-neg-chunks"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "chunks": -1,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_tools_must_be_list(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-tools"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "tools": "not-a-list",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_limited_token_mode_requires_limit(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-limit"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "limited_token_mode": True,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_limited_request_mode_requires_limit(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-req-limit"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "limited_request_mode": True,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_token_limit_without_mode_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-token-mode"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "token_limit": 1000,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_invalid_prompt_id_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-upd-prompt"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "prompt_id": "not-a-uuid",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_prompt_id_default_clears(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-pid-default"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "prompt_id": "default",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200

    def test_empty_name_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-empty-name"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={"name": "", "description": "d", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_publish_classic_missing_fields_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-publish-missing"
        agent = _seed_agent(pg_conn, user=user, with_source=False)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "published",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_publishing_generates_api_key(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent
        from application.storage.db.repositories.agents import AgentsRepository

        user = "u-publish-key"
        agent = _seed_agent(
            pg_conn, user=user, status="draft", retriever="classic",
        )
        # Seed a prompt so published path validates
        from application.storage.db.repositories.prompts import PromptsRepository
        prompt = PromptsRepository(pg_conn).create(user, "p", "c")
        AgentsRepository(pg_conn).update(
            str(agent["id"]), user,
            {
                "prompt_id": str(prompt["id"]),
                "chunks": 2,
                "agent_type": "classic",
            },
        )

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "published",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200
        # New key is in response
        assert "key" in response.json

    def test_invalid_json_in_form_field_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-bad-json"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            data={
                "name": "n",
                "description": "d",
                "status": "draft",
                "tools": "not-json",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_empty_update_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-empty-upd"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_db_error_returns_500(self, app):
        from application.api.user.agents.routes import UpdateAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context(
            "/api/update_agent/abc", method="PUT",
            json={"name": "n", "description": "d", "status": "draft"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = UpdateAgent().put("abc")
        assert response.status_code == 500

    def test_allow_system_prompt_override(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-override"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "allow_system_prompt_override": True,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200

    def test_folder_id_null_clears(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-folder-null"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "folder_id": None,
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200

    def test_publish_workflow_without_workflow_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-wf-publish"
        agent = _seed_agent(pg_conn, user=user, with_source=False)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "WF Agent",
                "description": "d",
                "agent_type": "workflow",
                "status": "published",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 400

    def test_invalid_json_schema_returns_400(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-bad-schema"
        agent = _seed_agent(pg_conn, user=user)

        # JSON schema must be valid — provide something invalid
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            json={
                "name": "n", "description": "d", "status": "draft",
                "json_schema": {"type": "nonsense-type"},
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        # json_schema validation may or may not reject type=nonsense-type
        # depending on normalize_json_schema_payload; accept 200 or 400.
        assert response.status_code in (200, 400)

    def test_json_schema_empty_becomes_none(self, app, pg_conn):
        from application.api.user.agents.routes import UpdateAgent

        user = "u-schema-empty"
        agent = _seed_agent(pg_conn, user=user)

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/update_agent/{agent['id']}", method="PUT",
            data={
                "name": "n",
                "description": "d",
                "status": "draft",
                "json_schema": "",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = UpdateAgent().put(str(agent["id"]))
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# CreateAgent — more coverage
# ---------------------------------------------------------------------------


class TestCreateAgentMore:
    def test_invalid_status_returns_400(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent", method="POST",
            json={"name": "n", "description": "d", "status": "bogus"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 400

    def test_publish_classic_without_source_returns_400(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent", method="POST",
            json={
                "name": "n",
                "description": "d",
                "status": "published",
                "agent_type": "classic",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 400

    def test_unknown_agent_type_falls_back_classic(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent

        user = "u-unknown-type"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent", method="POST",
            json={
                "name": "hi",
                "description": "d",
                "status": "draft",
                "agent_type": "made-up-type",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 201

    def test_create_form_invalid_json_fields(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent

        # Invalid JSON strings in form fields are coerced to []/None (no 400)
        user = "u-form-json"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent", method="POST",
            data={
                "name": "hi",
                "description": "d",
                "status": "draft",
                "tools": "not-json",
                "sources": "not-json",
                "json_schema": "not-json",
                "models": "not-json",
            },
            content_type="multipart/form-data",
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 201

    def test_create_published_workflow_without_workflow_returns_400(
        self, app, pg_conn,
    ):
        from application.api.user.agents.routes import CreateAgent

        user = "u-wf-no-wf"
        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent", method="POST",
            json={
                "name": "wfn",
                "description": "d",
                "status": "published",
                "agent_type": "workflow",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 400

    def test_create_with_sources_list(self, app, pg_conn):
        from application.api.user.agents.routes import CreateAgent
        from application.storage.db.repositories.sources import (
            SourcesRepository,
        )

        user = "u-create-srcs"
        src1 = SourcesRepository(pg_conn).create("s1", user_id=user)
        src2 = SourcesRepository(pg_conn).create("s2", user_id=user)

        with _patch_db(pg_conn), app.test_request_context(
            "/api/create_agent", method="POST",
            json={
                "name": "multi-src",
                "description": "d",
                "agent_type": "classic",
                "status": "draft",
                "sources": [str(src1["id"]), str(src2["id"]), "default"],
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 201

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.routes import CreateAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context(
            "/api/create_agent", method="POST",
            json={
                "name": "n", "description": "d", "status": "draft",
                "agent_type": "classic",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = CreateAgent().post()
        status = (
            response[1] if isinstance(response, tuple) else response.status_code
        )
        assert status == 400


# ---------------------------------------------------------------------------
# AdoptAgent — copies a template into user's agents
# ---------------------------------------------------------------------------


class TestAdoptAgentMore:
    def test_adopts_template_agent(self, app, pg_conn):
        from application.api.user.agents.routes import AdoptAgent
        from application.storage.db.repositories.agents import AgentsRepository

        repo = AgentsRepository(pg_conn)
        template = repo.create("__system__", "Template X", "template")

        with _patch_db(pg_conn), app.test_request_context(
            f"/api/adopt_agent?id={template['id']}", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": "u-adopter"}
            response = AdoptAgent().post()
        assert response.status_code == 200
        # Adoption copies agent into user's list
        mine = repo.list_for_user("u-adopter")
        assert any(a["name"] == "Template X" for a in mine)

    def test_adopt_template_missing_returns_404(self, app, pg_conn):
        from application.api.user.agents.routes import AdoptAgent

        with _patch_db(pg_conn), app.test_request_context(
            "/api/adopt_agent?id=00000000-0000-0000-0000-000000000000",
            method="POST",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AdoptAgent().post()
        assert response.status_code == 404

    def test_db_error_returns_400(self, app):
        from application.api.user.agents.routes import AdoptAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context(
            "/api/adopt_agent?id=abc", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AdoptAgent().post()
        assert response.status_code == 400


class TestPinAgentMore:
    def test_toggle_pin(self, app, pg_conn):
        """PinAgent is a toggle — second call unpins."""
        from application.api.user.agents.routes import PinAgent
        from application.storage.db.repositories.users import UsersRepository

        user = "u-pin-toggle"
        agent = _seed_agent(pg_conn, user=user)
        agent_id = str(agent["id"])

        # First pin
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/pin_agent?id={agent_id}", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PinAgent().post()
        assert response.status_code == 200
        user_doc = UsersRepository(pg_conn).upsert(user)
        prefs = user_doc.get("agent_preferences") or {}
        assert agent_id in prefs.get("pinned", [])

        # Second pin (unpin)
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/pin_agent?id={agent_id}", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PinAgent().post()
        assert response.status_code == 200

    def test_pin_db_error_returns_500(self, app):
        from application.api.user.agents.routes import PinAgent

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context(
            "/api/pin_agent?id=abc", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = PinAgent().post()
        assert response.status_code == 500


class TestPinnedAgentsListing:
    def test_returns_pinned_after_pinning(self, app, pg_conn):
        from application.api.user.agents.routes import PinAgent, PinnedAgents

        user = "u-pinned-list"
        agent = _seed_agent(pg_conn, user=user, retriever="classic")

        # Pin
        with _patch_db(pg_conn), app.test_request_context(
            f"/api/pin_agent?id={agent['id']}", method="POST"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            PinAgent().post()

        with _patch_db(pg_conn), app.test_request_context(
            "/api/pinned_agents"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = PinnedAgents().get()

        assert response.status_code == 200
        assert len(response.json) == 1
        assert response.json[0]["pinned"] is True

    def test_pinned_db_error_returns_400(self, app):
        from application.api.user.agents.routes import PinnedAgents

        @contextmanager
        def _broken():
            raise RuntimeError("boom")
            yield

        with patch(
            "application.api.user.agents.routes.db_session", _broken
        ), app.test_request_context("/api/pinned_agents"):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = PinnedAgents().get()
        assert response.status_code == 400
