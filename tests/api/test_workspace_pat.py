"""Personal access tokens in team workspaces: a token acts as its person, with the same workspace header.

The requests go through the whole Flask app, so the token's scope check and the
route's workspace check both run. The token's tool for agents (``agent_tool``)
can't set headers, so its list and create actions take the workspace as the
``workspace`` query parameter, which the same check reads.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from docsgpt.api.pat.tokens import expand_scopes
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER, WORKSPACE_PARAM
from docsgpt.workspaces.principal import principal_id

PRESETS = {"default", "creative", "strict"}


@pytest.fixture(scope="module")
def client():
    from docsgpt.app import app

    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with patch("docsgpt.api.user.prompts.routes.db_session", _yield), patch(
        "docsgpt.api.user.prompts.routes.db_readonly", _yield
    ), patch("docsgpt.workspaces.context.db_readonly", _yield):
        yield pg_conn


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "alice", role="team_admin")
    repo.add_member(tid, "eddie", role="team_editor")
    repo.add_member(tid, "vera", role="team_viewer")
    return tid, principal_id(tid)


def _pat(sub, scopes, resource_filter=None):
    return {
        "sub": sub,
        "auth_method": "pat",
        "pat_id": "t1",
        "pat_name": "ci",
        "scopes": sorted(expand_scopes(scopes)),
        "resource_filter": resource_filter or {},
    }


def _call(client, method, path, claims, workspace=None, **kwargs):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with patch("docsgpt.app.handle_auth", return_value=claims):
        return client.open(path, method=method, headers=headers, **kwargs)


def _prompt(conn, owner, name, created_by=None):
    return str(PromptsRepository(conn).create(owner, name, "Be brief.", created_by=created_by)["id"])


def _ids(response):
    return {row["id"] for row in response.get_json()} - PRESETS


class TestLists:
    def test_the_header_picks_the_team_for_a_token(self, client, db):
        tid, principal = _team(db)
        team_prompt = _prompt(db, principal, "Team", created_by="alice")
        mine = _prompt(db, "vera", "Mine")
        claims = _pat("vera", ["prompts:read"])

        assert _ids(_call(client, "GET", "/api/get_prompts", claims)) == {mine}
        assert _ids(_call(client, "GET", "/api/get_prompts", claims, workspace=tid)) == {team_prompt}

    def test_the_query_parameter_works_too(self, client, db):
        tid, principal = _team(db)
        team_prompt = _prompt(db, principal, "Team", created_by="alice")
        response = _call(client, "GET", f"/api/get_prompts?{WORKSPACE_PARAM}={tid}", _pat("vera", ["prompts:read"]))
        assert _ids(response) == {team_prompt}

    def test_a_token_of_a_non_member_gets_404(self, client, db):
        tid, principal = _team(db)
        _prompt(db, principal, "Team", created_by="alice")
        response = _call(client, "GET", "/api/get_prompts", _pat("stranger", ["prompts:read"]), workspace=tid)
        assert response.status_code == 404
        assert response.get_json()["error"] == "workspace_not_found"

    def test_a_restricted_token_sees_only_its_team_rows(self, client, db):
        tid, principal = _team(db)
        allowed = _prompt(db, principal, "Allowed", created_by="alice")
        _prompt(db, principal, "Other", created_by="alice")
        claims = _pat("vera", ["prompts:read"], {"prompts": [allowed]})
        assert _ids(_call(client, "GET", "/api/get_prompts", claims, workspace=tid)) == {allowed}


class TestCreates:
    def test_an_editors_token_creates_a_team_prompt(self, client, db):
        tid, principal = _team(db)
        response = _call(client, "POST", "/api/create_prompt", _pat("eddie", ["prompts:write"]), workspace=tid,
                         json={"name": "N", "content": "C"})
        assert response.status_code == 200, response.get_json()
        row = PromptsRepository(db).get(response.get_json()["id"], principal)
        assert row is not None and row["created_by"] == "eddie"

    def test_a_viewers_token_is_refused(self, client, db):
        tid, principal = _team(db)
        response = _call(client, "POST", "/api/create_prompt", _pat("vera", ["prompts:write"]), workspace=tid,
                         json={"name": "N", "content": "C"})
        assert response.status_code == 403
        assert response.get_json()["error"] == "workspace_role_required"
        assert PromptsRepository(db).list_for_user(principal) == []

    def test_a_non_members_token_creates_nothing(self, client, db):
        tid, principal = _team(db)
        response = _call(client, "POST", "/api/create_prompt", _pat("stranger", ["prompts:write"]), workspace=tid,
                         json={"name": "N", "content": "C"})
        assert response.status_code == 404
        assert PromptsRepository(db).list_for_user(principal) == []
        assert PromptsRepository(db).list_for_user("stranger") == []


class TestAgentTool:
    """The token's tool for agents names the workspace on every list and create of one."""

    LISTS_AND_CREATES = {
        "list_agents", "create_agent", "list_agent_folders", "create_agent_folder", "list_schedules",
        "list_sources", "search_sources_list", "create_wiki_source", "list_folders", "create_folder",
        "file_in_folder", "list_prompts", "create_prompt", "list_tools", "create_tool", "list_artifacts",
        "list_conversations", "search_conversations",
    }

    def test_lists_and_creates_take_a_workspace(self):
        from docsgpt.api.pat.agent_tool import CATALOG

        taking = {entry.name for entry in CATALOG if "workspace" in entry.query}
        assert taking == self.LISTS_AND_CREATES
        for entry in CATALOG:
            if entry.name in taking:
                spec = entry.query["workspace"]
                assert spec["required"] is False and "list_workspaces" in spec["description"]

    def test_built_actions_carry_it_as_a_query_parameter(self):
        from docsgpt.api.pat.agent_tool import build_actions

        actions = build_actions("https://docs.example.com", "dgpt_x", ["prompts:write", "teams:read"], {})
        assert WORKSPACE_PARAM in actions["list_prompts"]["query_params"]["properties"]
        assert WORKSPACE_PARAM in actions["create_prompt"]["query_params"]["properties"]
        assert WORKSPACE_PARAM not in actions["get_prompt"]["query_params"]["properties"]
        assert "list_workspaces" in actions
