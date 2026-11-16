"""Agents and workflows in a team workspace.

A team's agents are owned by the team's principal and reached by team role only. Creates in a team need the
Editor role and record who added the item; a team agent references the team's own items only; outward exposure
(key, public link, webhook, publish) is an Admin action, and the Admin who turns it on pays for that traffic.
Lists are per workspace: Personal never shows a team's agents. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.resource_access import CODE_WORKSPACE_MISMATCH
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

OWNER, ADMIN, EDITOR, VIEWER, STRANGER = "ws-alice", "ws-adam", "ws-eddie", "ws-vera", "ws-stan"

_DB_MODULES = (
    "docsgpt.api.user.agents.routes",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.agents.webhooks",
    "docsgpt.api.user.workflows.routes",
    "docsgpt.api.user.folder_knowledge",
    "docsgpt.api.user.base",
)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    import importlib

    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        for mod_name in _DB_MODULES:
            mod = importlib.import_module(mod_name)
            for attr in ("db_session", "db_readonly"):
                if hasattr(mod, attr):
                    stack.enter_context(patch(f"{mod_name}.{attr}", _yield))
        yield


def _call(app, conn, resource_cls, method, path, user, *, json=None, args=(), query=None, team=None):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    if query is not None:
        kwargs["query_string"] = query
    if team is not None:
        kwargs["headers"] = {WORKSPACE_HEADER: team}
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _status(resp) -> int:
    return resp[1] if isinstance(resp, tuple) else resp.status_code


def _json(resp):
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _team(conn) -> tuple[str, str]:
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _agent(conn, owner, name="Bot", **extra) -> str:
    extra.setdefault("agent_type", "classic")
    extra.setdefault("chunks", 6)
    extra.setdefault("description", "d")
    return str(AgentsRepository(conn).create(owner, name, extra.pop("status", "draft"), **extra)["id"])


def _row(conn, agent_id):
    return AgentsRepository(conn).get_by_id(agent_id)


def _source(conn, owner, name="Handbook") -> str:
    return str(SourcesRepository(conn).create(name, user_id=owner)["id"])


def _tool(conn, owner) -> str:
    return str(UserToolsRepository(conn).create(owner, "api_tool", custom_name="CRM")["id"])


def _folder(conn, owner, name="Docs") -> str:
    return str(FoldersRepository(conn).create(owner, name)["id"])


_PUBLISHED = {"status": "published", "chunks": 2, "retriever": "classic", "prompt_id": "default"}


def _create(app, conn, user, team, **body):
    from docsgpt.api.user.agents.routes import CreateAgent

    payload = {"name": "Team bot", "description": "d", "status": "draft", "agent_type": "classic", **body}
    return _call(app, conn, CreateAgent, "post", "/api/create_agent", user, json=payload, team=team)


def _update(app, conn, user, agent_id, **body):
    from docsgpt.api.user.agents.routes import UpdateAgent

    return _call(app, conn, UpdateAgent, "put", f"/api/update_agent/{agent_id}", user, json=body, args=(agent_id,))


class TestCreateInATeam:
    def test_an_editor_creates_an_agent_the_principal_owns(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, EDITOR, tid)
        assert _status(resp) == 201, _json(resp)
        row = _row(pg_conn, _json(resp)["id"])
        assert row["user_id"] == principal
        assert row["created_by"] == EDITOR
        assert row["access_payer_id"] is None

    def test_a_viewer_is_refused(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, VIEWER, tid)
        assert _status(resp) == 403
        assert _json(resp)["error"] == "workspace_role_required"
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_a_non_member_gets_404_and_nothing_is_written(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, STRANGER, tid)
        assert _status(resp) == 404
        assert _json(resp)["error"] == "workspace_not_found"
        assert AgentsRepository(pg_conn).list_for_user(principal) == []
        assert AgentsRepository(pg_conn).list_for_user(STRANGER) == []

    def test_no_header_creates_a_personal_agent(self, app, pg_conn):
        _team(pg_conn)
        resp = _create(app, pg_conn, EDITOR, None)
        assert _status(resp) == 201
        row = _row(pg_conn, _json(resp)["id"])
        assert row["user_id"] == EDITOR
        assert row["created_by"] == EDITOR

    def test_a_personal_source_is_refused(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        mine = _source(pg_conn, EDITOR)
        resp = _create(app, pg_conn, EDITOR, tid, sources=[mine])
        assert _status(resp) == 400, _json(resp)
        body = _json(resp)
        assert body["error"] == CODE_WORKSPACE_MISMATCH
        assert body["resources"][0]["id"] == mine
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_a_personal_tool_is_refused(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = _create(app, pg_conn, EDITOR, tid, tools=[_tool(pg_conn, EDITOR)])
        assert _status(resp) == 400
        assert _json(resp)["error"] == CODE_WORKSPACE_MISMATCH

    def test_team_items_and_builtin_tools_are_allowed(self, app, pg_conn):
        from docsgpt.agents.default_tools import default_tool_id

        tid, principal = _team(pg_conn)
        source, tool = _source(pg_conn, principal), _tool(pg_conn, principal)
        builtin = default_tool_id("read_webpage")
        resp = _create(app, pg_conn, EDITOR, tid, sources=[source], tools=[tool, builtin], prompt_id="creative")
        assert _status(resp) == 201, _json(resp)
        row = _row(pg_conn, _json(resp)["id"])
        assert [str(s) for s in row["extra_source_ids"]] == [source]
        assert row["resource_sponsors"] in ({}, None)

    def test_a_team_folder_is_allowed_and_a_personal_one_refused(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_folder, own_folder = _folder(pg_conn, principal), _folder(pg_conn, EDITOR)
        ok = _create(app, pg_conn, EDITOR, tid, folders=[team_folder])
        assert _status(ok) == 201, _json(ok)
        assert [str(f) for f in _row(pg_conn, _json(ok)["id"])["knowledge_folder_ids"]] == [team_folder]
        refused = _create(app, pg_conn, EDITOR, tid, folders=[own_folder])
        assert _status(refused) == 400
        assert _json(refused)["error"] == CODE_WORKSPACE_MISMATCH

    def test_an_editor_may_not_create_it_published(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = _create(app, pg_conn, EDITOR, tid, **_PUBLISHED)
        assert _status(resp) == 403, _json(resp)
        assert _json(resp)["error"] == "workspace_role_required"
        assert AgentsRepository(pg_conn).list_for_user(principal) == []

    def test_an_admin_publishes_with_a_key_and_pays_for_it(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = _create(app, pg_conn, ADMIN, tid, **_PUBLISHED)
        assert _status(resp) == 201, _json(resp)
        row = _row(pg_conn, _json(resp)["id"])
        assert row["key"]
        assert row["access_payer_id"] == ADMIN

    def test_a_personal_agent_records_no_payer(self, app, pg_conn):
        resp = _create(app, pg_conn, EDITOR, None, **_PUBLISHED)
        row = _row(pg_conn, _json(resp)["id"])
        assert row["key"]
        assert row["access_payer_id"] is None


class TestUpdateATeamAgent:
    def test_an_editor_may_not_add_a_personal_source(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, created_by=EDITOR)
        resp = _update(app, pg_conn, EDITOR, agent_id, sources=[_source(pg_conn, EDITOR)])
        assert _status(resp) == 400
        assert _json(resp)["error"] == CODE_WORKSPACE_MISMATCH
        assert not _row(pg_conn, agent_id)["extra_source_ids"]

    def test_an_editor_may_add_a_team_folder_without_a_confirmation(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, created_by=EDITOR)
        folder = _folder(pg_conn, principal)
        resp = _update(app, pg_conn, EDITOR, agent_id, folders=[folder])
        assert _status(resp) == 200, _json(resp)
        assert [str(f) for f in _row(pg_conn, agent_id)["knowledge_folder_ids"]] == [folder]

    def test_a_personal_folder_is_refused(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, created_by=EDITOR)
        resp = _update(app, pg_conn, EDITOR, agent_id, folders=[_folder(pg_conn, EDITOR)])
        assert _status(resp) == 400
        assert _json(resp)["error"] == CODE_WORKSPACE_MISMATCH

    def test_a_viewer_may_not_edit(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        assert _status(_update(app, pg_conn, VIEWER, agent_id, name="New")) == 403

    def test_an_editor_may_not_publish(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        resp = _update(app, pg_conn, EDITOR, agent_id, status="published")
        assert _status(resp) == 403
        assert _row(pg_conn, agent_id)["status"] == "draft"

    def test_an_admin_publishes_and_becomes_the_payer(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        resp = _update(app, pg_conn, ADMIN, agent_id, status="published")
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert row["key"]
        assert row["access_payer_id"] == ADMIN

    def test_an_editors_save_of_a_keyless_published_agent_mints_no_key(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published")
        resp = _update(app, pg_conn, EDITOR, agent_id, name="Renamed")
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert not row["key"]
        assert row["access_payer_id"] is None

    def test_another_members_save_keeps_the_payer(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published", key=f"k-{uuid.uuid4().hex}",
                          access_payer_id=ADMIN)
        assert _status(_update(app, pg_conn, OWNER, agent_id, name="Renamed")) == 200
        assert _status(_update(app, pg_conn, EDITOR, agent_id, name="Again")) == 200
        assert _row(pg_conn, agent_id)["access_payer_id"] == ADMIN

    def test_an_editor_may_switch_the_team_agents_workflow(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        first = str(WorkflowsRepository(pg_conn).create(principal, "one")["id"])
        second = str(WorkflowsRepository(pg_conn).create(principal, "two")["id"])
        agent_id = _agent(pg_conn, principal, agent_type="workflow", workflow_id=first)
        resp = _update(app, pg_conn, EDITOR, agent_id, workflow=second)
        assert _status(resp) == 200, _json(resp)
        assert str(_row(pg_conn, agent_id)["workflow_id"]) == second


class TestOutwardExposure:
    def test_an_editor_may_not_share_a_link(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published")
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", EDITOR, json={"id": agent_id, "shared": True})
        assert _status(resp) == 403
        assert not _row(pg_conn, agent_id)["shared"]

    def test_an_admin_shares_a_link_and_pays_for_it(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published")
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", ADMIN, json={"id": agent_id, "shared": True})
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert row["shared"] is True
        assert row["access_payer_id"] == ADMIN

    def test_turning_a_link_on_beside_a_key_keeps_the_payer(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published", key=f"k-{uuid.uuid4().hex}",
                          access_payer_id=ADMIN)
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", OWNER, json={"id": agent_id, "shared": True})
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["access_payer_id"] == ADMIN

    def test_turning_a_webhook_on_beside_a_key_keeps_the_payer(self, app, pg_conn):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published", key=f"k-{uuid.uuid4().hex}",
                          access_payer_id=ADMIN)
        resp = _call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", OWNER, query={"id": agent_id})
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert row["incoming_webhook_token"]
        assert row["access_payer_id"] == ADMIN

    def test_turning_the_first_way_in_on_again_makes_that_admin_the_payer(self, app, pg_conn):
        from docsgpt.api.user.agents.sharing import ShareAgent

        tid, principal = _team(pg_conn)
        # Everything was turned off; the payer recorded then pays for nothing now.
        agent_id = _agent(pg_conn, principal, status="published", access_payer_id=ADMIN)
        resp = _call(app, pg_conn, ShareAgent, "put", "/api/share_agent", OWNER, json={"id": agent_id, "shared": True})
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["access_payer_id"] == OWNER

    def test_an_editor_may_not_mint_a_webhook(self, app, pg_conn):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published")
        resp = _call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", EDITOR, query={"id": agent_id})
        assert _status(resp) == 403
        assert not _row(pg_conn, agent_id)["incoming_webhook_token"]

    def test_an_admin_mints_a_webhook_and_pays_for_it(self, app, pg_conn):
        from docsgpt.api.user.agents.webhooks import AgentWebhook

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published")
        resp = _call(app, pg_conn, AgentWebhook, "get", "/api/agent_webhook", ADMIN, query={"id": agent_id})
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, agent_id)
        assert row["incoming_webhook_token"]
        assert row["access_payer_id"] == ADMIN

    def test_an_editor_may_not_rotate_the_key(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        tid, principal = _team(pg_conn)
        key = f"k-{uuid.uuid4().hex}"
        agent_id = _agent(pg_conn, principal, status="published", key=key, access_payer_id=ADMIN)
        resp = _call(app, pg_conn, RegenerateAgentKey, "post", f"/api/regenerate_agent_key/{agent_id}", EDITOR,
                     args=(agent_id,))
        assert _status(resp) == 403
        assert _row(pg_conn, agent_id)["key"] == key

    def test_rotating_the_key_keeps_the_payer(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import RegenerateAgentKey

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, status="published", key=f"k-{uuid.uuid4().hex}",
                          access_payer_id=ADMIN)
        resp = _call(app, pg_conn, RegenerateAgentKey, "post", f"/api/regenerate_agent_key/{agent_id}", OWNER,
                     args=(agent_id,))
        assert _status(resp) == 200
        assert _row(pg_conn, agent_id)["access_payer_id"] == ADMIN


class TestListsPerWorkspace:
    def _list(self, app, conn, user, team=None):
        from docsgpt.api.user.agents.routes import GetAgents

        resp = _call(app, conn, GetAgents, "get", "/api/get_agents", user, team=team)
        assert _status(resp) == 200, _json(resp)
        return _json(resp)

    def test_a_team_lists_its_agents_with_the_callers_role(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal, created_by=EDITOR)
        _agent(pg_conn, VIEWER, name="Private")
        rows = self._list(app, pg_conn, VIEWER, tid)
        assert [r["id"] for r in rows] == [team_agent]
        row = rows[0]
        assert row["workspace"] == {"kind": "team", "team_id": tid}
        assert row["team_role"] == "viewer"
        assert row["origin"] == "team"
        assert row["access"] == "viewer"
        assert set(row["allowed_actions"]) == {"use", "pin"}
        assert row["ownership"] == "team"
        assert row["created_by"]["user_id"] == EDITOR

    def test_an_admin_row_keeps_the_legacy_team_access(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        _agent(pg_conn, principal)
        row = self._list(app, pg_conn, ADMIN, tid)[0]
        assert row["access"] == "admin"
        assert row["team_access"] == "editor"
        assert "manage_access_details" in row["allowed_actions"]

    def test_personal_never_lists_team_agents(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        _agent(pg_conn, principal)
        own = _agent(pg_conn, EDITOR, name="Mine", created_by=EDITOR)
        rows = self._list(app, pg_conn, EDITOR)
        assert [r["id"] for r in rows] == [own]
        assert rows[0]["workspace"] == {"kind": "personal", "team_id": None}
        assert rows[0]["origin"] == "own"

    def test_a_forced_grant_on_a_team_agent_lists_nothing_in_personal(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        other = TeamsRepository(pg_conn).create("Side", f"side-{uuid.uuid4().hex[:6]}", OWNER)
        TeamMembersRepository(pg_conn).add_member(str(other["id"]), STRANGER)
        # A grant row that names a person as owner passes the CHECK; the lists must still ignore it.
        pg_conn.execute(
            text(
                "INSERT INTO team_resource_grants (team_id, resource_type, resource_id, owner_id, access_level, "
                "granted_by) VALUES (CAST(:t AS uuid), 'agent', CAST(:a AS uuid), :o, 'editor', :o)"
            ),
            {"t": str(other["id"]), "a": team_agent, "o": OWNER},
        )
        assert [r["id"] for r in self._list(app, pg_conn, STRANGER)] == []

    def test_the_principal_check_refuses_a_grant_owned_by_a_team(self, pg_conn):
        import sqlalchemy

        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            with pg_conn.begin_nested():
                pg_conn.execute(
                    text(
                        "INSERT INTO team_resource_grants (team_id, resource_type, resource_id, owner_id, "
                        "access_level, granted_by) VALUES (CAST(:t AS uuid), 'agent', CAST(:a AS uuid), :o, "
                        "'viewer', :g)"
                    ),
                    {"t": tid, "a": team_agent, "o": principal, "g": OWNER},
                )

    def test_another_teams_header_is_404(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgents

        tid, _principal = _team(pg_conn)
        resp = _call(app, pg_conn, GetAgents, "get", "/api/get_agents", STRANGER, team=tid)
        assert _status(resp) == 404


class TestGetAgent:
    def test_a_team_agent_names_its_workspace_and_creator(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgent

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal, created_by=EDITOR)
        resp = _call(app, pg_conn, GetAgent, "get", "/api/get_agent", EDITOR, query={"id": agent_id})
        assert _status(resp) == 200, _json(resp)
        body = _json(resp)
        assert body["workspace"] == {"kind": "team", "team_id": tid}
        assert body["team_role"] == "editor"
        assert body["ownership"] == "team"
        assert body["team_access"] == "editor"
        assert body["created_by"]["user_id"] == EDITOR

    def test_a_non_member_gets_404(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import GetAgent

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        resp = _call(app, pg_conn, GetAgent, "get", "/api/get_agent", STRANGER, query={"id": agent_id})
        assert _status(resp) == 404


class TestDelete:
    def _delete(self, app, conn, user, agent_id):
        from docsgpt.api.user.agents.routes import DeleteAgent

        return _call(app, conn, DeleteAgent, "delete", "/api/delete_agent", user, query={"id": agent_id})

    def test_an_editor_may_not_delete(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        assert _status(self._delete(app, pg_conn, EDITOR, agent_id)) == 403
        assert _row(pg_conn, agent_id) is not None

    def test_an_admin_deletes_with_its_workflow(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        wf = str(WorkflowsRepository(pg_conn).create(principal, "wf")["id"])
        agent_id = _agent(pg_conn, principal, agent_type="workflow", workflow_id=wf)
        assert _status(self._delete(app, pg_conn, ADMIN, agent_id)) == 200
        assert _row(pg_conn, agent_id) is None
        assert WorkflowsRepository(pg_conn).get_by_id(wf) is None


class TestPins:
    def _pinned(self, app, conn, user, team=None):
        from docsgpt.api.user.agents.routes import PinnedAgents

        resp = _call(app, conn, PinnedAgents, "get", "/api/pinned_agents", user, team=team)
        assert _status(resp) == 200, _json(resp)
        return [row["id"] for row in _json(resp)]

    def test_a_pin_shows_in_the_workspace_its_agent_lives_in(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import PinAgent

        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        own = _agent(pg_conn, VIEWER, name="Mine")
        for agent_id in (team_agent, own):
            resp = _call(app, pg_conn, PinAgent, "post", "/api/pin_agent", VIEWER, query={"id": agent_id})
            assert _status(resp) == 200, _json(resp)
        assert self._pinned(app, pg_conn, VIEWER) == [own]
        assert self._pinned(app, pg_conn, VIEWER, tid) == [team_agent]

    def test_a_non_member_cant_pin_a_team_agent(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import PinAgent

        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        resp = _call(app, pg_conn, PinAgent, "post", "/api/pin_agent", STRANGER, query={"id": team_agent})
        assert _status(resp) == 404


class TestAdoptInATeam:
    def _template(self, conn) -> str:
        UsersRepository(conn).upsert("__system__")
        return _agent(conn, "__system__", name="Template", status="published")

    def test_an_editor_adopts_into_the_team_as_a_draft_without_a_key(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import AdoptAgent

        tid, principal = _team(pg_conn)
        template = self._template(pg_conn)
        resp = _call(app, pg_conn, AdoptAgent, "post", "/api/adopt_agent", EDITOR, query={"id": template}, team=tid)
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, _json(resp)["agent"]["id"])
        assert row["user_id"] == principal
        assert row["created_by"] == EDITOR
        assert row["status"] == "draft"
        assert not row["key"]
        assert row["access_payer_id"] is None

    def test_an_admin_adopts_it_published_and_pays_for_the_key(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import AdoptAgent

        tid, principal = _team(pg_conn)
        template = self._template(pg_conn)
        resp = _call(app, pg_conn, AdoptAgent, "post", "/api/adopt_agent", ADMIN, query={"id": template}, team=tid)
        assert _status(resp) == 200, _json(resp)
        row = _row(pg_conn, _json(resp)["agent"]["id"])
        assert row["user_id"] == principal
        assert row["status"] == "published"
        assert row["key"]
        assert row["access_payer_id"] == ADMIN

    def test_a_viewer_may_not_adopt_into_the_team(self, app, pg_conn):
        from docsgpt.api.user.agents.routes import AdoptAgent

        tid, principal = _team(pg_conn)
        template = self._template(pg_conn)
        resp = _call(app, pg_conn, AdoptAgent, "post", "/api/adopt_agent", VIEWER, query={"id": template}, team=tid)
        assert _status(resp) == 403
        assert AgentsRepository(pg_conn).list_for_user(principal) == []


class TestWorkflowsInATeam:
    def _body(self, source=None, folder=None):
        cfg = {"agent_type": "classic", "system_prompt": "s", "tools": [], "sources": [source] if source else []}
        if folder:
            cfg["folders"] = [folder]
        return {
            "name": "WF",
            "description": "d",
            "nodes": [
                {"id": "start1", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "a1", "type": "agent", "title": "A", "position": {"x": 50, "y": 0},
                 "data": {"config": cfg}},
                {"id": "end1", "type": "end", "position": {"x": 100, "y": 0}, "data": {}},
            ],
            "edges": [
                {"id": "e1", "source": "start1", "target": "a1"},
                {"id": "e2", "source": "a1", "target": "end1"},
            ],
        }

    def _post(self, app, conn, user, team, body):
        from docsgpt.api.user.workflows.routes import WorkflowList

        return _call(app, conn, WorkflowList, "post", "/api/workflows", user, json=body, team=team)

    def test_an_editor_creates_a_principal_owned_workflow(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = self._post(app, pg_conn, EDITOR, tid, self._body(source=_source(pg_conn, principal)))
        assert _status(resp) in (200, 201), _json(resp)
        wf = WorkflowsRepository(pg_conn).get_by_id(_json(resp)["data"]["id"])
        assert wf["user_id"] == principal
        assert wf["created_by"] == EDITOR

    def test_a_viewer_is_refused(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = self._post(app, pg_conn, VIEWER, tid, self._body())
        assert _status(resp) == 403

    def test_a_personal_source_on_a_node_is_refused(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        resp = self._post(app, pg_conn, EDITOR, tid, self._body(source=_source(pg_conn, EDITOR)))
        assert _status(resp) == 400, _json(resp)
        assert _json(resp)["code"] == CODE_WORKSPACE_MISMATCH
        assert WorkflowsRepository(pg_conn).list_for_user(principal) == []

    def test_a_personal_folder_on_a_node_is_refused(self, app, pg_conn):
        tid, _principal = _team(pg_conn)
        resp = self._post(app, pg_conn, EDITOR, tid, self._body(folder=_folder(pg_conn, EDITOR)))
        assert _status(resp) == 400
        assert _json(resp)["code"] == CODE_WORKSPACE_MISMATCH

    def test_an_inline_graph_on_a_team_agent_is_principal_owned(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        body = self._body(source=_source(pg_conn, principal))
        resp = _create(app, pg_conn, EDITOR, tid, agent_type="workflow",
                       workflow_graph={"nodes": body["nodes"], "edges": body["edges"]})
        assert _status(resp) == 201, _json(resp)
        wf = WorkflowsRepository(pg_conn).get_by_id(_json(resp)["workflow_id"])
        assert wf["user_id"] == principal
        assert wf["created_by"] == EDITOR

    def test_an_editor_saves_a_team_graph_and_a_personal_source_is_refused(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        tid, principal = _team(pg_conn)
        wf = str(WorkflowsRepository(pg_conn).create(principal, "wf")["id"])
        _agent(pg_conn, principal, agent_type="workflow", workflow_id=wf)
        ok = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wf}", EDITOR,
                   json=self._body(source=_source(pg_conn, principal)), args=(wf,))
        assert _status(ok) == 200, _json(ok)
        refused = _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wf}", EDITOR,
                        json=self._body(source=_source(pg_conn, EDITOR)), args=(wf,))
        assert _status(refused) == 400
        assert _json(refused)["code"] == CODE_WORKSPACE_MISMATCH
