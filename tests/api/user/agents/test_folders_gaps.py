"""Gap-filling tests for application.api.user.agents.folders.

These tests cover the uncovered lines not reached by tests/api/user/test_folders.py:
  - folders.py:50-51   exception in AgentFolders.get
  - folders.py:151     parent_id update path in AgentFolder.put
  - folders.py:159-160 exception in AgentFolder.put
  - folders.py:166     401 in AgentFolder.delete
  - folders.py:183-184 exception in AgentFolder.delete
  - folders.py:202     401 in MoveAgentToFolder.post
  - folders.py:219     folder not found in MoveAgentToFolder.post
  - folders.py:229-230 exception in MoveAgentToFolder.post
  - folders.py:248     401 in BulkMoveAgents.post
  - folders.py:275-276 exception in BulkMoveAgents.post
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
# AgentFolders.get – exception branch (lines 50-51)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFoldersGetException:

    def test_returns_400_on_exception(self, app):
        """Lines 50-51: DB exception in AgentFolders.get returns 400."""
        from application.api.user.agents.folders import AgentFolders

        mock_col = Mock()
        mock_col.find.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context("/api/agents/folders/", method="GET"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolders().get()

        assert response.status_code == 400
        assert response.json["success"] is False


# ---------------------------------------------------------------------------
# AgentFolder.put – parent_id update & exception (lines 151, 159-160)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFolderPutGaps:

    def test_updates_parent_id(self, app):
        """Line 151: parent_id field is included in the update."""
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())
        new_parent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.update_one.return_value = Mock(matched_count=1)

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}",
                method="PUT",
                json={"parent_id": new_parent_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().put(folder_id)

        assert response.status_code == 200
        call_set = mock_col.update_one.call_args[0][1]["$set"]
        assert call_set["parent_id"] == new_parent_id

    def test_returns_400_on_exception(self, app):
        """Lines 159-160: DB exception in AgentFolder.put returns 400."""
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())
        mock_col = Mock()
        mock_col.update_one.side_effect = Exception("DB write error")

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_col
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}",
                method="PUT",
                json={"name": "New Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().put(folder_id)

        assert response.status_code == 400
        assert response.json["success"] is False


# ---------------------------------------------------------------------------
# AgentFolder.delete – 401 & exception (lines 166, 183-184)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentFolderDeleteGaps:

    def test_returns_401_unauthenticated(self, app):
        """Line 166: unauthenticated request returns 401."""
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())

        with app.test_request_context(
            f"/api/agents/folders/{folder_id}", method="DELETE"
        ):
            from flask import request

            request.decoded_token = None
            response = AgentFolder().delete(folder_id)

        assert response.status_code == 401

    def test_returns_400_on_exception(self, app):
        """Lines 183-184: DB exception in AgentFolder.delete returns 400."""
        from application.api.user.agents.folders import AgentFolder

        folder_id = str(ObjectId())
        mock_folders = Mock()
        mock_folders.update_many.side_effect = Exception("DB error")
        mock_agents = Mock()

        with patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_folders
        ), patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ):
            with app.test_request_context(
                f"/api/agents/folders/{folder_id}", method="DELETE"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AgentFolder().delete(folder_id)

        assert response.status_code == 400
        assert response.json["success"] is False


# ---------------------------------------------------------------------------
# MoveAgentToFolder – 401, folder not found, exception (lines 202, 219, 229-230)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMoveAgentToFolderGaps:

    def test_returns_401_unauthenticated(self, app):
        """Line 202: unauthenticated request returns 401."""
        from application.api.user.agents.folders import MoveAgentToFolder

        with app.test_request_context(
            "/api/agents/folders/move_agent",
            method="POST",
            json={"agent_id": str(ObjectId())},
        ):
            from flask import request

            request.decoded_token = None
            response = MoveAgentToFolder().post()

        assert response.status_code == 401

    def test_returns_404_folder_not_found(self, app):
        """Line 219: target folder does not exist returns 404."""
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = ObjectId()
        folder_id = ObjectId()
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
                json={"agent_id": str(agent_id), "folder_id": str(folder_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 404

    def test_returns_400_on_exception(self, app):
        """Lines 229-230: DB exception in move returns 400."""
        from application.api.user.agents.folders import MoveAgentToFolder

        agent_id = ObjectId()
        mock_agents = Mock()
        mock_agents.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ):
            with app.test_request_context(
                "/api/agents/folders/move_agent",
                method="POST",
                json={"agent_id": str(agent_id)},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = MoveAgentToFolder().post()

        assert response.status_code == 400
        assert response.json["success"] is False


# ---------------------------------------------------------------------------
# BulkMoveAgents – 401 & exception (lines 248, 275-276)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBulkMoveAgentsGaps:

    def test_returns_401_unauthenticated(self, app):
        """Line 248: unauthenticated request returns 401."""
        from application.api.user.agents.folders import BulkMoveAgents

        with app.test_request_context(
            "/api/agents/folders/bulk_move",
            method="POST",
            json={"agent_ids": [str(ObjectId())]},
        ):
            from flask import request

            request.decoded_token = None
            response = BulkMoveAgents().post()

        assert response.status_code == 401

    def test_returns_400_on_exception(self, app):
        """Lines 275-276: DB exception in bulk move returns 400."""
        from application.api.user.agents.folders import BulkMoveAgents

        folder_id = str(ObjectId())
        agent_ids = [str(ObjectId())]
        mock_agents = Mock()
        mock_agents.update_many.side_effect = Exception("DB error")
        mock_folders = Mock()
        mock_folders.find_one.return_value = {"_id": ObjectId(folder_id)}

        with patch(
            "application.api.user.agents.folders.agents_collection", mock_agents
        ), patch(
            "application.api.user.agents.folders.agent_folders_collection", mock_folders
        ):
            with app.test_request_context(
                "/api/agents/folders/bulk_move",
                method="POST",
                json={"agent_ids": agent_ids, "folder_id": folder_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = BulkMoveAgents().post()

        assert response.status_code == 400
        assert response.json["success"] is False
