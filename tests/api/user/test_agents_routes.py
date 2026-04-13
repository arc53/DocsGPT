"""Tests for application.api.user.agents.routes module."""

import uuid
from unittest.mock import Mock, patch

import pytest
from bson import DBRef, ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeWorkflowReference:

    def test_returns_none_for_none(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference(None) is None

    def test_extracts_id_from_dict(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference({"id": "abc123"})
        assert result == "abc123"

    def test_extracts_underscore_id_from_dict(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference({"_id": "abc123"})
        assert result == "abc123"

    def test_extracts_workflow_id_from_dict(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference({"workflow_id": "abc123"})
        assert result == "abc123"

    def test_returns_empty_string_for_blank_string(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference("   ") == ""

    def test_returns_plain_string_value(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        oid = str(ObjectId())
        assert normalize_workflow_reference(oid) == oid

    def test_parses_json_string_value(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference('"some_id"')
        assert result == "some_id"

    def test_parses_json_dict_value(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference('{"id": "xyz"}')
        assert result == "xyz"

    def test_returns_string_for_non_json_string(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference("plain_value") == "plain_value"

    def test_converts_non_string_non_dict_to_str(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference(42) == "42"

    def test_dict_priority_id_over_workflow_id(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference(
            {"id": "first", "_id": "second", "workflow_id": "third"}
        )
        assert result == "first"


@pytest.mark.unit
class TestValidateWorkflowAccess:

    def test_returns_none_when_not_required_and_empty(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        with app.app_context():
            wf_id, err = validate_workflow_access(None, "user1", required=False)
            assert wf_id is None
            assert err is None

    def test_returns_error_when_required_and_empty(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        with app.app_context():
            wf_id, err = validate_workflow_access(None, "user1", required=True)
            assert wf_id is None
            assert err is not None
            assert err.status_code == 400

    def test_returns_error_for_invalid_oid_format(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        with app.app_context():
            wf_id, err = validate_workflow_access("not-a-valid-oid", "user1")
            assert wf_id is None
            assert err.status_code == 400

    def test_returns_404_when_workflow_not_found(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None
        oid = str(ObjectId())

        with app.app_context():
            with patch(
                "application.api.user.agents.routes.workflows_collection", mock_wf_col
            ):
                wf_id, err = validate_workflow_access(oid, "user1")
                assert err.status_code == 404

    def test_returns_workflow_id_on_success(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": ObjectId(), "user": "user1"}
        oid = str(ObjectId())

        with app.app_context():
            with patch(
                "application.api.user.agents.routes.workflows_collection", mock_wf_col
            ):
                wf_id, err = validate_workflow_access(oid, "user1")
                assert wf_id == oid
                assert err is None


@pytest.mark.unit
class TestBuildAgentDocument:

    def test_builds_classic_agent(self):
        from application.api.user.agents.routes import build_agent_document

        data = {
            "name": "Test Agent",
            "description": "desc",
            "status": "draft",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
        }
        doc = build_agent_document(
            data, "user1", "key123", "classic", image_url="img.png"
        )
        assert doc["user"] == "user1"
        assert doc["name"] == "Test Agent"
        assert doc["image"] == "img.png"
        assert doc["agent_type"] == "classic"
        assert "createdAt" in doc
        assert "updatedAt" in doc

    def test_builds_workflow_agent(self):
        from application.api.user.agents.routes import build_agent_document

        data = {
            "name": "WF Agent",
            "status": "published",
            "workflow": "wf123",
            "folder_id": "folder1",
        }
        doc = build_agent_document(data, "user1", "key123", "workflow")
        assert doc["workflow"] == "wf123"
        assert doc["folder_id"] == "folder1"
        # Workflow agents should not have classic-specific fields
        assert "image" not in doc
        assert "source" not in doc

    def test_defaults_to_classic_for_unknown_type(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "Agent", "status": "draft"}
        doc = build_agent_document(data, "user1", "k", "unknown_type")
        assert doc["agent_type"] == "classic"

    def test_defaults_to_classic_for_empty_type(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "Agent", "status": "draft"}
        doc = build_agent_document(data, "user1", "k", "")
        assert doc["agent_type"] == "classic"

    def test_limited_token_mode_string_true(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "A", "status": "draft", "limited_token_mode": "True"}
        doc = build_agent_document(data, "user1", "k", "classic")
        assert doc["limited_token_mode"] is True

    def test_limited_token_mode_string_false(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "A", "status": "draft", "limited_token_mode": "False"}
        doc = build_agent_document(data, "user1", "k", "classic")
        assert doc["limited_token_mode"] is False

    def test_limited_request_mode_bool(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "A", "status": "draft", "limited_request_mode": True}
        doc = build_agent_document(data, "user1", "k", "classic")
        assert doc["limited_request_mode"] is True

    def test_filters_to_allowed_fields(self):
        from application.api.user.agents.routes import build_agent_document

        data = {"name": "A", "status": "draft"}
        doc = build_agent_document(data, "user1", "k", "workflow")
        # Workflow doc should not have classic-only fields
        for classic_field in ["image", "source", "sources", "chunks", "retriever"]:
            assert classic_field not in doc

    def test_source_and_sources_passed_through(self):
        from application.api.user.agents.routes import build_agent_document

        source_ref = DBRef("sources", ObjectId())
        doc = build_agent_document(
            {"name": "A", "status": "draft"},
            "user1",
            "k",
            "classic",
            source_field=source_ref,
            sources_list=[source_ref],
        )
        assert doc["source"] == source_ref
        assert doc["sources"] == [source_ref]


# ---------------------------------------------------------------------------
# Route classes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import GetAgent

        with app.test_request_context("/api/get_agent?id=abc"):
            from flask import request

            request.decoded_token = None
            result = GetAgent().get()
            # Returns tuple (dict, status_code)
            assert result[1] == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import GetAgent

        with app.test_request_context("/api/get_agent"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            result = GetAgent().get()
            assert result[1] == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.routes import GetAgent

        agent_id = ObjectId()
        mock_col = Mock()
        mock_col.find_one.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/get_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                result = GetAgent().get()
                assert result[1] == 404

    def test_returns_agent_data_on_success(self, app):
        from application.api.user.agents.routes import GetAgent

        agent_id = ObjectId()
        key = str(uuid.uuid4())
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            "name": "Test Agent",
            "description": "desc",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
            "tools": [],
            "agent_type": "classic",
            "status": "published",
            "key": key,
        }

        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.routes.db", mock_db
        ):
            with app.test_request_context(f"/api/get_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgent().get()
                assert response.status_code == 200
                data = response.json
                assert data["id"] == str(agent_id)
                assert data["name"] == "Test Agent"
                assert data["key"].startswith(key[:4])

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import GetAgent

        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/get_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                result = GetAgent().get()
                assert result[1] == 400


@pytest.mark.unit
class TestGetAgents:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import GetAgents

        with app.test_request_context("/api/get_agents"):
            from flask import request

            request.decoded_token = None
            result = GetAgents().get()
            assert result[1] == 401

    def test_returns_agents_list(self, app):
        from application.api.user.agents.routes import GetAgents

        agent_id = ObjectId()
        key = str(uuid.uuid4())
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = [
            {
                "_id": agent_id,
                "user": "user1",
                "name": "Agent1",
                "source": "default",
                "retriever": "classic",
                "key": key,
            }
        ]

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": [str(agent_id)]},
            }
        )
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.routes.db", mock_db
        ):
            with app.test_request_context("/api/get_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgents().get()
                assert response.status_code == 200
                data = response.json
                assert len(data) == 1
                assert data[0]["name"] == "Agent1"
                assert data[0]["pinned"] is True

    def test_filters_agents_without_source_or_retriever(self, app):
        from application.api.user.agents.routes import GetAgents

        mock_agents_col = Mock()
        # Agent without source/retriever and not workflow type -> filtered out
        mock_agents_col.find.return_value = [
            {
                "_id": ObjectId(),
                "user": "user1",
                "name": "BadAgent",
                "agent_type": "classic",
            }
        ]

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": []},
            }
        )
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.routes.db", mock_db
        ):
            with app.test_request_context("/api/get_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgents().get()
                assert response.status_code == 200
                assert len(response.json) == 0

    def test_includes_workflow_agent_without_source(self, app):
        from application.api.user.agents.routes import GetAgents

        agent_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = [
            {
                "_id": agent_id,
                "user": "user1",
                "name": "WFAgent",
                "agent_type": "workflow",
                "key": "abcd1234efgh",
            }
        ]

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": []},
            }
        )
        mock_resolve = Mock(return_value=[])
        mock_db = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.routes.db", mock_db
        ):
            with app.test_request_context("/api/get_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgents().get()
                assert response.status_code == 200
                assert len(response.json) == 1
                assert response.json[0]["name"] == "WFAgent"

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import GetAgents

        mock_ensure = Mock(side_effect=Exception("DB error"))

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ):
            with app.test_request_context("/api/get_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgents().get()
                assert response.status_code == 400


@pytest.mark.unit
class TestCreateAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={"name": "A"},
        ):
            from flask import request

            request.decoded_token = None
            result = CreateAgent().post()
            assert result[1] == 401

    def test_returns_400_invalid_status(self, app):
        from application.api.user.agents.routes import CreateAgent

        with app.test_request_context(
            "/api/create_agent",
            method="POST",
            json={"name": "A", "status": "invalid"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = CreateAgent().post()
            assert response.status_code == 400

    def test_creates_draft_agent_success(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)

        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Draft Agent",
                    "status": "draft",
                    "agent_type": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201
                data = response.json
                assert data["id"] == str(inserted_id)
                # Draft agents get empty key
                assert data["key"] == ""

    def test_creates_published_classic_agent(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("img.png", None))
        source_id = str(ObjectId())

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Published Agent",
                    "description": "A test agent",
                    "status": "published",
                    "agent_type": "classic",
                    "source": source_id,
                    "chunks": "5",
                    "retriever": "classic",
                    "prompt_id": "default",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201
                data = response.json
                assert data["id"] == str(inserted_id)
                # Published agents get a uuid key
                assert data["key"] != ""

    def test_published_classic_requires_source(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "No Source",
                    "description": "desc",
                    "status": "published",
                    "agent_type": "classic",
                    "chunks": "5",
                    "retriever": "classic",
                    "prompt_id": "default",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400

    def test_creates_workflow_agent(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        wf_id = str(ObjectId())
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": ObjectId(wf_id), "user": "user1"}

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "WF Agent",
                    "status": "published",
                    "agent_type": "workflow",
                    "workflow": wf_id,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_image_upload_failure(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=(None, Mock()))

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400

    def test_invalid_json_schema(self, app):
        from application.api.user.agents.routes import CreateAgent
        from application.core.json_schema_utils import JsonSchemaValidationError

        def raise_exc(val):
            raise JsonSchemaValidationError("is invalid")

        with patch(
            "application.api.user.agents.routes.normalize_json_schema_payload",
            side_effect=raise_exc,
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "json_schema": {"bad": True},
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400

    def test_folder_id_not_found(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=("", None))
        mock_folders = Mock()
        mock_folders.find_one.return_value = None
        folder_id = str(ObjectId())

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.agent_folders_collection", mock_folders
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                    "folder_id": folder_id,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 404

    def test_invalid_folder_id_format(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                    "folder_id": "not-valid",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400

    def test_form_data_with_json_fields(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                content_type="multipart/form-data",
                data={
                    "name": "FormAgent",
                    "status": "draft",
                    "agent_type": "classic",
                    "tools": '["tool1", "tool2"]',
                    "sources": '["src1"]',
                    "models": '["model1"]',
                    "json_schema": "null",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_form_data_invalid_json_tools(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                content_type="multipart/form-data",
                data={
                    "name": "FormAgent",
                    "status": "draft",
                    "agent_type": "classic",
                    "tools": "not-valid-json",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                # invalid json for tools falls back to []
                assert response.status_code == 201

    def test_create_with_sources_list(self, app):
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        src_id = str(ObjectId())
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "MultiSource",
                    "description": "desc",
                    "status": "published",
                    "agent_type": "classic",
                    "sources": [src_id, "default"],
                    "chunks": "5",
                    "retriever": "classic",
                    "prompt_id": "default",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_db_insert_failure(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_agents_col = Mock()
        mock_agents_col.insert_one.side_effect = Exception("insert error")
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400


@pytest.mark.unit
class TestUpdateAgent:

    def _make_existing_agent(self, agent_id=None):
        return {
            "_id": agent_id or ObjectId(),
            "user": "user1",
            "name": "Existing Agent",
            "description": "existing desc",
            "source": "default",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
            "status": "published",
            "agent_type": "classic",
            "key": str(uuid.uuid4()),
        }

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import UpdateAgent

        with app.test_request_context(
            "/api/update_agent/abc",
            method="PUT",
            json={"name": "A"},
        ):
            from flask import request

            request.decoded_token = None
            response = UpdateAgent().put("abc")
            assert response.status_code == 401

    def test_returns_400_invalid_agent_id(self, app):
        from application.api.user.agents.routes import UpdateAgent

        with app.test_request_context(
            "/api/update_agent/not-valid",
            method="PUT",
            json={"name": "A"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateAgent().put("not-valid")
            assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.find_one.return_value = None
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(agent_id)
                assert response.status_code == 404

    def test_updates_agent_name_success(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_repo = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        def _run_dual_write(_repo_cls, fn):
            fn(mock_repo)

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.dual_write",
            side_effect=_run_dual_write,
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                assert response.json["success"] is True
        mock_repo.update_by_legacy_id.assert_called_once_with(
            str(agent_id),
            "user1",
            {"name": "Updated Name"},
        )

    def test_returns_400_invalid_status(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "invalid_status"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_returns_400_negative_chunks(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"chunks": -1},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_returns_400_tools_not_list(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"tools": "not-a-list"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_returns_400_no_update_data(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"unknown_field": "value"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_limited_token_mode_without_limit(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"limited_token_mode": True},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_limited_request_mode_without_limit(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"limited_request_mode": True},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_token_limit_without_mode(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"token_limit": 1000},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_request_limit_without_mode(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"request_limit": 100},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_source_with_invalid_oid(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"source": "not-valid-oid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_sources_list_with_invalid_oid(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"sources": ["bad-id"]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_source_to_default(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"source": "default"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_empty_source_on_draft(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        existing["status"] = "draft"
        existing["key"] = ""
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"source": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_empty_source_on_published_fails(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        # Published agent with only "default" source
        existing["source"] = "default"
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"source": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_chunks_empty_defaults_to_2(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"chunks": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_args = mock_col.update_one.call_args[0][1]["$set"]
                assert call_args["chunks"] == "2"

    def test_update_invalid_chunks_value(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"chunks": "abc"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_matched_but_not_modified(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=0)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Same Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                assert "No changes detected" in response.json["message"]

    def test_update_matched_zero_returns_404(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=0, modified_count=0)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "New Name"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 404

    def test_publish_draft_generates_key(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        existing["status"] = "draft"
        existing["key"] = ""
        existing["source"] = "default"
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                assert "key" in response.json

    def test_publish_missing_required_fields(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "",
            "description": "",
            "source": "",
            "chunks": "",
            "retriever": "",
            "prompt_id": "",
            "status": "draft",
            "agent_type": "classic",
            "key": "",
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_db_update_exception(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.side_effect = Exception("DB error")
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 500

    def test_update_json_schema_valid(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        schema_val = {"type": "object", "properties": {"x": {"type": "string"}}}

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.normalize_json_schema_payload",
            return_value=schema_val,
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"json_schema": schema_val},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_json_schema_invalid(self, app):
        from application.api.user.agents.routes import UpdateAgent
        from application.core.json_schema_utils import JsonSchemaValidationError

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        def raise_exc(val):
            raise JsonSchemaValidationError("is invalid")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.normalize_json_schema_payload",
            side_effect=raise_exc,
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"json_schema": {"bad": True}},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_json_schema_none(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"json_schema": None},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_folder_id_valid(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        folder_id = str(ObjectId())
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))
        mock_folders = Mock()
        mock_folders.find_one.return_value = {"_id": ObjectId(folder_id), "user": "user1"}

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.agent_folders_collection", mock_folders
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"folder_id": folder_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_folder_id_invalid_format(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"folder_id": "invalid"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_folder_not_found(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        folder_id = str(ObjectId())
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))
        mock_folders = Mock()
        mock_folders.find_one.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.agent_folders_collection", mock_folders
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"folder_id": folder_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 404

    def test_update_folder_id_empty_sets_none(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"folder_id": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_args = mock_col.update_one.call_args[0][1]["$set"]
                assert call_args["folder_id"] is None

    def test_empty_name_field_rejected(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_workflow_field(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        wf_id = str(ObjectId())
        existing = self._make_existing_agent(agent_id)
        existing["agent_type"] = "workflow"
        existing["status"] = "draft"
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": ObjectId(wf_id), "user": "user1"}

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"workflow": wf_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_publish_workflow_without_workflow_field(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "WF Agent",
            "status": "draft",
            "agent_type": "workflow",
            "key": "",
            "workflow": None,
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_form_data_json_parse_error(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = str(ObjectId())
        existing = self._make_existing_agent(ObjectId(agent_id))
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={"tools": "not-valid-json"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(agent_id)
                assert response.status_code == 400

    def test_limited_token_mode_string_true(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={
                    "limited_token_mode": "True",
                    "token_limit": 5000,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_update_sources_with_default(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        src_id = str(ObjectId())
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"sources": ["default", src_id]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200


@pytest.mark.unit
class TestDeleteAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import DeleteAgent

        with app.test_request_context("/api/delete_agent"):
            from flask import request

            request.decoded_token = None
            response = DeleteAgent().delete()
            assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import DeleteAgent

        with app.test_request_context("/api/delete_agent"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = DeleteAgent().delete()
            assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.routes import DeleteAgent

        mock_col = Mock()
        mock_col.find_one_and_delete.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/delete_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 404

    def test_deletes_classic_agent_success(self, app):
        from application.api.user.agents.routes import DeleteAgent

        agent_id = ObjectId()
        mock_col = Mock()
        mock_repo = Mock()
        mock_col.find_one_and_delete.return_value = {
            "_id": agent_id,
            "user": "user1",
            "agent_type": "classic",
        }

        def _run_dual_write(_repo_cls, fn):
            fn(mock_repo)

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.dual_write",
            side_effect=_run_dual_write,
        ):
            with app.test_request_context(f"/api/delete_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 200
                assert response.json["id"] == str(agent_id)
        mock_repo.delete_by_legacy_id.assert_called_once_with(str(agent_id), "user1")

    def test_deletes_workflow_agent_cleans_up(self, app):
        from application.api.user.agents.routes import DeleteAgent

        agent_id = ObjectId()
        wf_id = str(ObjectId())
        mock_agents_col = Mock()
        mock_agents_col.find_one_and_delete.return_value = {
            "_id": agent_id,
            "user": "user1",
            "agent_type": "workflow",
            "workflow": wf_id,
        }
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": ObjectId(wf_id), "user": "user1"}
        mock_nodes_col = Mock()
        mock_edges_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.agents.routes.workflow_nodes_collection", mock_nodes_col
        ), patch(
            "application.api.user.agents.routes.workflow_edges_collection", mock_edges_col
        ):
            with app.test_request_context(f"/api/delete_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 200
                mock_nodes_col.delete_many.assert_called_once()
                mock_edges_col.delete_many.assert_called_once()
                mock_wf_col.delete_one.assert_called_once()

    def test_deletes_workflow_agent_non_owned_skips_cleanup(self, app):
        from application.api.user.agents.routes import DeleteAgent

        agent_id = ObjectId()
        wf_id = str(ObjectId())
        mock_agents_col = Mock()
        mock_agents_col.find_one_and_delete.return_value = {
            "_id": agent_id,
            "user": "user1",
            "agent_type": "workflow",
            "workflow": wf_id,
        }
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None  # Not owned
        mock_nodes_col = Mock()
        mock_edges_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.agents.routes.workflow_nodes_collection", mock_nodes_col
        ), patch(
            "application.api.user.agents.routes.workflow_edges_collection", mock_edges_col
        ):
            with app.test_request_context(f"/api/delete_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 200
                mock_nodes_col.delete_many.assert_not_called()

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import DeleteAgent

        mock_col = Mock()
        mock_col.find_one_and_delete.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/delete_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 400


@pytest.mark.unit
class TestPinnedAgents:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import PinnedAgents

        with app.test_request_context("/api/pinned_agents"):
            from flask import request

            request.decoded_token = None
            response = PinnedAgents().get()
            assert response.status_code == 401

    def test_returns_empty_when_no_pinned(self, app):
        from application.api.user.agents.routes import PinnedAgents

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": []},
            }
        )

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 200
                assert response.json == []

    def test_returns_pinned_agents(self, app):
        from application.api.user.agents.routes import PinnedAgents

        agent_id = ObjectId()
        key = str(uuid.uuid4())
        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": [str(agent_id)]},
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = [
            {
                "_id": agent_id,
                "name": "Pinned Agent",
                "source": "default",
                "retriever": "classic",
                "key": key,
            }
        ]
        mock_resolve = Mock(return_value=[])
        mock_users_col = Mock()
        mock_db = Mock()

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ), patch(
            "application.api.user.agents.routes.users_collection", mock_users_col
        ), patch(
            "application.api.user.agents.routes.db", mock_db
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 200
                data = response.json
                assert len(data) == 1
                assert data[0]["pinned"] is True

    def test_cleans_up_stale_pinned_ids(self, app):
        from application.api.user.agents.routes import PinnedAgents

        stale_id = str(ObjectId())
        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": [stale_id]},
            }
        )
        mock_agents_col = Mock()
        mock_agents_col.find.return_value = []
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.users_collection", mock_users_col
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 200
                mock_users_col.update_one.assert_called_once()

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import PinnedAgents

        mock_ensure = Mock(side_effect=Exception("DB error"))

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 400


@pytest.mark.unit
class TestGetTemplateAgents:

    def test_returns_template_agents(self, app):
        from application.api.user.agents.routes import GetTemplateAgents

        agent_id = ObjectId()
        mock_col = Mock()
        mock_col.find.return_value = [
            {
                "_id": agent_id,
                "name": "Template1",
                "description": "A template",
                "image": "img.png",
            }
        ]

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context("/api/template_agents"):
                response = GetTemplateAgents().get()
                assert response.status_code == 200
                data = response.json
                assert len(data) == 1
                assert data[0]["name"] == "Template1"

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import GetTemplateAgents

        mock_col = Mock()
        mock_col.find.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context("/api/template_agents"):
                response = GetTemplateAgents().get()
                assert response.status_code == 400


@pytest.mark.unit
class TestAdoptAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import AdoptAgent

        with app.test_request_context("/api/adopt_agent?id=abc"):
            from flask import request

            request.decoded_token = None
            response = AdoptAgent().post()
            assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import AdoptAgent

        with app.test_request_context("/api/adopt_agent"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = AdoptAgent().post()
            assert response.status_code == 400

    def test_returns_404_template_not_found(self, app):
        from application.api.user.agents.routes import AdoptAgent

        mock_col = Mock()
        mock_col.find_one.return_value = None
        agent_id = str(ObjectId())

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/adopt_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AdoptAgent().post()
                assert response.status_code == 404

    def test_adopts_agent_success(self, app):
        from application.api.user.agents.routes import AdoptAgent

        agent_id = ObjectId()
        new_id = ObjectId()
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "system",
            "name": "Template Agent",
            "description": "A template",
            "source": "default",
            "tools": [],
        }
        mock_col.insert_one.return_value = Mock(inserted_id=new_id)
        mock_resolve = Mock(return_value=[])

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ):
            with app.test_request_context(f"/api/adopt_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AdoptAgent().post()
                assert response.status_code == 200
                data = response.json
                assert data["success"] is True
                assert data["agent"]["id"] == str(new_id)

    def test_returns_400_on_exception(self, app):
        from application.api.user.agents.routes import AdoptAgent

        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/adopt_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AdoptAgent().post()
                assert response.status_code == 400


@pytest.mark.unit
class TestPinAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import PinAgent

        with app.test_request_context("/api/pin_agent"):
            from flask import request

            request.decoded_token = None
            response = PinAgent().post()
            assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import PinAgent

        with app.test_request_context("/api/pin_agent"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = PinAgent().post()
            assert response.status_code == 400

    def test_returns_404_agent_not_found(self, app):
        from application.api.user.agents.routes import PinAgent

        mock_col = Mock()
        mock_col.find_one.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/pin_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinAgent().post()
                assert response.status_code == 404

    def test_pins_agent(self, app):
        from application.api.user.agents.routes import PinAgent

        agent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.find_one.return_value = {"_id": ObjectId(agent_id)}

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": []},
            }
        )
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.users_collection", mock_users_col
        ):
            with app.test_request_context(f"/api/pin_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinAgent().post()
                assert response.status_code == 200
                assert response.json["action"] == "pinned"

    def test_unpins_agent(self, app):
        from application.api.user.agents.routes import PinAgent

        agent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.find_one.return_value = {"_id": ObjectId(agent_id)}

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": [agent_id]},
            }
        )
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.users_collection", mock_users_col
        ):
            with app.test_request_context(f"/api/pin_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinAgent().post()
                assert response.status_code == 200
                assert response.json["action"] == "unpinned"

    def test_returns_500_on_exception(self, app):
        from application.api.user.agents.routes import PinAgent

        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(f"/api/pin_agent?id={ObjectId()}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinAgent().post()
                assert response.status_code == 500


@pytest.mark.unit
class TestRemoveSharedAgent:

    def test_returns_401_unauthenticated(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        with app.test_request_context("/api/remove_shared_agent"):
            from flask import request

            request.decoded_token = None
            response = RemoveSharedAgent().delete()
            assert response.status_code == 401

    def test_returns_400_missing_id(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        with app.test_request_context("/api/remove_shared_agent"):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = RemoveSharedAgent().delete()
            assert response.status_code == 400

    def test_returns_404_shared_agent_not_found(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        mock_col = Mock()
        mock_col.find_one.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(
                f"/api/remove_shared_agent?id={ObjectId()}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = RemoveSharedAgent().delete()
                assert response.status_code == 404

    def test_removes_shared_agent_success(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        agent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": ObjectId(agent_id),
            "shared_publicly": True,
        }

        mock_ensure = Mock(
            return_value={
                "user_id": "user1",
                "agent_preferences": {"pinned": [], "shared_with_me": [agent_id]},
            }
        )
        mock_users_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure
        ), patch(
            "application.api.user.agents.routes.users_collection", mock_users_col
        ):
            with app.test_request_context(
                f"/api/remove_shared_agent?id={agent_id}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = RemoveSharedAgent().delete()
                assert response.status_code == 200
                assert response.json["action"] == "removed"
                mock_users_col.update_one.assert_called_once()

    def test_returns_500_on_exception(self, app):
        from application.api.user.agents.routes import RemoveSharedAgent

        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context(
                f"/api/remove_shared_agent?id={ObjectId()}"
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = RemoveSharedAgent().delete()
                assert response.status_code == 500


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAgentFormDataEdgeCases:
    """Cover form-data JSON-parse fallback branches in CreateAgent."""

    def test_form_data_invalid_sources_json_falls_back(self, app):
        """Lines 474-475: invalid JSON for 'sources' falls back to []."""
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                content_type="multipart/form-data",
                data={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                    "sources": "not-valid-json",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_form_data_invalid_json_schema_falls_back(self, app):
        """Lines 479-480: invalid JSON for 'json_schema' falls back to None."""
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                content_type="multipart/form-data",
                data={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                    "json_schema": "{bad json",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_form_data_invalid_models_json_falls_back(self, app):
        """Lines 484-485: invalid JSON for 'models' falls back to []."""
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                content_type="multipart/form-data",
                data={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "classic",
                    "models": "not-json",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201

    def test_create_with_unknown_agent_type_defaults_classic(self, app):
        """Line 511-517: unknown agent_type not in AGENT_TYPE_SCHEMAS."""
        from application.api.user.agents.routes import CreateAgent

        inserted_id = ObjectId()
        mock_agents_col = Mock()
        mock_agents_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_agents_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Agent",
                    "status": "draft",
                    "agent_type": "totally_unknown",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201


@pytest.mark.unit
class TestUpdateAgentFormDataEdgeCases:
    """Cover form-data parsing and edge cases in UpdateAgent."""

    def _make_existing_agent(self, agent_id=None):
        return {
            "_id": agent_id or ObjectId(),
            "user": "user1",
            "name": "Existing Agent",
            "description": "existing desc",
            "source": "default",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
            "status": "published",
            "agent_type": "classic",
            "key": str(uuid.uuid4()),
        }

    def test_form_data_parses_json_fields(self, app):
        """Line 699: form.to_dict() branch in UpdateAgent."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={
                    "name": "Updated",
                    "tools": '["tool1"]',
                    "sources": '["default"]',
                    "models": '["m1"]',
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_form_data_invalid_json_sources_returns_400(self, app):
        """Lines 712-713: invalid JSON for sources in form data."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={"sources": "{bad json"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Invalid JSON format" in response.json["message"]

    def test_form_data_invalid_json_models_returns_400(self, app):
        """Lines 712-713: invalid JSON for models in form data."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={"models": "not-json{"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Invalid JSON format" in response.json["message"]

    def test_form_data_empty_json_schema_sets_none(self, app):
        """Line 715-716: empty json_schema string sets None."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={"json_schema": ""},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_find_agent_db_error(self, app):
        """Line 730: exception when finding agent in DB."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = str(ObjectId())
        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("DB connection lost")
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(agent_id)
                assert response.status_code == 500
                assert "Database error" in response.json["message"]

    def test_handle_image_upload_error_forwarded(self, app):
        """Line 746: image upload error is returned directly."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        error_response = Mock(status_code=400)
        mock_handle_img = Mock(return_value=(None, error_response))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                result = UpdateAgent().put(str(agent_id))
                assert result == error_response

    def test_limited_request_mode_string_true(self, app):
        """Lines 904-907: limited_request_mode as string 'True'."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={
                    "limited_request_mode": "True",
                    "request_limit": 100,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_publish_workflow_missing_workflow_id(self, app):
        """Line 1031: workflow_id is missing when publishing workflow."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "WF Agent",
            "status": "draft",
            "agent_type": "workflow",
            "key": "",
            "workflow": "",
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Workflow" in response.json["message"]

    def test_publish_workflow_invalid_workflow_id_format(self, app):
        """Line 1032-1033: workflow_id is present but not valid ObjectId."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "WF Agent",
            "status": "draft",
            "agent_type": "workflow",
            "key": "",
            "workflow": "not-an-objectid",
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_publish_workflow_workflow_not_found(self, app):
        """Lines 1035-1039: workflow exists but not found in DB."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        wf_id = str(ObjectId())
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "WF Agent",
            "status": "draft",
            "agent_type": "workflow",
            "key": "",
            "workflow": wf_id,
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Workflow access" in response.json["message"]

    def test_update_with_image_url_set(self, app):
        """Line 1000-1001: image_url is truthy, added to update_fields."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("new_img.png", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="multipart/form-data",
                data={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_publish_generates_key_in_response(self, app):
        """Line 1134-1136: newly_generated_key is included in response."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        existing["status"] = "draft"
        existing["key"] = ""
        existing["source"] = "default"
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                assert "key" in response.json
                assert len(response.json["key"]) > 0


@pytest.mark.unit
class TestDeleteAgentWorkflowEdgeCases:
    """Cover workflow cleanup edge cases in DeleteAgent."""

    def test_delete_workflow_invalid_workflow_id(self, app):
        """Lines 1179-1181: invalid workflow id skips cleanup."""
        from application.api.user.agents.routes import DeleteAgent

        agent_id = ObjectId()
        mock_col = Mock()
        mock_col.find_one_and_delete.return_value = {
            "_id": agent_id,
            "user": "user1",
            "agent_type": "workflow",
            "workflow": "not-a-valid-oid",
        }
        mock_wf_col = Mock()
        mock_nodes_col = Mock()
        mock_edges_col = Mock()

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.workflows_collection", mock_wf_col
        ), patch(
            "application.api.user.agents.routes.workflow_nodes_collection",
            mock_nodes_col,
        ), patch(
            "application.api.user.agents.routes.workflow_edges_collection",
            mock_edges_col,
        ):
            with app.test_request_context(f"/api/delete_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = DeleteAgent().delete()
                assert response.status_code == 200
                mock_nodes_col.delete_many.assert_not_called()
                mock_wf_col.delete_one.assert_not_called()


# ---------------------------------------------------------------------------
# Coverage — additional uncovered lines
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAgentEmptyAgentType:
    """Cover line 517: agent_type defaults to 'classic' when empty."""

    def test_empty_agent_type_defaults_to_classic(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_col = Mock()
        mock_col.insert_one.return_value = Mock(inserted_id=ObjectId())
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Test",
                    "status": "draft",
                    "agent_type": "",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201


@pytest.mark.unit
class TestUpdateAgentFormDataPath:
    """Cover lines 666, 699, 815-816, 859, 887, 948-951, 1073, 1108, 1136."""

    def _make_existing_agent(self, agent_id):
        return {
            "_id": agent_id,
            "user": "user1",
            "name": "Existing",
            "status": "draft",
            "agent_type": "classic",
            "key": "abcdefghijklmnop",
            "source": "default",
        }

    def test_form_data_parsing(self, app):
        """Cover line 699: form data parsing path."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                content_type="application/x-www-form-urlencoded",
                data={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_invalid_source_id_in_sources_list(self, app):
        """Cover lines 815-816: invalid source ID in sources list."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"sources": ["not-a-valid-oid"]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Invalid source ID" in response.json["message"]

    def test_tools_not_a_list(self, app):
        """Cover line 859: tools is not a list."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"tools": "not-a-list"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Tools must be a list" in response.json["message"]

    def test_limited_token_mode_string_true(self, app):
        """Cover line 887: limited_token_mode string 'True' converted."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"limited_token_mode": "True", "token_limit": 5000},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_request_limit_without_limited_mode(self, app):
        """Cover lines 948-951: request_limit without limited_request_mode."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={
                    "request_limit": 100,
                    "limited_request_mode": False,
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Request limit cannot be set" in response.json["message"]

    def test_folder_id_update(self, app):
        """Cover lines 950-951: folder_id field update."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))
        folder_oid = str(ObjectId())
        mock_folders_col = Mock()
        mock_folders_col.find_one.return_value = {"_id": ObjectId(folder_oid), "user": "user1"}

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.agent_folders_collection", mock_folders_col
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"folder_id": folder_oid},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200

    def test_publish_missing_source_returns_400(self, app):
        """Cover line 1073: published with source_val check."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "Agent",
            "description": "desc",
            "prompt_id": "default",
            "status": "draft",
            "agent_type": "classic",
            "key": "abcdefghijklmnop",
            "retriever": "classic",
            "chunks": 5,
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400

    def test_update_not_found_returns_404(self, app):
        """Cover line 1108: matched_count==0 returns 404."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=0, modified_count=0)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "Updated"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 404


@pytest.mark.unit
class TestGetPinnedAgents:
    """Cover lines 1253, 1262: pinned agents key masking and return."""

    def test_returns_pinned_agents_with_masked_key(self, app):
        from application.api.user.agents.routes import PinnedAgents

        agent_id = ObjectId()
        mock_col = Mock()
        mock_col.find.return_value = [
            {
                "_id": agent_id,
                "name": "Pinned",
                "description": "desc",
                "agent_type": "classic",
                "source": "default",
                "retriever": "classic",
                "status": "published",
                "key": "abcdefghijklmnop",
                "createdAt": "",
                "updatedAt": "",
                "lastUsedAt": "",
            }
        ]
        mock_ensure_user = Mock(
            return_value={"agent_preferences": {"pinned": [str(agent_id)]}}
        )
        mock_resolve_tools = Mock(return_value=[])

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure_user
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve_tools
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 200
                data = response.json
                assert len(data) == 1
                assert data[0]["key"] == "abcd...mnop"

    def test_returns_empty_for_no_pinned(self, app):
        from application.api.user.agents.routes import PinnedAgents

        mock_ensure_user = Mock(
            return_value={"agent_preferences": {"pinned": []}}
        )

        with patch(
            "application.api.user.agents.routes.ensure_user_doc", mock_ensure_user
        ):
            with app.test_request_context("/api/pinned_agents"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = PinnedAgents().get()
                assert response.status_code == 200
                assert response.json == []


@pytest.mark.unit
class TestGetTemplateAgentsErrorPath:
    """Cover line 1283: template agents error path."""

    def test_template_agents_error_returns_400(self, app):
        from application.api.user.agents.routes import GetTemplateAgents

        mock_col = Mock()
        mock_col.find.side_effect = Exception("DB error")

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ):
            with app.test_request_context("/api/template_agents"):
                response = GetTemplateAgents().get()
                assert response.status_code == 400


# ---------------------------------------------------------------------------
# Additional coverage for agents/routes.py
# Lines: 526 (workflow validation error), 666 (models field),
# 815-816 (invalid source id in list), 887 (limited_token_mode bool),
# 948-951 (request_limit without mode), 1073 (has_valid_source),
# 1253 (key masking), 1262 (return pinned agents)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAgentWorkflowError:
    """Cover lines 525-526: workflow validation returns error."""

    def test_workflow_validation_error_on_create(self, app):
        from application.api.user.agents.routes import CreateAgent

        mock_col = Mock()
        mock_col.insert_one.return_value = Mock(inserted_id=ObjectId())

        error_response = Mock()
        error_response.status_code = 400

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.validate_workflow_access",
            return_value=(None, error_response),
        ), patch(
            "application.api.user.agents.routes.handle_image_upload",
            return_value=("", None),
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "Test",
                    "agent_type": "workflow",
                    "status": "draft",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 400


@pytest.mark.unit
class TestUpdateAgentInvalidSourceInList:
    """Cover lines 815-816: invalid source ID in sources list."""

    def _make_existing_agent(self, agent_id):
        return {
            "_id": agent_id,
            "user": "user1",
            "name": "Test",
            "agent_type": "classic",
            "status": "draft",
        }

    def test_invalid_source_in_list(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"sources": ["not_valid_source_id!!!"]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Invalid source ID" in response.json["message"]


@pytest.mark.unit
class TestUpdateAgentModelsField:
    """Cover line 666: models list field in update."""

    def _make_existing_agent(self, agent_id):
        return {
            "_id": agent_id,
            "user": "user1",
            "name": "Test",
            "agent_type": "classic",
            "status": "draft",
        }

    def test_models_field_update(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"models": ["model-1", "model-2"]},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200


@pytest.mark.unit
class TestUpdateAgentHasValidSourceDefault:
    """Cover line 1073: has_valid_source with source == 'default'."""

    def _make_existing_agent(self, agent_id):
        return {
            "_id": agent_id,
            "user": "user1",
            "name": "Test",
            "agent_type": "classic",
            "status": "published",
            "description": "desc",
            "prompt_id": "default",
            "source": "default",
            "chunks": 2,
        }

    def test_has_valid_source_with_default(self, app):
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = self._make_existing_agent(agent_id)
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_col.update_one.return_value = Mock(matched_count=1, modified_count=1)
        mock_handle_img = Mock(return_value=("", None))

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"name": "UpdatedName"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
