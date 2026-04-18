"""Tests for application/api/user/agents/folders.py.

Uses the ephemeral ``pg_conn`` fixture to exercise real PG repository code.
"""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_folders_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch(
        "application.api.user.agents.folders.db_session", _yield
    ), patch(
        "application.api.user.agents.folders.db_readonly", _yield
    ):
        yield


def _seed_folder(pg_conn, user, name="F", parent_id=None):
    from application.storage.db.repositories.agent_folders import (
        AgentFoldersRepository,
    )
    return AgentFoldersRepository(pg_conn).create(user, name, parent_id=parent_id)


def _seed_agent(pg_conn, user, folder_id=None):
    from application.storage.db.repositories.agents import AgentsRepository
    repo = AgentsRepository(pg_conn)
    agent = repo.create(user, "test-agent", "published", description="x")
    if folder_id:
        repo.set_folder(str(agent["id"]), user, folder_id)
    return agent


class TestAgentFoldersGet:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context("/api/agents/folders/"):
            from flask import request
            request.decoded_token = None
            response = AgentFolders().get()
        assert response.status_code == 401

    def test_returns_folders_list(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolders

        user = "u-folders-list"
        _seed_folder(pg_conn, user, name="A")
        _seed_folder(pg_conn, user, name="B")

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolders().get()
        assert response.status_code == 200
        names = [f["name"] for f in response.json["folders"]]
        assert "A" in names and "B" in names


class TestAgentFoldersPost:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context(
            "/api/agents/folders/", method="POST", json={"name": "F"}
        ):
            from flask import request
            request.decoded_token = None
            response = AgentFolders().post()
        assert response.status_code == 401

    def test_returns_400_missing_name(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context(
            "/api/agents/folders/", method="POST", json={}
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentFolders().post()
        assert response.status_code == 400

    def test_creates_folder_at_root(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolders

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/", method="POST",
            json={"name": "Root Folder"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u-create"}
            response = AgentFolders().post()
        assert response.status_code == 201
        assert response.json["name"] == "Root Folder"
        assert response.json["parent_id"] is None

    def test_creates_nested_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolders

        user = "u-nested"
        parent = _seed_folder(pg_conn, user, name="parent")

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/", method="POST",
            json={"name": "child", "parent_id": str(parent["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolders().post()
        assert response.status_code == 201
        assert response.json["parent_id"] == str(parent["id"])

    def test_returns_404_for_missing_parent(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolders

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/", method="POST",
            json={
                "name": "child",
                "parent_id": "00000000-0000-0000-0000-000000000000",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentFolders().post()
        assert response.status_code == 404


class TestAgentFolderGet:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolder

        with app.test_request_context("/api/agents/folders/abc"):
            from flask import request
            request.decoded_token = None
            response = AgentFolder().get("abc")
        assert response.status_code == 401

    def test_returns_404_missing_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/00000000-0000-0000-0000-000000000000"
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentFolder().get(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_returns_folder_with_agents_and_subfolders(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-folder-detail"
        parent = _seed_folder(pg_conn, user, name="parent")
        _seed_folder(pg_conn, user, name="sub", parent_id=str(parent["id"]))
        _seed_agent(pg_conn, user, folder_id=str(parent["id"]))

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{parent['id']}"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().get(str(parent["id"]))
        assert response.status_code == 200
        data = response.json
        assert data["name"] == "parent"
        assert len(data["agents"]) == 1
        assert len(data["subfolders"]) == 1


class TestAgentFolderPut:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolder

        with app.test_request_context(
            "/api/agents/folders/abc", method="PUT", json={"name": "new"}
        ):
            from flask import request
            request.decoded_token = None
            response = AgentFolder().put("abc")
        assert response.status_code == 401

    def test_returns_404_missing_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/00000000-0000-0000-0000-000000000000",
            method="PUT",
            json={"name": "new"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentFolder().put(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_renames_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-rename"
        folder = _seed_folder(pg_conn, user, name="old")

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{folder['id']}",
            method="PUT",
            json={"name": "renamed"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().put(str(folder["id"]))
        assert response.status_code == 200

    def test_prevents_setting_self_as_parent(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-self-parent"
        folder = _seed_folder(pg_conn, user, name="f1")

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{folder['id']}",
            method="PUT",
            json={"parent_id": str(folder["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().put(str(folder["id"]))
        assert response.status_code == 400

    def test_sets_parent_to_other_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-moveparent"
        f1 = _seed_folder(pg_conn, user, name="f1")
        f2 = _seed_folder(pg_conn, user, name="f2")

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{f1['id']}",
            method="PUT",
            json={"parent_id": str(f2["id"])},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().put(str(f1["id"]))
        assert response.status_code == 200

    def test_returns_404_for_missing_parent(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-missingparent"
        folder = _seed_folder(pg_conn, user, name="f")

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{folder['id']}",
            method="PUT",
            json={"parent_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().put(str(folder["id"]))
        assert response.status_code == 404

    def test_clears_parent_id_when_null(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-clear"
        parent = _seed_folder(pg_conn, user, name="p")
        child = _seed_folder(
            pg_conn, user, name="c", parent_id=str(parent["id"])
        )

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{child['id']}",
            method="PUT",
            json={"parent_id": None},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().put(str(child["id"]))
        assert response.status_code == 200


class TestAgentFolderDelete:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolder

        with app.test_request_context(
            "/api/agents/folders/abc", method="DELETE"
        ):
            from flask import request
            request.decoded_token = None
            response = AgentFolder().delete("abc")
        assert response.status_code == 401

    def test_returns_404_missing_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/00000000-0000-0000-0000-000000000000",
            method="DELETE",
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = AgentFolder().delete(
                "00000000-0000-0000-0000-000000000000"
            )
        assert response.status_code == 404

    def test_deletes_folder(self, app, pg_conn):
        from application.api.user.agents.folders import AgentFolder

        user = "u-del"
        folder = _seed_folder(pg_conn, user, name="tbd")

        with _patch_folders_db(pg_conn), app.test_request_context(
            f"/api/agents/folders/{folder['id']}", method="DELETE"
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = AgentFolder().delete(str(folder["id"]))
        assert response.status_code == 200


class TestMoveAgentToFolder:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        with app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={"agent_id": "x"},
        ):
            from flask import request
            request.decoded_token = None
            response = MoveAgentToFolder().post()
        assert response.status_code == 401

    def test_returns_400_missing_agent_id(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        with app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MoveAgentToFolder().post()
        assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app, pg_conn):
        from application.api.user.agents.folders import MoveAgentToFolder

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={"agent_id": "00000000-0000-0000-0000-000000000000"},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = MoveAgentToFolder().post()
        assert response.status_code == 404

    def test_moves_agent_into_folder(self, app, pg_conn):
        from application.api.user.agents.folders import MoveAgentToFolder

        user = "u-move"
        folder = _seed_folder(pg_conn, user, name="target")
        agent = _seed_agent(pg_conn, user)

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={
                "agent_id": str(agent["id"]),
                "folder_id": str(folder["id"]),
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = MoveAgentToFolder().post()
        assert response.status_code == 200

    def test_returns_404_folder_not_found(self, app, pg_conn):
        from application.api.user.agents.folders import MoveAgentToFolder

        user = "u-move-nofolder"
        agent = _seed_agent(pg_conn, user)

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={
                "agent_id": str(agent["id"]),
                "folder_id": "00000000-0000-0000-0000-000000000000",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = MoveAgentToFolder().post()
        assert response.status_code == 404

    def test_removes_agent_from_folder(self, app, pg_conn):
        from application.api.user.agents.folders import MoveAgentToFolder

        user = "u-remove"
        folder = _seed_folder(pg_conn, user, name="target")
        agent = _seed_agent(pg_conn, user, folder_id=str(folder["id"]))

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={"agent_id": str(agent["id"]), "folder_id": None},
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = MoveAgentToFolder().post()
        assert response.status_code == 200


class TestBulkMoveAgents:
    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        with app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={"agent_ids": ["a"]},
        ):
            from flask import request
            request.decoded_token = None
            response = BulkMoveAgents().post()
        assert response.status_code == 401

    def test_returns_400_missing_agent_ids(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        with app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={},
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = BulkMoveAgents().post()
        assert response.status_code == 400

    def test_bulk_moves_agents(self, app, pg_conn):
        from application.api.user.agents.folders import BulkMoveAgents

        user = "u-bulk"
        folder = _seed_folder(pg_conn, user, name="dest")
        a1 = _seed_agent(pg_conn, user)
        a2 = _seed_agent(pg_conn, user)

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={
                "agent_ids": [str(a1["id"]), str(a2["id"])],
                "folder_id": str(folder["id"]),
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = BulkMoveAgents().post()
        assert response.status_code == 200

    def test_returns_404_when_folder_not_found(self, app, pg_conn):
        from application.api.user.agents.folders import BulkMoveAgents

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={
                "agent_ids": ["a"],
                "folder_id": "00000000-0000-0000-0000-000000000000",
            },
        ):
            from flask import request
            request.decoded_token = {"sub": "u"}
            response = BulkMoveAgents().post()
        assert response.status_code == 404

    def test_bulk_move_tolerates_missing_agents(self, app, pg_conn):
        from application.api.user.agents.folders import BulkMoveAgents

        user = "u-bulk-partial"
        folder = _seed_folder(pg_conn, user, name="f")
        a1 = _seed_agent(pg_conn, user)

        with _patch_folders_db(pg_conn), app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={
                "agent_ids": [
                    str(a1["id"]),
                    "00000000-0000-0000-0000-000000000000",
                ],
                "folder_id": str(folder["id"]),
            },
        ):
            from flask import request
            request.decoded_token = {"sub": user}
            response = BulkMoveAgents().post()
        assert response.status_code == 200
