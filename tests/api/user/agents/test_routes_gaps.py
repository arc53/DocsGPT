"""Gap-filling tests for application.api.user.agents.routes.

These tests cover the lines not reached by tests/api/user/test_agents_routes.py:
  - routes.py:602,604  check/validate_required_fields early-return paths
  - routes.py:638      source="default" branch in create_agent
  - routes.py:783-787  exception during form-data parsing in update_agent
  - routes.py:858      valid OID source sets DBRef in update_agent
  - routes.py:892      empty sources list sets [] in update_agent
  - routes.py:910      valid positive chunks sets str(int)
  - routes.py:1051     workflow validation error path in update_agent
  - routes.py:1054-55  allow_system_prompt_override as string "True"
  - routes.py:1101     missing workflow agent name when publishing
  - routes.py:1406     DBRef source serialised in adopt_agent
"""

from unittest.mock import Mock, patch

import pytest
from bson import DBRef, ObjectId
from flask import Flask


@pytest.fixture
def app():
    app = Flask(__name__)
    return app


# ---------------------------------------------------------------------------
# CreateAgent – missing/invalid required-field paths (lines 602, 604, 638)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCreateAgentRequiredFieldPaths:

    def test_returns_400_missing_required_field_for_published(self, app):
        """Line 602: check_required_fields returns a response when fields are absent."""
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=("", None))
        source_id = str(ObjectId())

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    # "name" is missing → check_required_fields catches it
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
                assert response.status_code == 400
                assert "Missing" in response.json.get("message", "")

    def test_returns_400_empty_required_field_for_published(self, app):
        """Line 604: validate_required_fields returns a response when fields are empty."""
        from application.api.user.agents.routes import CreateAgent

        mock_handle_img = Mock(return_value=("", None))
        source_id = str(ObjectId())

        with patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ):
            with app.test_request_context(
                "/api/create_agent",
                method="POST",
                json={
                    "name": "",
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
                assert response.status_code == 400

    def test_create_with_default_source_string(self, app):
        """Line 638: source='default' sets source_field to 'default' literal."""
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
                    "name": "Default Source Agent",
                    "description": "desc",
                    "status": "published",
                    "agent_type": "classic",
                    "source": "default",
                    "chunks": "5",
                    "retriever": "classic",
                    "prompt_id": "default",
                },
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = CreateAgent().post()
                assert response.status_code == 201
                # Verify the insert was called (source="default" branch reached)
                mock_agents_col.insert_one.assert_called_once()
                inserted_doc = mock_agents_col.insert_one.call_args[0][0]
                assert inserted_doc["source"] == "default"


# ---------------------------------------------------------------------------
# UpdateAgent – various branch gaps
# ---------------------------------------------------------------------------


def _make_existing_agent(agent_id=None, **kwargs):
    doc = {
        "_id": agent_id or ObjectId(),
        "user": "user1",
        "name": "Existing Agent",
        "description": "desc",
        "source": "default",
        "chunks": "5",
        "retriever": "classic",
        "prompt_id": "default",
        "status": "published",
        "agent_type": "classic",
        "key": "abcd1234efgh5678",
    }
    doc.update(kwargs)
    return doc


@pytest.mark.unit
class TestUpdateAgentGaps:

    def test_exception_during_form_data_parse(self, app):
        """Lines 783-787: exception raised during request-data parsing returns 400."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = str(ObjectId())

        with app.test_request_context(
            f"/api/update_agent/{agent_id}",
            method="PUT",
            content_type="multipart/form-data",
            data={"tools": "[invalid"},
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            response = UpdateAgent().put(agent_id)
            assert response.status_code == 400

    def test_exception_during_get_json_parse(self, app):
        """Lines 783-787: unexpected exception from get_json() itself returns 400."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = str(ObjectId())

        with app.test_request_context(
            f"/api/update_agent/{agent_id}",
            method="PUT",
            content_type="application/json",
        ):
            from flask import request

            request.decoded_token = {"sub": "user1"}
            # Patch get_json to raise unexpectedly
            with patch.object(request, "get_json", side_effect=Exception("parse error")):
                response = UpdateAgent().put(agent_id)
            assert response.status_code == 400
            assert "Invalid request data" in response.json.get("message", "")

    def test_update_source_with_valid_oid(self, app):
        """Line 858: source is a valid OID → stored as DBRef."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        src_id = str(ObjectId())
        existing = _make_existing_agent(agent_id)
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
                json={"source": src_id},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_set = mock_col.update_one.call_args[0][1]["$set"]
                assert isinstance(call_set["source"], DBRef)

    def test_update_sources_empty_list(self, app):
        """Line 892: sources=[] sets update field to []."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = _make_existing_agent(agent_id)
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
                json={"sources": []},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_set = mock_col.update_one.call_args[0][1]["$set"]
                assert call_set["sources"] == []

    def test_update_valid_positive_chunks(self, app):
        """Line 910: valid positive chunks value stored as string."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = _make_existing_agent(agent_id)
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
                json={"chunks": 10},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_set = mock_col.update_one.call_args[0][1]["$set"]
                assert call_set["chunks"] == "10"

    def test_workflow_validation_error_in_update(self, app):
        """Line 1051: workflow validation failure returns the error response."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = _make_existing_agent(agent_id, agent_type="workflow", status="draft")
        existing["workflow"] = None
        mock_col = Mock()
        mock_col.find_one.return_value = existing
        mock_handle_img = Mock(return_value=("", None))
        # Mock validate_workflow_access to return an error
        error_response = Mock()
        error_response.status_code = 400

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.handle_image_upload", mock_handle_img
        ), patch(
            "application.api.user.agents.routes.validate_workflow_access",
            return_value=(None, error_response),
        ):
            with app.test_request_context(
                f"/api/update_agent/{agent_id}",
                method="PUT",
                json={"workflow": "bad-workflow-id"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                # The error response from validate_workflow_access is returned directly
                assert response is error_response

    def test_allow_system_prompt_override_string_true(self, app):
        """Lines 1054-1055: allow_system_prompt_override as string 'True' is parsed to bool."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        existing = _make_existing_agent(agent_id)
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
                # Send as a form field (string) rather than JSON bool
                content_type="application/json",
                json={"allow_system_prompt_override": "True"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 200
                call_set = mock_col.update_one.call_args[0][1]["$set"]
                assert call_set["allow_system_prompt_override"] is True

    def test_publish_workflow_agent_with_missing_name(self, app):
        """Line 1101: publishing a workflow agent that has no name raises missing-field error."""
        from application.api.user.agents.routes import UpdateAgent

        agent_id = ObjectId()
        wf_id = str(ObjectId())
        existing = {
            "_id": agent_id,
            "user": "user1",
            "name": "",          # empty name → missing published field
            "status": "draft",
            "agent_type": "workflow",
            "key": "",
            "workflow": wf_id,
        }
        mock_col = Mock()
        mock_col.find_one.return_value = existing
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
                json={"status": "published"},
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = UpdateAgent().put(str(agent_id))
                assert response.status_code == 400
                assert "Agent name" in response.json.get("message", "")


# ---------------------------------------------------------------------------
# AdoptAgent – DBRef source serialisation (line 1406)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAdoptAgentDBRefSource:

    def test_dbref_source_serialised_to_string(self, app):
        """Line 1406: DBRef source in the adopted agent is converted to its string id."""
        from application.api.user.agents.routes import AdoptAgent

        source_oid = ObjectId()
        agent_id = ObjectId()
        inserted_id = ObjectId()
        system_agent = {
            "_id": agent_id,
            "user": "system",
            "name": "Template Agent",
            "source": DBRef("sources", source_oid),
            "tools": [],
        }
        mock_col = Mock()
        mock_col.find_one.return_value = system_agent
        mock_col.insert_one.return_value = Mock(inserted_id=inserted_id)
        mock_resolve = Mock(return_value=[])

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", mock_resolve
        ):
            with app.test_request_context(
                f"/api/adopt_agent?id={agent_id}",
                method="POST",
            ):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = AdoptAgent().post()
                assert response.status_code == 200
                # source should be stringified OID, not a DBRef
                assert response.json["agent"]["source"] == str(source_oid)
