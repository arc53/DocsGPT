"""Roles on prompts: listing payload, get, update, delete."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.resource_access import set_settings
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository

OWNER = "alice"


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.prompts.routes.db_session", _yield), patch(
        "docsgpt.api.user.prompts.routes.db_readonly", _yield
    ):
        yield


def _call(app, conn, resource_cls, user, *, method="post", json=None, path="/api/x"):
    with _patch_db(conn), app.test_request_context(path, method=method.upper(), json=json):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _prompt(conn, name="P", content="C"):
    return PromptsRepository(conn).create(OWNER, name, content)


def _share(conn, prompt_id, member, level):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", OWNER)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "prompt", str(prompt_id), OWNER, OWNER, access_level=level
    )


class TestGetPromptsAccess:
    def _list(self, app, conn, user):
        from docsgpt.api.user.prompts.routes import GetPrompts

        resp = _call(app, conn, GetPrompts, user, method="get", path="/api/get_prompts")
        assert resp.status_code == 200
        return {p["id"]: p for p in resp.json}

    def test_owner_and_grantee_payloads(self, app, pg_conn):
        prompt = _prompt(pg_conn)
        pid = str(prompt["id"])
        _share(pg_conn, pid, "bob", "viewer")
        own = self._list(app, pg_conn, OWNER)[pid]
        assert own["access"] == "owner" and "delete" in own["allowed_actions"]
        assert own["updated_at"]
        shared = self._list(app, pg_conn, "bob")[pid]
        assert shared["access"] == "viewer"
        assert shared["allowed_actions"] == ["duplicate", "use"]
        assert shared["type"] == "team" and shared["team_access"] == "viewer"
        assert shared["updated_at"]

    def test_presets_have_no_access_fields(self, app, pg_conn):
        presets = self._list(app, pg_conn, OWNER)
        assert "access" not in presets["default"]


class TestGetSinglePromptAccess:
    def test_by_role(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import GetSinglePrompt

        prompt = _prompt(pg_conn, content="Hello")
        pid = str(prompt["id"])
        _share(pg_conn, pid, "bob", "viewer")
        for user, access in ((OWNER, "owner"), ("bob", "viewer")):
            resp = _call(app, pg_conn, GetSinglePrompt, user, method="get", path=f"/api/get_single_prompt?id={pid}")
            assert resp.status_code == 200
            assert resp.json["content"] == "Hello"
            assert resp.json["access"] == access
            assert resp.json["updated_at"]
        resp = _call(app, pg_conn, GetSinglePrompt, "eve", method="get", path=f"/api/get_single_prompt?id={pid}")
        assert resp.status_code == 404


class TestUpdatePromptAccess:
    def test_by_role(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import UpdatePrompt

        prompt = _prompt(pg_conn)
        pid = str(prompt["id"])
        _share(pg_conn, pid, "ed", "editor")
        _share(pg_conn, pid, "vi", "viewer")
        body = {"id": pid, "name": "N", "content": "by editor"}
        assert _call(app, pg_conn, UpdatePrompt, "ed", json=body).status_code == 200
        assert PromptsRepository(pg_conn).get(pid, OWNER)["content"] == "by editor"
        resp = _call(app, pg_conn, UpdatePrompt, "vi", json=body)
        assert resp.status_code == 403 and resp.json["success"] is False
        assert _call(app, pg_conn, UpdatePrompt, "eve", json=body).status_code == 404

    def test_stale_write_is_409_for_owner_too(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import UpdatePrompt

        prompt = _prompt(pg_conn)
        body = {"id": str(prompt["id"]), "name": "N", "content": "x",
                "expected_updated_at": "2000-01-01T00:00:00+00:00"}
        resp = _call(app, pg_conn, UpdatePrompt, OWNER, json=body)
        assert resp.status_code == 409 and resp.json["code"] == "stale_write"


class TestDeletePromptAccess:
    def test_by_role_and_cleanup(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import DeletePrompt

        prompt = _prompt(pg_conn)
        pid = str(prompt["id"])
        _share(pg_conn, pid, "ed", "editor")
        set_settings(pg_conn, "prompt", pid, {"editors_can_share": True}, OWNER)
        assert _call(app, pg_conn, DeletePrompt, "ed", json={"id": pid}).status_code == 403
        assert _call(app, pg_conn, DeletePrompt, "eve", json={"id": pid}).status_code == 404
        assert _call(app, pg_conn, DeletePrompt, OWNER, json={"id": pid}).status_code == 200
        assert PromptsRepository(pg_conn).get(pid, OWNER) is None
        for table in ("team_resource_grants", "resource_share_settings"):
            count = pg_conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE resource_id = CAST(:id AS uuid)"), {"id": pid}
            ).scalar()
            assert count == 0
