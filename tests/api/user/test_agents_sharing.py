"""Tests for application.api.user.agents.sharing module."""

import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask

pytestmark = pytest.mark.skip(
    reason="Asserts Mongo-era agents_collection call shapes; needs PG repository-based rewrite. "
    "Tracked as migration debt."
)


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# SharedAgent (GET /shared_agent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSharedAgent:

    def test_returns_400_missing_token(self, app):
        from application.api.user.agents.sharing import SharedAgent

        with app.test_request_context("/api/shared_agent"):
            response = SharedAgent().get()
            assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.sharing import SharedAgent

        mock_col = Mock()
        mock_col.find_one.return_value = None

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context("/api/shared_agent?token=abc123"):
                response = SharedAgent().get()
                assert response.status_code == 404

    def test_returns_shared_agent_data(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Shared Agent",
            "description": "A shared agent",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
            "tools": [],
            "agent_type": "classic",
            "status": "published",
            "shared_publicly": True,
            "shared_token": "abc123",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ):
            with app.test_request_context("/api/shared_agent?token=abc123"):
                from flask import request

                # No decoded_token -> anonymous access
                request.decoded_token = None
                response = SharedAgent().get()
                assert response.status_code == 200
                data = response.json
                assert data["id"] == str(agent_id)
                assert data["name"] == "Shared Agent"
                assert data["shared"] is True

    def test_adds_to_shared_with_me_for_different_user(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "tools": [],
            "shared_publicly": True,
            "shared_token": "abc123",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()
        mock_ensure = Mock(return_value={"user_id": "user2"})
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ), patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.users_collection", mock_users_col
        ):
            with app.test_request_context("/api/shared_agent?token=abc123"):
                from flask import request

                request.decoded_token = {"sub": "user2"}
                response = SharedAgent().get()
                assert response.status_code == 200
                mock_ensure.assert_called_once_with("user2")
                mock_users_col.update_one.assert_called_once()

    def test_does_not_add_to_shared_for_owner(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "tools": [],
            "shared_publicly": True,
            "shared_token": "abc123",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()
        mock_ensure = Mock()
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ), patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.users_collection", mock_users_col
        ):
            with app.test_request_context("/api/shared_agent?token=abc123"):
                from flask import request

                request.decoded_token = {"sub": "owner1"}
                response = SharedAgent().get()
                assert response.status_code == 200
                mock_ensure.assert_not_called()
                mock_users_col.update_one.assert_not_called()

    def test_enriches_tool_names(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        tool_id = str(uuid.uuid4().hex)
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "tools": [tool_id],
            "shared_publicly": True,
            "shared_token": "tok",
        }
        mock_tools_col = Mock()
        mock_tools_col.find_one.return_value = {
            "_id": tool_id,
            "name": "calculator",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.user_tools_collection", mock_tools_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ):
            with app.test_request_context("/api/shared_agent?token=tok"):
                from flask import request

                request.decoded_token = None
                response = SharedAgent().get()
                assert response.status_code == 200
                assert response.json["tools"] == ["calculator"]

    def test_handles_source_dbref(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        source_id = uuid.uuid4().hex
        source_ref = uuid.uuid4().hex  # TODO: was DBRef("sources", source_id)
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "source": source_ref,
            "tools": [],
            "shared_publicly": True,
            "shared_token": "tok",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()
        mock_db.dereference.return_value = {"_id": source_id}

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ):
            with app.test_request_context("/api/shared_agent?token=tok"):
                from flask import request

                request.decoded_token = None
                response = SharedAgent().get()
                assert response.status_code == 200
                assert response.json["source"] == str(source_id)

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.sharing import SharedAgent

        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context("/api/shared_agent?token=tok"):
                response = SharedAgent().get()
                assert response.status_code == 400

    def test_tool_enrichment_handles_missing_tool(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        tool_id = str(uuid.uuid4().hex)
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "tools": [tool_id],
            "shared_publicly": True,
            "shared_token": "tok",
        }
        mock_tools_col = Mock()
        mock_tools_col.find_one.return_value = None
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.user_tools_collection", mock_tools_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ):
            with app.test_request_context("/api/shared_agent?token=tok"):
                from flask import request

                request.decoded_token = None
                response = SharedAgent().get()
                assert response.status_code == 200
                # Missing tools are skipped
                assert response.json["tools"] == []

    def test_image_url_generated_when_present(self, app):
        from application.api.user.agents.sharing import SharedAgent

        agent_id = uuid.uuid4().hex
        mock_agents_col = Mock()
        mock_agents_col.find_one.return_value = {
            "_id": agent_id,
            "user": "owner1",
            "name": "Agent",
            "image": "path/to/img.png",
            "tools": [],
            "shared_publicly": True,
            "shared_token": "tok",
        }
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()
        mock_generate = Mock(return_value="http://example.com/img.png")

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.db", mock_db
        ), patch(
            "application.api.user.agents.sharing.generate_image_url", mock_generate
        ):
            with app.test_request_context("/api/shared_agent?token=tok"):
                from flask import request

                request.decoded_token = None
                response = SharedAgent().get()
                assert response.status_code == 200
                assert response.json["image"] == "http://example.com/img.png"
                mock_generate.assert_called_once_with("path/to/img.png")


# ---------------------------------------------------------------------------
# SharedAgents (GET /shared_agents)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSharedAgents:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.sharing import SharedAgents

        with app.test_request_context("/api/shared_agents"):
            from flask import request

            request.decoded_token = None
            response = SharedAgents().get()
            assert response.status_code == 401

    def test_returns_shared_agents_list(self, app):
        from application.api.user.agents.sharing import SharedAgents

        agent_id = uuid.uuid4().hex
        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {
                    "shared_with_me": [str(agent_id)],
                    "pinned": [str(agent_id)],
                },
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = [
            {
                "_id": agent_id,
                "name": "Shared Agent",
                "description": "desc",
                "tools": [],
                "agent_type": "classic",
                "status": "published",
                "shared_publicly": True,
                "shared_token": "tok123",
            }
        ]
        mock_resolve = Mock(return_value=[])
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.users_collection", mock_users_col
        ):
            with app.test_request_context("/api/shared_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SharedAgents().get()
                assert response.status_code == 200
                data = response.json
                assert len(data) == 1
                assert data[0]["name"] == "Shared Agent"
                assert data[0]["pinned"] is True

    def test_removes_stale_shared_ids(self, app):
        from application.api.user.agents.sharing import SharedAgents

        stale_id = str(uuid.uuid4().hex)
        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {
                    "shared_with_me": [stale_id],
                    "pinned": [],
                },
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = []  # None found
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.users_collection", mock_users_col
        ):
            with app.test_request_context("/api/shared_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SharedAgents().get()
                assert response.status_code == 200
                mock_users_col.update_one.assert_called_once()
                call_args = mock_users_col.update_one.call_args
                assert stale_id in call_args[0][1]["$pullAll"][
                    "agent_preferences.shared_with_me"
                ]

    def test_returns_empty_when_no_shared_ids(self, app):
        from application.api.user.agents.sharing import SharedAgents

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"shared_with_me": [], "pinned": []},
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = []

        with patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ):
            with app.test_request_context("/api/shared_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SharedAgents().get()
                assert response.status_code == 200
                assert response.json == []

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.sharing import SharedAgents

        mock_ensure = Mock(side_effect=Exception("DB error"))

        with patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ):
            with app.test_request_context("/api/shared_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SharedAgents().get()
                assert response.status_code == 400

    def test_image_url_generated(self, app):
        from application.api.user.agents.sharing import SharedAgents

        agent_id = uuid.uuid4().hex
        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {
                    "shared_with_me": [str(agent_id)],
                    "pinned": [],
                },
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = [
            {
                "_id": agent_id,
                "name": "Agent",
                "image": "path.png",
                "tools": [],
                "shared_publicly": True,
            }
        ]
        mock_resolve = Mock(return_value=[])
        mock_generate = Mock(return_value="http://example.com/path.png")

        with patch(
            "application.api.user.agents.sharing.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.sharing.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.sharing.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.sharing.generate_image_url", mock_generate
        ), patch(
            "application.api.user.agents.sharing.users_collection", Mock()
        ):
            with app.test_request_context("/api/shared_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = SharedAgents().get()
                assert response.status_code == 200
                assert response.json[0]["image"] == "http://example.com/path.png"


# ---------------------------------------------------------------------------
# ShareAgent (PUT /share_agent)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShareAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": "abc", "shared": True},
        ):
            from flask import request

            request.decoded_token = None
            response = ShareAgent().put()
            assert response.status_code == 401

    def test_returns_400_missing_json_body(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent",
            method="PUT",
            content_type="application/json",
            data=b"{}",
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            # Empty JSON object -> no id, no shared -> 400
            response = ShareAgent().put()
            assert response.status_code == 400
            assert response.json["success"] is False

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"shared": True},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ShareAgent().put()
            assert response.status_code == 400

    def test_returns_400_missing_shared_param(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": str(uuid.uuid4().hex)},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ShareAgent().put()
            assert response.status_code == 400

    def test_returns_400_invalid_agent_id(self, app):
        from application.api.user.agents.sharing import ShareAgent

        with app.test_request_context(
            "/api/share_agent",
            method="PUT",
            json={"id": "invalid-oid", "shared": True},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = ShareAgent().put()
            assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.sharing import ShareAgent

        mock_col = Mock()
        mock_col.find_one.return_value = None
        agent_id = str(uuid.uuid4().hex)

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={"id": agent_id, "shared": True},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 404

    def test_shares_agent_success(self, app):
        from application.api.user.agents.sharing import ShareAgent

        agent_id = uuid.uuid4().hex
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
        }
        mock_col.update_one.return_value = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={
                    "id": str(agent_id),
                    "shared": True,
                    "username": "TestUser",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 200
                data = response.json
                assert data["success"] is True
                assert data["shared_token"] is not None
                mock_col.update_one.assert_called_once()

    def test_unshares_agent_success(self, app):
        from application.api.user.agents.sharing import ShareAgent

        agent_id = uuid.uuid4().hex
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
        }
        mock_col.update_one.return_value = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={
                    "id": str(agent_id),
                    "shared": False,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 200
                data = response.json
                assert data["success"] is True
                assert data["shared_token"] is None

    def test_returns_400_on_db_exception(self, app):
        from application.api.user.agents.sharing import ShareAgent

        agent_id = uuid.uuid4().hex
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
        }
        mock_col.update_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={
                    "id": str(agent_id),
                    "shared": True,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 400

    def test_share_with_username(self, app):
        from application.api.user.agents.sharing import ShareAgent

        agent_id = uuid.uuid4().hex
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
        }
        mock_col.update_one.return_value = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={
                    "id": str(agent_id),
                    "shared": True,
                    "username": "SharedByUser",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 200
                # Verify the update call includes shared_metadata with username
                update_call = mock_col.update_one.call_args[0][1]["$set"]
                assert update_call["shared_metadata"]["shared_by"] == "SharedByUser"
                assert update_call["shared_publicly"] is True
                assert "shared_token" in update_call

    def test_shared_false_explicitly(self, app):
        from application.api.user.agents.sharing import ShareAgent

        agent_id = uuid.uuid4().hex
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
        }
        mock_col.update_one.return_value = Mock()

        with patch(
            "application.api.user.agents.sharing.agents_collection", mock_col
        ):
            with app.test_request_context(
                "/api/share_agent",
                method="PUT",
                json={
                    "id": str(agent_id),
                    "shared": False,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = ShareAgent().put()
                assert response.status_code == 200
                update_call = mock_col.update_one.call_args[0][1]
                assert update_call["$set"]["shared_publicly"] is False
                assert update_call["$set"]["shared_token"] is None
