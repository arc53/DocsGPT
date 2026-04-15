"""Gap-coverage tests for application.api.user.agents.folders.

No bson/ObjectId imports. Mongo collections are replaced by Mock objects;
the repository (AgentFoldersRepository) is patched for dual-write paths.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


def _fake_oid():
    """24-character hex string that substitutes for a Mongo ObjectId string."""
    return uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# AgentFolders.get — list user folders
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFoldersGetGaps:

    def test_returns_empty_list_when_no_folders(self, app):
        from application.api.user.agents.folders import AgentFolders

        mock_col = Mock()
        mock_col.find.return_value = []

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        assert response.status_code == 200
        assert response.json["folders"] == []

    def test_returns_folder_timestamps_as_isoformat(self, app):
        from application.api.user.agents.folders import AgentFolders
        import datetime

        now = datetime.datetime(2024, 3, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        fid = _fake_oid()
        mock_col = Mock()
        mock_col.find.return_value = [
            {
                "_id": fid,
                "name": "Timestamped",
                "parent_id": None,
                "created_at": now,
                "updated_at": now,
            }
        ]

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        assert response.status_code == 200
        folder = response.json["folders"][0]
        assert folder["created_at"] == now.isoformat()
        assert folder["updated_at"] == now.isoformat()

    def test_returns_folder_without_timestamps(self, app):
        """Folders without created_at/updated_at return None for those fields."""
        from application.api.user.agents.folders import AgentFolders

        fid = _fake_oid()
        mock_col = Mock()
        mock_col.find.return_value = [{"_id": fid, "name": "NoTime"}]

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        assert response.status_code == 200
        folder = response.json["folders"][0]
        assert folder["created_at"] is None
        assert folder["updated_at"] is None

    def test_returns_500_on_db_exception(self, app):
        from application.api.user.agents.folders import AgentFolders

        mock_col = Mock()
        mock_col.find.side_effect = Exception("connection error")

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        # _folder_error_response returns 400
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# AgentFolders.post — create folder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFoldersPostGaps:

    def test_creates_folder_without_parent(self, app):
        from application.api.user.agents.folders import AgentFolders

        inserted_id = _fake_oid()
        mock_col = Mock()
        mock_col.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ), patch(
            "application.api.user.agents.folders.dual_write",
            lambda *a, **kw: None,
        ):
            with app.test_request_context(
                "/api/agents/folders/",
                method="POST",
                json={"name": "Root Folder"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().post()

        assert response.status_code == 201
        assert response.json["name"] == "Root Folder"

    def test_rejects_missing_name_field(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context(
            "/api/agents/folders/", method="POST", json={"other": "data"}
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentFolders().post()

        assert response.status_code == 400

    def test_rejects_empty_name_string(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context(
            "/api/agents/folders/", method="POST", json={"name": ""}
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentFolders().post()

        assert response.status_code == 400

    def test_insert_exception_returns_400(self, app):
        from application.api.user.agents.folders import AgentFolders

        mock_col = Mock()
        mock_col.find_one.return_value = None
        mock_col.insert_one.side_effect = Exception("write error")

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context(
                "/api/agents/folders/", method="POST", json={"name": "Fail Folder"}
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().post()

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# AgentFolder.get — retrieve single folder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFolderGetGaps:

    def test_returns_folder_with_empty_agents_list(self, app):
        from application.api.user.agents.folders import AgentFolder

        fid = _fake_oid()
        mock_folders = Mock()
        mock_folders.find_one.return_value = {"_id": fid, "name": "Empty", "parent_id": None}
        mock_folders.find.return_value = []
        mock_agents = Mock()
        mock_agents.find.return_value = []

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_folders
        ), patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ):
            with app.test_request_context(f"/api/agents/folders/{fid}", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().get(fid)

        assert response.status_code == 200
        assert response.json["agents"] == []
        assert response.json["subfolders"] == []


# ---------------------------------------------------------------------------
# AgentFolder.put — update folder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFolderPutGaps:

    def test_prevents_self_parent_assignment(self, app):
        from application.api.user.agents.folders import AgentFolder

        fid = _fake_oid()
        with app.test_request_context(
            f"/api/agents/folders/{fid}",
            method="PUT",
            json={"parent_id": fid},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentFolder().put(fid)

        assert response.status_code == 400
        assert "parent" in response.json["message"].lower()

    def test_update_exception_returns_400(self, app):
        from application.api.user.agents.folders import AgentFolder

        fid = _fake_oid()
        mock_col = Mock()
        mock_col.update_one.side_effect = Exception("db gone")

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context(
                f"/api/agents/folders/{fid}",
                method="PUT",
                json={"name": "New Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().put(fid)

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# AgentFolder.delete — delete folder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFolderDeleteGaps:

    def test_successful_delete_returns_200(self, app):
        from application.api.user.agents.folders import AgentFolder

        fid = _fake_oid()
        mock_col = Mock()
        mock_col.delete_one.return_value = Mock(deleted_count=1)
        mock_col.update_many.return_value = Mock()
        mock_col.update_one.return_value = Mock()
        mock_agents = Mock()
        mock_agents.update_many.return_value = Mock()

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ), patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ), patch(
            "application.api.user.agents.folders.dual_write", lambda *a, **kw: None
        ):
            with app.test_request_context(
                f"/api/agents/folders/{fid}", method="DELETE"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().delete(fid)

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_delete_returns_404_when_not_found(self, app):
        from application.api.user.agents.folders import AgentFolder

        fid = _fake_oid()
        mock_col = Mock()
        mock_col.delete_one.return_value = Mock(deleted_count=0)
        mock_col.update_many.return_value = Mock()
        mock_agents = Mock()
        mock_agents.update_many.return_value = Mock()

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ), patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ), patch(
            "application.api.user.agents.folders.dual_write", lambda *a, **kw: None
        ):
            with app.test_request_context(
                f"/api/agents/folders/{fid}", method="DELETE"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().delete(fid)

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# MoveAgentToFolder — move agent into / out of folder
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMoveAgentToFolderGaps:

    def test_remove_agent_from_folder_when_folder_id_none(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = _fake_oid()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"_id": agent_id, "user": "user1"}

        with patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={"agent_id": agent_id, "folder_id": None},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 200
        # $unset path should have been called
        mock_agents.update_one.assert_called_once()

    def test_returns_404_when_target_folder_missing(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = _fake_oid()
        folder_id = _fake_oid()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"_id": agent_id, "user": "user1"}
        mock_folders = Mock()
        mock_folders.find_one.return_value = None

        with patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ), patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_folders
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={"agent_id": agent_id, "folder_id": folder_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# BulkMoveAgents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBulkMoveAgentsGaps:

    def test_bulk_move_no_folder_id_clears_folder(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        ids = [_fake_oid(), _fake_oid()]
        mock_agents = Mock()

        with patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ):
            with app.test_request_context(
                "/api/agents/folders/bulk_move",
                method="POST",
                json={"agent_ids": ids},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = BulkMoveAgents().post()

        assert response.status_code == 200
        # Should call update_many with $unset
        mock_agents.update_many.assert_called_once()
