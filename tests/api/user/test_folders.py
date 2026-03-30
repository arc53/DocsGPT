import datetime
from unittest.mock import Mock, patch

import pytest
from bson import ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


@pytest.mark.unit
class TestAgentFoldersGet:

    def test_returns_folders(self, app):
        from application.api.user.agents.folders import AgentFolders

        now = datetime.datetime(2024, 6, 15, tzinfo=datetime.timezone.utc)
        folder_id = ObjectId()
        mock_collection = Mock()
        mock_collection.find.return_value = [
            {
                "_id": folder_id,
                "name": "My Folder",
                "parent_id": None,
                "created_at": now,
                "updated_at": now,
            }
        ]

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        assert response.status_code == 200
        folders = response.json["folders"]
        assert len(folders) == 1
        assert folders[0]["id"] == str(folder_id)
        assert folders[0]["name"] == "My Folder"

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context("/api/agents/folders/", method="GET"):
            from flask import request

            request.decoded_token = None
            response = AgentFolders().get()

        assert response.status_code == 401


@pytest.mark.unit
class TestAgentFoldersCreate:

    def test_creates_folder(self, app):
        from application.api.user.agents.folders import AgentFolders

        inserted_id = ObjectId()
        mock_collection = Mock()
        mock_collection.insert_one.return_value = Mock(inserted_id=inserted_id)

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/agents/folders/",
                method="POST",
                json={"name": "New Folder"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().post()

        assert response.status_code == 201
        assert response.json["id"] == str(inserted_id)
        assert response.json["name"] == "New Folder"

    def test_returns_400_missing_name(self, app):
        from application.api.user.agents.folders import AgentFolders

        with app.test_request_context(
            "/api/agents/folders/",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentFolders().post()

        assert response.status_code == 400

    def test_validates_parent_folder_exists(self, app):
        from application.api.user.agents.folders import AgentFolders

        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context(
                "/api/agents/folders/",
                method="POST",
                json={"name": "Sub", "parent_id": str(ObjectId())},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().post()

        assert response.status_code == 404


@pytest.mark.unit
class TestAgentFolderGet:

    def test_returns_folder_with_agents_and_subfolders(self, app):
        from application.api.user.agents.folders import AgentFolder

        folder_id = ObjectId()
        agent_id = ObjectId()
        subfolder_id = ObjectId()
        mock_folders = Mock()
        mock_folders.find_one.return_value = {
            "_id": folder_id,
            "name": "Folder",
            "parent_id": None,
        }
        mock_folders.find.return_value = [
            {"_id": subfolder_id, "name": "Subfolder"}
        ]
        mock_agents = Mock()
        mock_agents.find.return_value = [
            {"_id": agent_id, "name": "Agent 1", "description": "Desc"}
        ]

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ), patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}", method="GET"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().get(str(folder_id))

        assert response.status_code == 200
        assert response.json["name"] == "Folder"
        assert len(response.json["agents"]) == 1
        assert len(response.json["subfolders"]) == 1

    def test_returns_404_not_found(self, app):
        from application.api.user.agents.folders import AgentFolder

        mock_collection = Mock()
        mock_collection.find_one.return_value = None

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{ObjectId()}", method="GET"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().get(str(ObjectId()))

        assert response.status_code == 404


@pytest.mark.unit
class TestAgentFolderUpdate:

    def test_updates_folder_name(self, app):
        from application.api.user.agents.folders import AgentFolder

        folder_id = ObjectId()
        mock_collection = Mock()
        mock_collection.update_one.return_value = Mock(matched_count=1)

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}",
                method="PUT",
                json={"name": "Renamed"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().put(str(folder_id))

        assert response.status_code == 200
        assert response.json["success"] is True

    def test_prevents_self_parent(self, app):
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())

        with app.test_request_context(
            f"/api/agents/folders/{folder_id}",
            method="PUT",
            json={"parent_id": folder_id},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AgentFolder().put(folder_id)

        assert response.status_code == 400
        assert "own parent" in response.json["message"]

    def test_returns_404_when_not_found(self, app):
        from application.api.user.agents.folders import AgentFolder

        mock_collection = Mock()
        mock_collection.update_one.return_value = Mock(matched_count=0)

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_collection,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{ObjectId()}",
                method="PUT",
                json={"name": "X"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().put(str(ObjectId()))

        assert response.status_code == 404


@pytest.mark.unit
class TestAgentFolderDelete:

    def test_deletes_folder_and_unsets_references(self, app):
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())
        mock_folders = Mock()
        mock_folders.delete_one.return_value = Mock(deleted_count=1)
        mock_agents = Mock()

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ), patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}", method="DELETE"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().delete(folder_id)

        assert response.status_code == 200
        mock_agents.update_many.assert_called_once()
        mock_folders.update_many.assert_called_once()
        mock_folders.delete_one.assert_called_once()

    def test_returns_404_not_found(self, app):
        from application.api.user.agents.folders import AgentFolder

        mock_folders = Mock()
        mock_folders.delete_one.return_value = Mock(deleted_count=0)
        mock_agents = Mock()

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ), patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                f"/api/agents/folders/{ObjectId()}", method="DELETE"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().delete(str(ObjectId()))

        assert response.status_code == 404


@pytest.mark.unit
class TestMoveAgentToFolder:

    def test_moves_agent_to_folder(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = ObjectId()
        folder_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"_id": agent_id, "user": "user1"}
        mock_folders = Mock()
        mock_folders.find_one.return_value = {"_id": folder_id}

        with patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={
                    "agent_id": str(agent_id),
                    "folder_id": str(folder_id),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 200
        mock_agents.update_one.assert_called_once()

    def test_removes_agent_from_folder(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.return_value = {"_id": agent_id, "user": "user1"}

        with patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={"agent_id": str(agent_id), "folder_id": None},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 200
        call_args = mock_agents.update_one.call_args
        assert "$unset" in call_args[0][1]

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        mock_agents = Mock()
        mock_agents.find_one.return_value = None

        with patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={"agent_id": str(ObjectId())},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 404

    def test_returns_400_missing_agent_id(self, app):
        from application.api.user.agents.folders import MoveAgentToFolder

        with app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = MoveAgentToFolder().post()

        assert response.status_code == 400


@pytest.mark.unit
class TestBulkMoveAgents:

    def test_bulk_moves_to_folder(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        folder_id = ObjectId()
        agent_ids = [str(ObjectId()), str(ObjectId())]
        mock_agents = Mock()
        mock_folders = Mock()
        mock_folders.find_one.return_value = {"_id": folder_id}

        with patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ), patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ):
            with app.test_request_context(
                "/api/agents/folders/bulk_move",
                method="POST",
                json={"agent_ids": agent_ids, "folder_id": str(folder_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = BulkMoveAgents().post()

        assert response.status_code == 200
        mock_agents.update_many.assert_called_once()

    def test_bulk_removes_from_folders(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        agent_ids = [str(ObjectId())]
        mock_agents = Mock()

        with patch(
            "application.api.user.agents.folders.agents_collection",
            mock_agents,
        ):
            with app.test_request_context(
                "/api/agents/folders/bulk_move",
                method="POST",
                json={"agent_ids": agent_ids},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = BulkMoveAgents().post()

        assert response.status_code == 200
        call_args = mock_agents.update_many.call_args
        assert "$unset" in call_args[0][1]

    def test_returns_400_missing_agent_ids(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        with app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = BulkMoveAgents().post()

        assert response.status_code == 400

    def test_returns_404_folder_not_found(self, app):
        from application.api.user.agents.folders import BulkMoveAgents

        mock_folders = Mock()
        mock_folders.find_one.return_value = None

        with patch(
            "application.api.user.agents.folders.agent_folders_collection",
            mock_folders,
        ):
            with app.test_request_context(
                "/api/agents/folders/bulk_move",
                method="POST",
                json={
                    "agent_ids": [str(ObjectId())],
                    "folder_id": str(ObjectId()),
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = BulkMoveAgents().post()

        assert response.status_code == 404
