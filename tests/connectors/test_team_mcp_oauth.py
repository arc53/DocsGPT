"""Signing in to an MCP server for a team, and a team's tool for a custom server on each person's account.

A team's MCP sign-in is owned by the team's principal and names the Admin who signed in. The sign-in runs
on the team's behalf but reports to that Admin alone: its events go to their stream, only they cancel it
or read how it went, and only they save a tool from it. The sign-in writes the team's connection only once
the server hands over tokens, by its id, and never creates a team row without the person who signed in.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.connectors import service
from docsgpt.security.encryption import decrypt_json, encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

SERVER = "https://mcp.example.com"
URL = f"{SERVER}/mcp"
PROVIDER = f"mcp:{SERVER}"


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam and ana are Admins, eddie an Editor, vi a Viewer. Returns (team_id, principal)."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    for user, role in (("alice", "team_admin"), ("adam", "team_admin"), ("ana", "team_admin"),
                       ("eddie", "team_editor"), ("vi", "team_viewer")):
        members.add_member(tid, user, role=role)
    return tid, principal_id(tid)


@pytest.fixture(autouse=True)
def _mcp_servers_allowed():
    """The admin switch and DNS are not what these tests are about; a server name resolves to a public address."""
    with patch("docsgpt.api.user.tools.mcp._mcp_policy_error", return_value=None), \
            patch("docsgpt.core.url_validation.resolve_hostname", return_value="104.18.0.1"):
        yield


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield), \
            patch.multiple("docsgpt.api.user.tools.mcp", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.api.user.tools.routes", db_session=_yield, db_readonly=_yield), \
            patch("docsgpt.workspaces.context.db_readonly", _yield):
        yield


def _call(app, conn, resource_cls, user, body, team_id=None, method="post", path="/api/x"):
    headers = {WORKSPACE_HEADER: team_id} if team_id else {}
    with _db(conn), app.test_request_context(path, method=method.upper(), json=body, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)()


def _config(**extra):
    return {"server_url": URL, "auth_type": "oauth", "transport_type": "http", "timeout": 30, **extra}


def _mcp_row(conn, owner, *, connected_by=None, server=SERVER, tokens=True, status="connected"):
    secrets = {"tokens": {"access_token": f"{owner}-at", "token_type": "Bearer"}} if tokens else {}
    row = ConnectorSessionsRepository(conn).create(
        owner, f"mcp:{server}", connector_key="custom_mcp", auth_kind="mcp_oauth", server_url=server,
        status=status, connected_by=connected_by,
        encrypted_credentials=encrypt_json(secrets, owner) if secrets else None,
    )
    return str(row["id"])


def _rows(conn, owner):
    return conn.execute(
        text("SELECT * FROM connector_sessions WHERE user_id = :u AND provider = :p"), {"u": owner, "p": PROVIDER},
    ).mappings().all()


def _audit_events(conn, event):
    return conn.execute(
        text("SELECT user_id, metadata FROM auth_events WHERE event = :e ORDER BY created_at"), {"e": event},
    ).fetchall()


def _test_route(app, conn, user, body, team_id):
    from docsgpt.api.user.tools.mcp import TestMCPServerConfig

    task = MagicMock(id="task-1")
    manager = MagicMock()
    with patch("docsgpt.api.user.tools.mcp.mcp_oauth_task") as oauth_task, \
            patch("docsgpt.api.user.tools.mcp.MCPOAuthManager", return_value=manager), \
            patch("docsgpt.api.user.tools.mcp.MCPTool") as tool_cls:
        oauth_task.delay.return_value = task
        resp = _call(app, conn, TestMCPServerConfig, user, body, team_id)
    return resp, oauth_task, manager, tool_cls


# ---------------------------------------------------------------------------
# Starting a team's sign-in
# ---------------------------------------------------------------------------


class TestStartTeamSignIn:
    def test_an_admin_starts_a_sign_in_the_team_owns_and_they_follow(self, app, pg_conn, team):
        tid, principal = team
        resp, oauth_task, manager, tool_cls = _test_route(
            app, pg_conn, "adam", {"config": _config(), "owner": "team"}, tid,
        )
        assert resp.status_code == 200, resp.json
        assert resp.json == {"success": False, "requires_oauth": True, "task_id": "task-1"}
        config, owner, actor = oauth_task.delay.call_args.args
        # The tokens are the team's; the events, the cancel and the status are the Admin's.
        assert owner == principal
        assert actor == "adam"
        assert "connection_id" not in config
        manager.register_task.assert_called_once_with("task-1", "adam")
        # A team's sign-in always starts fresh: no stored sign-in answers it.
        tool_cls.assert_not_called()
        # Nothing is written until the server hands over tokens.
        assert _rows(pg_conn, principal) == []

    def test_a_client_cannot_name_who_signed_in(self, app, pg_conn, team):
        tid, _ = team
        body = {"config": _config(oauth_connected_by="ana", connection_id="x"), "owner": "team"}
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", body, tid)
        assert resp.status_code == 200
        config, _owner, actor = oauth_task.delay.call_args.args
        assert actor == "adam"
        assert "oauth_connected_by" not in config and "connection_id" not in config

    @pytest.mark.parametrize("user,status,code", [
        ("eddie", 403, "workspace_role_required"),
        ("vi", 403, "workspace_role_required"),
        ("mallory", 404, None),
    ])
    def test_below_admin_or_outside_the_team_is_refused(self, app, pg_conn, team, user, status, code):
        tid, _ = team
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, user, {"config": _config(), "owner": "team"}, tid)
        assert resp.status_code == status
        if code:
            assert resp.json["error"] == code
        oauth_task.delay.assert_not_called()

    def test_personal_has_no_team_to_connect_for(self, app, pg_conn):
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", {"config": _config(), "owner": "team"}, None)
        assert resp.status_code == 400
        assert resp.json["error"] == "team_workspace_required"
        oauth_task.delay.assert_not_called()

    def test_without_owner_team_a_team_still_cant_sign_in(self, app, pg_conn, team):
        tid, _ = team
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", {"config": _config()}, tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "oauth_personal_only"
        oauth_task.delay.assert_not_called()

    def test_a_server_the_team_is_signed_in_to_is_reconnected_not_added_again(self, app, pg_conn, team):
        tid, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", {"config": _config(), "owner": "team"}, tid)
        assert resp.status_code == 409
        assert resp.json["error"] == "account_already_connected"
        assert resp.json["connection_id"] == existing
        oauth_task.delay.assert_not_called()

    def test_a_signed_out_row_of_the_team_is_signed_in_again(self, app, pg_conn, team):
        tid, principal = team
        _mcp_row(pg_conn, principal, connected_by="ana", tokens=False, status="disconnected")
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", {"config": _config(), "owner": "team"}, tid)
        assert resp.status_code == 200
        oauth_task.delay.assert_called_once()

    def test_a_reconnect_signs_in_to_that_connection(self, app, pg_conn, team):
        tid, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        body = {"config": _config(), "owner": "team", "connection_id": existing}
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", body, tid)
        assert resp.status_code == 200, resp.json
        config, owner, actor = oauth_task.delay.call_args.args
        assert config["connection_id"] == existing
        assert (owner, actor) == (principal, "adam")

    def test_a_reconnect_by_an_editor_is_refused(self, app, pg_conn, team):
        tid, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        body = {"config": _config(), "owner": "team", "connection_id": existing}
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "eddie", body, tid)
        assert resp.status_code == 403
        oauth_task.delay.assert_not_called()

    @pytest.mark.parametrize("whose", ["personal", "other_team"])
    def test_a_reconnect_names_only_this_teams_connection(self, app, pg_conn, team, whose):
        tid, _ = team
        if whose == "personal":
            other = _mcp_row(pg_conn, "adam")
        else:
            other_team = TeamsRepository(pg_conn).create("Other", f"o-{uuid.uuid4().hex[:6]}", "adam")
            TeamMembersRepository(pg_conn).add_member(str(other_team["id"]), "adam", role="team_admin")
            other = _mcp_row(pg_conn, principal_id(str(other_team["id"])), connected_by="adam")
        body = {"config": _config(), "owner": "team", "connection_id": other}
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", body, tid)
        assert resp.status_code == 404
        assert resp.json["error"] == "connection_not_found"
        oauth_task.delay.assert_not_called()

    def test_a_reconnect_keeps_its_own_server(self, app, pg_conn, team):
        tid, principal = team
        elsewhere = _mcp_row(pg_conn, principal, connected_by="ana", server="https://other.example.com")
        body = {"config": _config(), "owner": "team", "connection_id": elsewhere}
        resp, oauth_task, _m, _t = _test_route(app, pg_conn, "adam", body, tid)
        assert resp.status_code == 400
        oauth_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Saving a team's server from the sign-in
# ---------------------------------------------------------------------------


class _Manager:
    """Sign-in statuses by (task, person): each person reads only their own stream."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.asked = []

    def get_oauth_status(self, task_id, user_id):
        self.asked.append((task_id, user_id))
        return self.statuses.get((task_id, user_id), {"status": "not_found"})


def _save(app, conn, user, body, team_id, statuses):
    from docsgpt.api.user.tools.mcp import MCPServerSave

    manager = _Manager(statuses)
    with patch("docsgpt.api.user.tools.mcp.MCPOAuthManager", return_value=manager):
        resp = _call(app, conn, MCPServerSave, user, body, team_id)
    return resp, manager


def _completed(connection_id, tools=({"name": "search", "description": "Search"},), **extra):
    return {"status": "completed", "tools": list(tools), "tools_count": len(tools), "connection_id": connection_id,
            **extra}


class TestSaveTeamServer:
    def test_an_admin_saves_the_teams_server_from_their_sign_in(self, app, pg_conn, team):
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="adam")
        body = {"displayName": "Example", "config": _config(oauth_task_id="task-1"), "owner": "team", "status": True}
        resp, manager = _save(app, pg_conn, "adam", body, tid, {("task-1", "adam"): _completed(row)})
        assert resp.status_code == 200, resp.json
        # The status is read from the Admin's own stream, never the team's.
        assert manager.asked == [("task-1", "adam")]
        assert resp.json["connection_id"] == row
        tool = UserToolsRepository(pg_conn).get(resp.json["id"], principal)
        assert tool["connection_id"] == row
        assert tool["created_by"] == "adam"
        assert tool["credential_mode"] != "member"
        assert tool["status"] is False
        assert resp.json["id"] in UserToolPreferencesRepository(pg_conn).list_in_chat_tool_ids("adam")
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_added")
        assert actor == "adam" and meta["connection_id"] == row

    def test_another_admin_cannot_save_from_someone_elses_sign_in(self, app, pg_conn, team):
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="adam")
        body = {"displayName": "Example", "config": _config(oauth_task_id="task-1"), "owner": "team"}
        resp, manager = _save(app, pg_conn, "ana", body, tid, {("task-1", "adam"): _completed(row)})
        assert resp.status_code == 400
        assert manager.asked == [("task-1", "ana")]
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_a_sign_in_naming_someone_elses_connection_is_refused(self, app, pg_conn, team):
        """The completed sign-in must name this team's connection, signed in by the caller."""
        tid, principal = team
        personal = _mcp_row(pg_conn, "adam")
        other_admins = _mcp_row(pg_conn, principal, connected_by="ana", server="https://other.example.com")
        for named in (personal, other_admins, None):
            body = {"displayName": "Example", "config": _config(oauth_task_id="task-1"), "owner": "team"}
            resp, _ = _save(app, pg_conn, "adam", body, tid, {("task-1", "adam"): _completed(named)})
            assert resp.status_code == 400, named
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_a_sign_in_someone_else_now_holds_is_refused(self, app, pg_conn, team):
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="ana")
        body = {"displayName": "Example", "config": _config(oauth_task_id="task-1"), "owner": "team"}
        resp, _ = _save(app, pg_conn, "adam", body, tid, {("task-1", "adam"): _completed(row)})
        assert resp.status_code == 400
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_an_editor_cannot_save_a_teams_sign_in_server(self, app, pg_conn, team):
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="adam")
        body = {"displayName": "Example", "config": _config(oauth_task_id="task-1"), "owner": "team"}
        resp, manager = _save(app, pg_conn, "eddie", body, tid, {("task-1", "eddie"): _completed(row)})
        assert resp.status_code == 403
        assert manager.asked == []

    def test_a_team_save_needs_a_finished_sign_in(self, app, pg_conn, team):
        tid, principal = team
        body = {"displayName": "Example", "config": _config(), "owner": "team"}
        resp, _ = _save(app, pg_conn, "adam", body, tid, {})
        assert resp.status_code == 400
        assert UserToolsRepository(pg_conn).list_for_user(principal) == []

    def test_a_reconnect_updates_the_teams_tool_on_that_connection(self, app, pg_conn, team):
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="adam")
        tool = UserToolsRepository(pg_conn).create(
            principal, "mcp_tool", config=_config(), display_name="Example", custom_name="Example",
            actions=[], connection_id=row, created_by="ana",
        )
        body = {"displayName": "Example", "config": _config(oauth_task_id="task-2"), "owner": "team",
                "connection_id": row}
        statuses = {("task-2", "adam"): _completed(row, previous_connected_by="ana")}
        resp, _ = _save(app, pg_conn, "adam", body, tid, statuses)
        assert resp.status_code == 200, resp.json
        assert resp.json["id"] == str(tool["id"])
        tools = [t for t in UserToolsRepository(pg_conn).list_for_user(principal) if t["name"] == "mcp_tool"]
        assert len(tools) == 1
        assert [a["name"] for a in tools[0]["actions"]] == ["search"]
        [(actor, meta)] = _audit_events(pg_conn, "team.connection_reconnected")
        assert actor == "adam"
        assert meta["replaced"] is True and meta["previous_connected_by"] == "ana"

    def test_an_editors_new_server_never_overwrites_the_teams_tool_at_that_address(self, app, pg_conn, team):
        """A save with no id in a team adds a server: it never takes over the team's tool by its address."""
        tid, principal = team
        row = _mcp_row(pg_conn, principal, connected_by="adam")
        tool = UserToolsRepository(pg_conn).create(
            principal, "mcp_tool", config=_config(), display_name="Example", custom_name="Example",
            actions=[], connection_id=row, created_by="adam",
        )
        body = {"displayName": "Mine", "config": {**_config(auth_type="bearer"), "bearer_token": "eddie-token"}}
        discovered = MagicMock()
        discovered.get_actions_metadata.return_value = [{"name": "search", "description": "Search"}]
        with patch("docsgpt.api.user.tools.mcp.MCPTool", return_value=discovered):
            resp, _ = _save(app, pg_conn, "eddie", body, tid, {})

        assert resp.status_code == 200, resp.json
        assert resp.json["id"] != str(tool["id"])
        kept = UserToolsRepository(pg_conn).get(str(tool["id"]), principal)
        assert str(kept["connection_id"]) == row
        assert "encrypted_credentials" not in (kept["config"] or {})
        assert kept["display_name"] == "Example"


# ---------------------------------------------------------------------------
# The sign-in task
# ---------------------------------------------------------------------------


class _Capture:
    def __init__(self):
        self.calls = []

    def __call__(self, user_id, event_type, payload, scope=None):
        self.calls.append((user_id, event_type, payload, scope))


def _fake_tool_class(seen, connection_id="conn-1"):
    class _FakeMCPTool:
        def __init__(self, tool_config, user_id=None):
            seen.append((dict(tool_config), user_id))
            self._client = None
            self.oauth_connection_id = connection_id

        def _setup_client(self):
            self._client = object()

        async def _execute_with_client(self, name):
            return None

        def get_actions_metadata(self):
            return [{"name": "search"}]

    return _FakeMCPTool


def _run_task(monkeypatch, config, user_id, actor_id=None, connection_id="conn-1"):
    import sys
    import types

    from docsgpt import worker

    seen: list = []
    stub = types.ModuleType("docsgpt.agents.tools.mcp_tool")
    stub.MCPTool = _fake_tool_class(seen, connection_id)
    monkeypatch.setitem(sys.modules, "docsgpt.agents.tools.mcp_tool", stub)
    capture = _Capture()
    monkeypatch.setattr(worker, "publish_user_event", capture)
    task = MagicMock()
    task.request.id = "task-1"
    result = worker.mcp_oauth(task, config, user_id, actor_id)
    return result, capture, seen


class TestSignInTask:
    def test_a_team_sign_in_reports_to_the_admin_and_names_them(self, monkeypatch, team):
        _, principal = team
        result, capture, seen = _run_task(monkeypatch, _config(), principal, "adam")
        assert result["success"] is True
        assert capture.calls and {call[0] for call in capture.calls} == {"adam"}
        [(tool_config, owner)] = seen
        assert owner == principal
        assert tool_config["oauth_connected_by"] == "adam"
        completed = capture.calls[-1]
        assert completed[1] == "mcp.oauth.completed"
        assert completed[2]["connection_id"] == "conn-1"

    def test_a_team_sign_in_without_a_person_never_runs(self, monkeypatch, team):
        _, principal = team
        result, capture, seen = _run_task(monkeypatch, _config(), principal, None)
        assert result["success"] is False
        assert capture.calls == []
        assert seen == []

    def test_a_personal_sign_in_cannot_be_given_a_person(self, monkeypatch):
        result, capture, seen = _run_task(monkeypatch, _config(oauth_connected_by="ana"), "zoe")
        assert result["success"] is True
        assert {call[0] for call in capture.calls} == {"zoe"}
        [(tool_config, owner)] = seen
        assert owner == "zoe" and "oauth_connected_by" not in tool_config
        assert "connection_id" not in capture.calls[-1][2]


class _Redis:
    def __init__(self):
        self.data = {}

    def setex(self, key, _ttl, value):
        self.data[key] = value.encode() if isinstance(value, str) else value

    def get(self, key):
        return self.data.get(key)


class TestOnlyTheAdminFollowsTheirSignIn:
    def test_another_admin_cannot_cancel_it(self):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager

        manager = MCPOAuthManager(_Redis())
        manager.register_task("task-1", "adam")
        assert manager.cancel("task-1", "ana") is False
        assert manager.cancel("task-1", "adam") is True

    def test_the_cancel_route_answers_404_for_someone_elses_sign_in(self, app, pg_conn, team):
        from docsgpt.agents.tools.mcp_tool import MCPOAuthManager
        from docsgpt.api.user.tools.mcp import MCPOAuthCancel

        redis = _Redis()
        MCPOAuthManager(redis).register_task("task-1", "adam")
        with patch("docsgpt.api.user.tools.mcp.get_redis_instance", return_value=redis):
            resp = _call(app, pg_conn, MCPOAuthCancel, "ana", {"task_id": "task-1"}, team[0])
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Where a team's sign-in writes
# ---------------------------------------------------------------------------


def _storage(principal, connected_by=None, connection_id=None):
    from docsgpt.agents.tools.mcp_tool import DBTokenStorage

    return DBTokenStorage(server_url=URL, user_id=principal, connection_id=connection_id, connected_by=connected_by)


def _token():
    from mcp.shared.auth import OAuthToken

    return OAuthToken(access_token="new-at", token_type="Bearer", refresh_token="new-rt", expires_in=3600)


def _client_info():
    from mcp.shared.auth import OAuthClientInformationFull

    return OAuthClientInformationFull(client_id="cid", redirect_uris=["https://app.example/api/mcp_server/callback"])


class TestTeamTokenStorage:
    def test_the_team_row_is_written_once_tokens_arrive_and_names_the_admin(self, pg_conn, team):
        _, principal = team
        storage = _storage(principal, connected_by="adam")
        with _db(pg_conn):
            asyncio.run(storage.set_client_info(_client_info()))
            # An abandoned sign-in leaves nothing behind.
            assert _rows(pg_conn, principal) == []
            asyncio.run(storage.set_tokens(_token()))
        [row] = _rows(pg_conn, principal)
        assert row["connected_by"] == "adam"
        assert row["status"] == "connected"
        assert row["auth_kind"] == "mcp_oauth"
        assert storage.connection_id == str(row["id"])
        secrets = decrypt_json(row["encrypted_credentials"], principal)
        assert secrets["tokens"]["access_token"] == "new-at"
        assert secrets["client_info"]["client_id"] == "cid"

    def test_a_team_sign_in_never_reads_the_stored_one(self, pg_conn, team):
        _, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        storage = _storage(principal, connected_by="adam", connection_id=existing)
        with _db(pg_conn):
            assert asyncio.run(storage.get_tokens()) is None
            assert asyncio.run(storage.get_client_info()) is None

    def test_another_admins_sign_in_takes_a_paused_connection_over_in_place(self, pg_conn, team):
        tid, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        pg_conn.execute(
            text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'ana'"), {"t": tid},
        )
        storage = _storage(principal, connected_by="adam", connection_id=existing)
        with _db(pg_conn):
            asyncio.run(storage.set_tokens(_token()))
        [row] = _rows(pg_conn, principal)
        assert str(row["id"]) == existing
        assert row["connected_by"] == "adam"
        assert decrypt_json(row["encrypted_credentials"], principal)["tokens"]["access_token"] == "new-at"

    def test_a_sign_in_by_someone_below_admin_is_not_kept(self, pg_conn, team):
        _, principal = team
        existing = _mcp_row(pg_conn, principal, connected_by="ana")
        storage = _storage(principal, connected_by="eddie", connection_id=existing)
        with _db(pg_conn), pytest.raises(service.ConnectionUnavailable):
            asyncio.run(storage.set_tokens(_token()))
        [row] = _rows(pg_conn, principal)
        assert row["connected_by"] == "ana"
        assert decrypt_json(row["encrypted_credentials"], principal)["tokens"]["access_token"] == f"{principal}-at"


class TestUpdateMcpSecrets:
    def test_a_team_row_is_never_made_without_who_signed_in(self, pg_conn, team):
        _, principal = team
        with _db(pg_conn), pytest.raises(service.ConnectionUnavailable):
            service.update_mcp_secrets(principal, SERVER, {"tokens": {"access_token": "x"}})
        assert _rows(pg_conn, principal) == []

    def test_a_person_names_only_a_teams_row(self, pg_conn):
        with _db(pg_conn), pytest.raises(ValueError):
            service.update_mcp_secrets("zoe", SERVER, {"tokens": {"access_token": "x"}}, connected_by="ana")
        assert _rows(pg_conn, "zoe") == []

    def test_a_named_connection_must_be_the_teams_own(self, pg_conn, team):
        _, principal = team
        personal = _mcp_row(pg_conn, "adam")
        with _db(pg_conn), pytest.raises(service.ConnectionUnavailable):
            service.update_mcp_secrets(
                principal, SERVER, {"tokens": {"access_token": "x"}}, connection_id=personal, connected_by="adam",
            )
        assert ConnectorSessionsRepository(pg_conn).get(personal)["connected_by"] is None


# ---------------------------------------------------------------------------
# A team's tool for a custom sign-in server, on each person's own account
# ---------------------------------------------------------------------------


def _post_member(app, conn, user, body, team_id):
    from docsgpt.api.user.tools.routes import CreateMemberTool

    return _call(app, conn, CreateMemberTool, user, body, team_id)


class TestCustomServerMemberTool:
    def test_an_editor_adds_a_custom_server_read_with_their_own_sign_in(self, app, pg_conn, team):
        tid, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam")
        mine = _mcp_row(pg_conn, "eddie")
        actions = [{"name": "search", "description": "Search", "parameters": {}}]
        with patch("docsgpt.connectors.mcp.discover_server_actions", return_value=actions) as discover:
            resp = _post_member(app, pg_conn, "eddie", {"connector_key": "custom_mcp", "server_url": URL}, tid)
        assert resp.status_code == 200, resp.json
        assert discover.call_args.args[0] == "eddie"
        assert str(discover.call_args.args[1]["id"]) == mine
        row = UserToolsRepository(pg_conn).get(resp.json["id"], principal)
        assert row["name"] == "mcp_tool"
        assert row["credential_mode"] == "member"
        assert row["connector_key"] == "custom_mcp"
        assert row["connection_id"] is None
        assert row["config"]["server_url"] == URL and row["config"]["auth_type"] == "oauth"
        assert "access_token" not in str(row["config"])
        assert row["created_by"] == "eddie"

    def test_the_teams_sign_in_does_not_count(self, app, pg_conn, team):
        tid, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam")
        with patch("docsgpt.connectors.mcp.discover_server_actions") as discover:
            resp = _post_member(app, pg_conn, "eddie", {"connector_key": "custom_mcp", "server_url": URL}, tid)
        assert resp.status_code == 409
        assert resp.json["error"] == "connect_personal_first"
        assert resp.json["connector_key"] == "custom_mcp"
        discover.assert_not_called()

    def test_a_custom_server_needs_its_address(self, app, pg_conn, team):
        tid, _ = team
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": "custom_mcp"}, tid)
        assert resp.status_code == 400

    def test_a_blocked_address_is_refused(self, app, pg_conn, team):
        tid, _ = team
        resp = _post_member(
            app, pg_conn, "eddie", {"connector_key": "custom_mcp", "server_url": "http://127.0.0.1/mcp"}, tid,
        )
        assert resp.status_code == 400

    def test_a_viewer_cannot_add_one(self, app, pg_conn, team):
        tid, _ = team
        _mcp_row(pg_conn, "vi")
        resp = _post_member(app, pg_conn, "vi", {"connector_key": "custom_mcp", "server_url": URL}, tid)
        assert resp.status_code == 403


class TestMemberToolSignInStatus:
    def test_each_person_sees_their_own_sign_in_for_a_member_tool(self, app, pg_conn, team):
        from docsgpt.api.user.tools.mcp import MCPAuthStatus

        tid, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam")
        _mcp_row(pg_conn, "eddie")
        tool = UserToolsRepository(pg_conn).create(
            principal, "mcp_tool", config=_config(), display_name="Example", actions=[],
            credential_mode="member", connector_key="custom_mcp", created_by="eddie",
        )
        tool_id = str(tool["id"])
        eddie = _call(app, pg_conn, MCPAuthStatus, "eddie", None, tid, method="get")
        vi = _call(app, pg_conn, MCPAuthStatus, "vi", None, tid, method="get")
        assert eddie.json["statuses"][tool_id] == "connected"
        # The team's sign-in is not the Viewer's.
        assert vi.json["statuses"][tool_id] == "needs_auth"
