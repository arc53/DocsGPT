"""Gap-coverage tests for application.api.user.agents.routes.

No bson/ObjectId imports. The routes internally use ObjectId (patched where
needed) and Mongo collections (mocked). Repository assertions use
AgentsRepository patches for Postgres-specific paths.
"""

import uuid
from unittest.mock import Mock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return Flask(__name__)


def _fake_oid():
    """Return a 24-character hex string that looks like a Mongo ObjectId."""
    return uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# normalize_workflow_reference — pure utility, no bson needed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNormalizeWorkflowReferenceGaps:

    def test_handles_integer_zero(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference(0) == "0"

    def test_handles_list_converts_to_str(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference([1, 2])
        assert isinstance(result, str)

    def test_json_string_with_underscore_id(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference('{"_id": "abc"}')
        assert result == "abc"

    def test_json_string_with_workflow_id_key(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference('{"workflow_id": "wf99"}')
        assert result == "wf99"

    def test_whitespace_only_string_returns_empty(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        assert normalize_workflow_reference("  \t  ") == ""

    def test_dict_missing_all_id_keys_returns_none(self):
        from application.api.user.agents.routes import normalize_workflow_reference

        result = normalize_workflow_reference({"other_key": "value"})
        assert result is None


# ---------------------------------------------------------------------------
# validate_workflow_access — mocked ObjectId + workflows_collection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateWorkflowAccessGaps:

    def _fake_objectid(self, valid: bool = True):
        """Return a Mock that mimics bson.ObjectId."""
        oid_cls = Mock()
        oid_cls.is_valid = Mock(return_value=valid)
        oid_cls.return_value = Mock()
        return oid_cls

    def test_returns_404_when_workflow_not_found(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        fake_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = None
        mock_oid = self._fake_objectid(valid=True)

        with app.app_context():
            with patch(
                "application.api.user.agents.routes.workflows_collection", mock_wf_col
            ), patch("application.api.user.agents.routes.ObjectId", mock_oid):
                wf_id, err = validate_workflow_access(fake_id, "user1")

        assert wf_id is None
        assert err is not None
        assert err.status_code == 404

    def test_returns_workflow_id_when_found(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        fake_id = _fake_oid()
        mock_wf_col = Mock()
        mock_wf_col.find_one.return_value = {"_id": fake_id, "user": "user1"}
        mock_oid = self._fake_objectid(valid=True)

        with app.app_context():
            with patch(
                "application.api.user.agents.routes.workflows_collection", mock_wf_col
            ), patch("application.api.user.agents.routes.ObjectId", mock_oid):
                wf_id, err = validate_workflow_access(fake_id, "user1")

        assert wf_id == fake_id
        assert err is None

    def test_returns_400_for_invalid_id_format(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        mock_oid = self._fake_objectid(valid=False)

        with app.app_context():
            with patch("application.api.user.agents.routes.ObjectId", mock_oid):
                wf_id, err = validate_workflow_access("bad-id", "user1")

        assert wf_id is None
        assert err.status_code == 400

    def test_returns_none_error_when_not_required_and_empty(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        with app.app_context():
            wf_id, err = validate_workflow_access(None, "user1", required=False)

        assert wf_id is None
        assert err is None

    def test_returns_400_when_required_and_empty(self, app):
        from application.api.user.agents.routes import validate_workflow_access

        with app.app_context():
            wf_id, err = validate_workflow_access("", "user1", required=True)

        assert wf_id is None
        assert err.status_code == 400


# ---------------------------------------------------------------------------
# build_agent_document — pure logic, no DB needed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAgentDocumentGaps:

    def test_allow_system_prompt_override_string_true(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 1000, "request_limit": 100}),
        ):
            data = {"name": "A", "status": "draft", "allow_system_prompt_override": "True"}
            doc = build_agent_document(data, "user1", "k", "classic")
        assert doc["allow_system_prompt_override"] is True

    def test_allow_system_prompt_override_bool_false(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 1000, "request_limit": 100}),
        ):
            data = {"name": "A", "status": "draft", "allow_system_prompt_override": False}
            doc = build_agent_document(data, "user1", "k", "classic")
        assert doc["allow_system_prompt_override"] is False

    def test_workflow_doc_has_no_retriever(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 1000, "request_limit": 100}),
        ):
            doc = build_agent_document(
                {"name": "W", "status": "draft", "workflow": "wfabc"},
                "user1", "k", "workflow",
            )
        assert "retriever" not in doc
        assert "image" not in doc
        assert doc.get("workflow") == "wfabc"

    def test_react_agent_type_uses_classic_schema(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 1000, "request_limit": 100}),
        ):
            doc = build_agent_document(
                {"name": "R", "status": "draft"},
                "user1", "k", "react",
            )
        assert doc["agent_type"] == "react"
        assert "image" in doc

    def test_token_limit_cast_to_int(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 1000, "request_limit": 100}),
        ):
            doc = build_agent_document(
                {"name": "A", "status": "draft", "token_limit": "500"},
                "user1", "k", "classic",
            )
        assert isinstance(doc["token_limit"], int)
        assert doc["token_limit"] == 500

    def test_request_limit_defaults_from_settings(self):
        from application.api.user.agents.routes import build_agent_document

        with patch(
            "application.api.user.agents.routes.settings",
            Mock(DEFAULT_AGENT_LIMITS={"token_limit": 2000, "request_limit": 50}),
        ):
            doc = build_agent_document(
                {"name": "A", "status": "draft"},
                "user1", "k", "classic",
            )
        assert doc["request_limit"] == 50


# ---------------------------------------------------------------------------
# GetAgent route — additional edge cases (uuid-based IDs, no bson)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgentGaps:

    def test_returns_400_when_db_raises(self, app):
        from application.api.user.agents.routes import GetAgent

        agent_id = _fake_oid()
        mock_col = Mock()
        mock_col.find_one.side_effect = Exception("connection reset")

        with patch("application.api.user.agents.routes.agents_collection", mock_col):
            with app.test_request_context(f"/api/get_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                result = GetAgent().get()

        assert result[1] == 400

    def test_returns_agent_name_in_response(self, app):
        from application.api.user.agents.routes import GetAgent

        agent_id = _fake_oid()
        mock_col = Mock()
        mock_col.find_one.return_value = {
            "_id": agent_id,
            "user": "user1",
            "name": "MyAgent",
            "description": "desc",
            "chunks": "5",
            "retriever": "classic",
            "prompt_id": "default",
            "tools": [],
            "agent_type": "classic",
            "status": "published",
            "key": uuid.uuid4().hex,
        }

        with patch(
            "application.api.user.agents.routes.agents_collection", mock_col
        ), patch(
            "application.api.user.agents.routes.resolve_tool_details", Mock(return_value=[])
        ), patch(
            "application.api.user.agents.routes.db", Mock()
        ):
            with app.test_request_context(f"/api/get_agent?id={agent_id}"):
                from flask import request

                request.decoded_token = {"sub": "user1"}
                response = GetAgent().get()

        assert response.status_code == 200
        assert response.json["name"] == "MyAgent"
