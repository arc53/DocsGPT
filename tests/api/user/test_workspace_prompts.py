"""Prompts per workspace: a list shows one workspace, a create lands in the one the request names."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id


@pytest.fixture
def app():
    return Flask(__name__)


def _team(conn, owner="alice", name="Ops", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.prompts.routes.db_session", _yield), patch(
        "docsgpt.api.user.prompts.routes.db_readonly", _yield
    ), patch("docsgpt.workspaces.context.db_readonly", _yield):
        yield


def _call(app, conn, resource_cls, user, *, team=None, method="post", json=None, path="/api/x"):
    headers = {WORKSPACE_HEADER: team} if team else {}
    with _patch_db(conn), app.test_request_context(path, method=method.upper(), json=json, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _prompt(conn, owner, name="P", created_by=None):
    return PromptsRepository(conn).create(owner, name, "Be brief.", created_by=created_by)


def _list(app, conn, user, team=None):
    from docsgpt.api.user.prompts.routes import GetPrompts

    return _call(app, conn, GetPrompts, user, team=team, method="get", path="/api/get_prompts")


class TestLists:
    def test_team_list_has_presets_and_the_teams_prompts_only(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        _o_tid, other_principal = _team(pg_conn, name="Other", members=(("eddie", "team_viewer"),))
        team_prompt = _prompt(pg_conn, principal, "Team", created_by="adam")
        _prompt(pg_conn, other_principal, "Other team", created_by="alice")
        _prompt(pg_conn, "eddie", "Mine", created_by="eddie")
        UsersRepository(pg_conn).upsert("adam", email="adam@example.com")

        resp = _list(app, pg_conn, "eddie", team=tid)
        assert resp.status_code == 200
        rows = {p["id"]: p for p in resp.json}
        assert {"default", "creative", "strict"} <= set(rows)
        assert set(rows) - {"default", "creative", "strict"} == {str(team_prompt["id"])}
        row = rows[str(team_prompt["id"])]
        assert row["type"] == "team"  # compat: today's UI reads a team row like a shared one
        assert row["team_access"] == "editor"
        assert row["access"] == "editor" and row["team_role"] == "editor" and row["origin"] == "team"
        assert row["workspace"] == {"kind": "team", "team_id": tid}
        assert "edit" in row["allowed_actions"] and "delete" not in row["allowed_actions"]
        assert row["created_by"] == {"user_id": "adam", "label": "adam@example.com"}
        assert row["owner_label"] == "Ops"

    def test_personal_list_never_shows_team_prompts(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_prompt = _prompt(pg_conn, principal, "Team", created_by="adam")
        mine = _prompt(pg_conn, "eddie", "Mine", created_by="eddie")
        with patch(
            "docsgpt.api.user.prompts.routes.visible_with_access",
            return_value={str(team_prompt["id"]): "viewer"},
        ):
            resp = _list(app, pg_conn, "eddie")
        ids = {p["id"] for p in resp.json} - {"default", "creative", "strict"}
        assert ids == {str(mine["id"])}
        row = next(p for p in resp.json if p["id"] == str(mine["id"]))
        assert row["type"] == "private" and row["created_by"] == {"user_id": "eddie", "label": "eddie"}

    def test_non_member_header_is_404(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = _list(app, pg_conn, "stranger", team=tid)
        assert resp.status_code == 404


class TestCreate:
    def test_editor_creates_a_principal_owned_prompt(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import CreatePrompt

        tid, principal = _team(pg_conn)
        resp = _call(app, pg_conn, CreatePrompt, "eddie", team=tid, json={"name": "N", "content": "C"})
        assert resp.status_code == 200, resp.json
        row = PromptsRepository(pg_conn).get(resp.json["id"], principal)
        assert row is not None and row["created_by"] == "eddie"
        assert PromptsRepository(pg_conn).list_for_user("eddie") == []

    def test_viewer_and_stranger_cannot_create(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import CreatePrompt

        tid, principal = _team(pg_conn)
        resp = _call(app, pg_conn, CreatePrompt, "vera", team=tid, json={"name": "N", "content": "C"})
        assert resp.status_code == 403 and resp.json["error"] == "workspace_role_required"
        resp = _call(app, pg_conn, CreatePrompt, "stranger", team=tid, json={"name": "N", "content": "C"})
        assert resp.status_code == 404
        assert PromptsRepository(pg_conn).list_for_user(principal) == []

    def test_personal_create_records_the_creator(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import CreatePrompt

        resp = _call(app, pg_conn, CreatePrompt, "eddie", json={"name": "N", "content": "C"})
        assert PromptsRepository(pg_conn).get(resp.json["id"], "eddie")["created_by"] == "eddie"


class TestByIdRoutes:
    def test_viewer_reads_editor_edits_admin_deletes(self, app, pg_conn):
        from docsgpt.api.user.prompts.routes import DeletePrompt, GetSinglePrompt, UpdatePrompt

        tid, principal = _team(pg_conn)
        prompt = _prompt(pg_conn, principal, created_by="adam")
        pid = str(prompt["id"])
        read = _call(app, pg_conn, GetSinglePrompt, "vera", method="get", path=f"/api/get_single_prompt?id={pid}")
        assert read.status_code == 200
        assert read.json["access"] == "viewer" and read.json["workspace"] == {"kind": "team", "team_id": tid}
        assert read.json["created_by"] == {"user_id": "adam", "label": "adam"}
        assert _call(app, pg_conn, GetSinglePrompt, "stranger", method="get",
                     path=f"/api/get_single_prompt?id={pid}").status_code == 404

        body = {"id": pid, "name": "New", "content": "New text"}
        assert _call(app, pg_conn, UpdatePrompt, "vera", json=body).status_code == 403
        assert _call(app, pg_conn, UpdatePrompt, "eddie", json=body).status_code == 200
        assert PromptsRepository(pg_conn).get(pid, principal)["name"] == "New"

        assert _call(app, pg_conn, DeletePrompt, "eddie", json={"id": pid}).status_code == 403
        assert _call(app, pg_conn, DeletePrompt, "adam", json={"id": pid}).status_code == 200
        assert PromptsRepository(pg_conn).get(pid, principal) is None
