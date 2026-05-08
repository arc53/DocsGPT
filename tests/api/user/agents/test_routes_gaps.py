"""Gap-coverage tests for application.api.user.agents.routes.

No bson/ObjectId imports. The routes internally use ObjectId (patched where
needed) and Mongo collections (mocked). Repository assertions use
AgentsRepository patches for Postgres-specific paths.
"""

import uuid
from unittest.mock import Mock

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
    pass

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
    pass

    def _fake_objectid(self, valid: bool = True):
        """Return a Mock that mimics bson.ObjectId."""
        oid_cls = Mock()
        oid_cls.is_valid = Mock(return_value=valid)
        oid_cls.return_value = Mock()
        return oid_cls







# ---------------------------------------------------------------------------
# build_agent_document — pure logic, no DB needed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildAgentDocumentGaps:
    pass








# ---------------------------------------------------------------------------
# GetAgent route — additional edge cases (uuid-based IDs, no bson)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetAgentGaps:
    pass

