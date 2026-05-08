"""Tests for helper functions in application/api/user/agents/routes.py."""

import json
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


class TestNormalizeWorkflowReference:
    def test_none_returns_none(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference(None) is None

    def test_dict_returns_id_field(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference({"id": "w1"}) == "w1"

    def test_dict_returns_workflow_id_field(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert (
            normalize_workflow_reference({"workflow_id": "wf99"}) == "wf99"
        )

    def test_dict_with_underscore_id(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference({"_id": "wf-2"}) == "wf-2"

    def test_empty_string_returns_empty(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference("") == ""

    def test_plain_string_returned(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference("wf-123") == "wf-123"

    def test_json_string_dict(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert (
            normalize_workflow_reference(json.dumps({"id": "x"})) == "x"
        )

    def test_json_string_as_string(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference('"wf-str"') == "wf-str"

    def test_invalid_json_returns_original(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference("not-json-wf") == "not-json-wf"

    def test_non_string_non_dict_coerced(self):
        from application.api.user.agents.routes import (
            normalize_workflow_reference,
        )
        assert normalize_workflow_reference(42) == "42"


class TestResolveWorkflowForUser:
    def test_none_workflow_returns_none(self, pg_conn):
        from application.api.user.agents.routes import (
            _resolve_workflow_for_user,
        )
        pg_id, err = _resolve_workflow_for_user(pg_conn, None, "u")
        assert pg_id is None and err is None

    def test_not_found_returns_error(self, pg_conn, app):
        from application.api.user.agents.routes import (
            _resolve_workflow_for_user,
        )
        with app.app_context():
            pg_id, err = _resolve_workflow_for_user(
                pg_conn,
                "00000000-0000-0000-0000-000000000000",
                "u",
            )
        assert pg_id is None
        assert err is not None
        assert err.status_code == 404

    def test_resolves_owned_workflow(self, pg_conn, app):
        from application.api.user.agents.routes import (
            _resolve_workflow_for_user,
        )
        from application.storage.db.repositories.workflows import (
            WorkflowsRepository,
        )

        user = "owner"
        wf = WorkflowsRepository(pg_conn).create(user, "wf")
        with app.app_context():
            pg_id, err = _resolve_workflow_for_user(
                pg_conn, str(wf["id"]), user,
            )
        assert pg_id == str(wf["id"])
        assert err is None


class TestResolveFolderId:
    def test_none_returns_none(self, pg_conn):
        from application.api.user.agents.routes import _resolve_folder_id
        pg_id, err = _resolve_folder_id(pg_conn, None, "u")
        assert pg_id is None
        assert err is None

    def test_not_found_returns_error(self, pg_conn, app):
        from application.api.user.agents.routes import _resolve_folder_id

        with app.app_context():
            pg_id, err = _resolve_folder_id(
                pg_conn, "00000000-0000-0000-0000-000000000000", "u",
            )
        assert pg_id is None
        assert err.status_code == 404

    def test_resolves_owned_folder(self, pg_conn, app):
        from application.api.user.agents.routes import _resolve_folder_id
        from application.storage.db.repositories.agent_folders import (
            AgentFoldersRepository,
        )

        user = "u"
        folder = AgentFoldersRepository(pg_conn).create(user, "F")
        with app.app_context():
            pg_id, err = _resolve_folder_id(pg_conn, str(folder["id"]), user)
        assert pg_id == str(folder["id"])
        assert err is None


class TestFormatAgentOutput:
    def test_basic_shape(self):
        from application.api.user.agents.routes import _format_agent_output

        agent = {
            "id": "agent-1",
            "name": "My",
            "description": "D",
            "source_id": "src-1",
            "extra_source_ids": ["s1", "s2"],
            "chunks": 4,
            "retriever": "classic",
            "prompt_id": "p-1",
            "tools": [],
            "agent_type": "classic",
            "status": "draft",
            "key": "secret-api-key-long",
        }
        out = _format_agent_output(agent)
        assert out["id"] == "agent-1"
        assert out["name"] == "My"
        assert out["source"] == "src-1"
        assert out["sources"] == ["s1", "s2"]
        # masked key: first4...last4
        assert out["key"].startswith("secr") and out["key"].endswith("long")

    def test_no_key_masking(self):
        from application.api.user.agents.routes import _format_agent_output

        agent = {"id": "a", "name": "n", "chunks": None}
        out = _format_agent_output(agent, include_key_masked=False)
        assert "key" not in out

    def test_empty_key_returns_empty_string(self):
        from application.api.user.agents.routes import _format_agent_output

        agent = {"id": "a", "name": "n", "key": ""}
        out = _format_agent_output(agent)
        assert out["key"] == ""

    def test_with_folder_and_workflow(self):
        from application.api.user.agents.routes import _format_agent_output

        agent = {
            "id": "a", "name": "n",
            "folder_id": "f-1", "workflow_id": "w-1",
        }
        out = _format_agent_output(agent)
        assert out["folder_id"] == "f-1"
        assert out["workflow"] == "w-1"


class TestBuildCreateKwargs:
    def test_classic_kwargs(self):
        from application.api.user.agents.routes import _build_create_kwargs

        data = {
            "description": "d",
            "agent_type": "classic",
            "chunks": "3",
            "retriever": "classic",
        }
        out = _build_create_kwargs(
            data, image_url="", agent_type="classic",
        )
        assert out["description"] == "d"
        assert out["chunks"] == 3

    def test_invalid_chunks_skipped(self, app):
        from application.api.user.agents.routes import _build_create_kwargs

        data = {"chunks": "abc"}
        with app.app_context():
            out = _build_create_kwargs(
                data, image_url="", agent_type="classic",
            )
        assert "chunks" not in out

    def test_prompt_id_default_not_set(self):
        from application.api.user.agents.routes import _build_create_kwargs

        data = {"prompt_id": "default"}
        out = _build_create_kwargs(
            data, image_url="", agent_type="classic",
        )
        assert "prompt_id" not in out

    def test_image_url_used_when_provided(self):
        from application.api.user.agents.routes import _build_create_kwargs

        out = _build_create_kwargs(
            {}, image_url="/upload/img.png", agent_type="classic",
        )
        assert out.get("image") == "/upload/img.png"
