"""Tools on each person's own account ("member mode") in a team, and how a team's tool finds its account.

A team's member-mode tool has no connection of its own: it records the service it signs in to
(``connector_key``), and each run uses the invoker's own personal connection for that service. It never
uses a team's connection, never the team's principal, and never falls back to whoever created the tool.
An owner-mode tool on a team connection stops while that connection is paused.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

SERVER = "https://m.example.com"


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam is an Admin, eddie an Editor, vi a Viewer. Returns (team_id, principal)."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    members.add_member(tid, "alice", role="team_admin")
    members.add_member(tid, "adam", role="team_admin")
    members.add_member(tid, "eddie", role="team_editor")
    members.add_member(tid, "vi", role="team_viewer")
    return tid, principal_id(tid)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield), \
            patch.multiple("docsgpt.api.user.tools.routes", db_session=_yield, db_readonly=_yield), \
            patch("docsgpt.workspaces.context.db_readonly", _yield):
        yield


def _connection(conn, owner, provider="telegram", *, connected_by=None, server_url=None, auth_kind="api_key",
                status="connected", secrets=None):
    row = ConnectorSessionsRepository(conn).create(
        owner, provider if not provider.startswith("mcp:") else provider,
        connector_key=provider if not provider.startswith("mcp:") else "custom_mcp",
        auth_kind=auth_kind, account_label=f"{uuid.uuid4().hex[:6]}@example.com", server_url=server_url,
        status=status, connected_by=connected_by,
        encrypted_credentials=encrypt_json(secrets or {"credentials": {"token": f"{owner}-token"}}, owner),
    )
    return str(row["id"])


def _member_tool(owner, *, name="telegram", connector_key="telegram", config=None, connection_id=None):
    return {
        "id": str(uuid.uuid4()), "user_id": owner, "name": name, "config": config or {},
        "actions": [], "connection_id": connection_id, "credential_mode": "member",
        "connector_key": connector_key,
    }


class TestResolveMemberTool:
    def test_a_connectionless_member_tool_uses_the_invokers_own_connection(self, pg_conn, team):
        from docsgpt.connectors.resolve import MODE_MEMBER, resolve_connection

        _, principal = team
        _connection(pg_conn, principal, connected_by="adam")
        eddies = _connection(pg_conn, "eddie")
        with _db(pg_conn):
            resolved = resolve_connection(_member_tool(principal), "eddie")
        assert resolved is not None and resolved.available
        assert resolved.connection_id == eddies
        assert resolved.mode == MODE_MEMBER and resolved.delegated is False

    def test_never_the_teams_connection_when_the_invoker_has_none(self, pg_conn, team):
        from docsgpt.connectors.resolve import resolve_connection

        _, principal = team
        _connection(pg_conn, principal, connected_by="adam")
        with _db(pg_conn):
            resolved = resolve_connection(_member_tool(principal), "eddie")
        assert resolved is not None
        assert resolved.row is None and resolved.available is False
        assert resolved.connector_key == "telegram" and resolved.connector_name == "Telegram"

    def test_a_principal_invoker_gets_no_account(self, pg_conn, team):
        """A team's own run never uses the team's account for a tool meant to run on each person's."""
        from docsgpt.connectors.resolve import resolve_connection

        _, principal = team
        _connection(pg_conn, principal, connected_by="adam")
        with _db(pg_conn):
            resolved = resolve_connection(_member_tool(principal), principal)
        assert resolved is not None and resolved.row is None and resolved.available is False

    def test_a_principal_invoker_gets_no_account_with_a_connection_named_either(self, pg_conn, team):
        from docsgpt.connectors.resolve import resolve_connection

        _, principal = team
        teams = _connection(pg_conn, principal, connected_by="adam")
        with _db(pg_conn):
            resolved = resolve_connection(_member_tool(principal, connection_id=teams), principal)
        assert resolved.row is None and resolved.available is False

    def test_an_mcp_member_tool_matches_the_invokers_row_for_its_own_server(self, pg_conn, team):
        from docsgpt.connectors.resolve import resolve_connection

        _, principal = team
        _connection(pg_conn, "eddie", "mcp:https://other.example.com", server_url="https://other.example.com",
                    auth_kind="mcp_oauth", secrets={"tokens": {"access_token": "o"}})
        mine = _connection(pg_conn, "eddie", f"mcp:{SERVER}", server_url=SERVER, auth_kind="mcp_oauth",
                           secrets={"tokens": {"access_token": "e"}})
        tool = _member_tool(principal, name="mcp_tool", connector_key="custom_mcp",
                            config={"server_url": f"{SERVER}/mcp", "auth_type": "oauth"})
        with _db(pg_conn):
            resolved = resolve_connection(tool, "eddie")
        assert resolved.available and resolved.connection_id == mine

    def test_a_member_tool_without_a_recorded_service_never_runs_as_its_owner(self, pg_conn, team):
        """A member tool moved in before its service was recorded still resolves only the invoker's rows."""
        from docsgpt.connectors.resolve import resolve_connection

        _, principal = team
        _connection(pg_conn, principal, f"mcp:{SERVER}", connected_by="adam", server_url=SERVER,
                    auth_kind="mcp_oauth", secrets={"tokens": {"access_token": "team"}})
        tool = _member_tool(principal, name="mcp_tool", connector_key=None,
                            config={"server_url": f"{SERVER}/mcp", "auth_type": "oauth"})
        with _db(pg_conn):
            resolved = resolve_connection(tool, "eddie")
        assert resolved is not None and resolved.row is None

    def test_an_owner_mode_tool_without_a_connection_still_resolves_to_nothing(self, pg_conn):
        from docsgpt.connectors.resolve import resolve_connection

        tool = {"id": "t", "user_id": "alice", "name": "read_webpage", "config": {}, "connection_id": None,
                "credential_mode": "owner"}
        with _db(pg_conn):
            assert resolve_connection(tool, "alice") is None


class TestPausedTeamConnection:
    def _owner_tool(self, principal, cid):
        return {"id": str(uuid.uuid4()), "user_id": principal, "name": "telegram", "config": {},
                "actions": [], "connection_id": cid, "credential_mode": "owner"}

    def test_an_owner_mode_tool_stops_while_whoever_connected_it_is_gone(self, pg_conn, team):
        from docsgpt.connectors.resolve import CONNECTION_PAUSED, connection_stop_reason, resolve_connection

        tid, principal = team
        cid = _connection(pg_conn, principal, connected_by="adam")
        pg_conn.execute(text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'adam'"),
                        {"t": tid})
        tool = self._owner_tool(principal, cid)
        with _db(pg_conn):
            resolved = resolve_connection(tool, "eddie")
        assert resolved.available is False
        assert resolved.paused_for and resolved.paused_for["reason"] == "payer_left"
        assert connection_stop_reason(tool, resolved) == CONNECTION_PAUSED == "connection_paused"

    def test_an_unpaused_team_connection_runs(self, pg_conn, team):
        from docsgpt.connectors.resolve import connection_stop_reason, resolve_connection

        _, principal = team
        cid = _connection(pg_conn, principal, connected_by="adam")
        tool = self._owner_tool(principal, cid)
        with _db(pg_conn):
            resolved = resolve_connection(tool, "eddie")
        assert resolved.available and resolved.paused_for is None
        assert connection_stop_reason(tool, resolved) is None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _post_member(app, conn, user, body, team_id=None):
    from docsgpt.api.user.tools.routes import CreateMemberTool

    headers = {WORKSPACE_HEADER: team_id} if team_id else {}
    with _db(conn), app.test_request_context("/api/tools/member", method="POST", json=body, headers=headers):
        from flask import request

        request.decoded_token = {"sub": user}
        return CreateMemberTool().post()


class TestCreateMemberTool:
    def test_an_editor_adds_a_member_tool_to_the_team(self, app, pg_conn, team):
        tid, principal = team
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": "telegram"}, tid)
        assert resp.status_code == 200, resp.json
        row = UserToolsRepository(pg_conn).get(resp.json["id"], principal)
        assert row["name"] == "telegram"
        assert row["credential_mode"] == "member"
        assert row["connection_id"] is None
        assert row["connector_key"] == "telegram"
        assert row["created_by"] == "eddie"
        # A team tool's ``status`` is nobody's switch; the creator's chat preference is theirs.
        assert row["status"] is False
        assert str(row["id"]) in UserToolPreferencesRepository(pg_conn).list_in_chat_tool_ids("eddie")
        # No secret is stored on the tool, and none was copied from anyone's account.
        assert "encrypted_credentials" not in (row["config"] or {})

    def test_a_viewer_cannot_add_one(self, app, pg_conn, team):
        tid, _ = team
        resp = _post_member(app, pg_conn, "vi", {"connector_key": "telegram"}, tid)
        assert resp.status_code == 403
        assert resp.json["error"] == "workspace_role_required"

    def test_an_outsider_gets_404(self, app, pg_conn, team):
        tid, _ = team
        resp = _post_member(app, pg_conn, "mallory", {"connector_key": "telegram"}, tid)
        assert resp.status_code == 404

    def test_personal_needs_a_team(self, app, pg_conn):
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": "telegram"})
        assert resp.status_code == 400
        assert resp.json["error"] == "team_workspace_required"

    def test_an_admin_forcing_owner_mode_refuses_it(self, app, pg_conn, team):
        tid, _ = team
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="owner")
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": "telegram"}, tid)
        assert resp.status_code == 409
        assert resp.json["error"] == "member_mode_not_allowed"

    @pytest.mark.parametrize("key", ["nope", "google_drive", "custom_openapi"])
    def test_a_service_without_a_tool_is_refused(self, app, pg_conn, team, key):
        tid, _ = team
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": key}, tid)
        assert resp.status_code == 400

    def test_an_mcp_service_needs_the_creators_own_connection_first(self, app, pg_conn, team):
        tid, principal = team
        # The team's own sign-in does not count: actions are read with the creator's own account.
        _connection(pg_conn, principal, "mcp:notion", connected_by="adam", server_url="https://mcp.notion.com/mcp",
                    auth_kind="mcp_oauth", secrets={"tokens": {"access_token": "team"}})
        resp = _post_member(app, pg_conn, "eddie", {"connector_key": "mcp:notion"}, tid)
        assert resp.status_code == 409
        assert resp.json["error"] == "connect_personal_first"
        assert resp.json["connector_key"] == "mcp:notion"

    def test_an_mcp_service_reads_its_actions_with_the_creators_own_connection(self, app, pg_conn, team):
        tid, principal = team
        mine = ConnectorSessionsRepository(pg_conn).create(
            "eddie", "mcp:https://mcp.notion.com", connector_key="mcp:notion", auth_kind="mcp_oauth",
            account_label="eddie@example.com", server_url="https://mcp.notion.com/mcp",
            encrypted_credentials=encrypt_json({"tokens": {"access_token": "e"}}, "eddie"),
        )
        actions = [{"name": "search", "description": "Search", "parameters": {}}]
        with patch("docsgpt.connectors.mcp.discover_connection_actions", return_value=actions) as discover:
            resp = _post_member(app, pg_conn, "eddie", {"connector_key": "mcp:notion"}, tid)
        assert resp.status_code == 200, resp.json
        assert discover.call_args.args[0] == "eddie"
        assert str(discover.call_args.args[1]["id"]) == str(mine["id"])
        row = UserToolsRepository(pg_conn).get(resp.json["id"], principal)
        assert row["name"] == "mcp_tool" and row["connector_key"] == "mcp:notion"
        assert row["config"]["server_url"].startswith("https://mcp.notion.com")
        assert row["connection_id"] is None
        assert [a["name"] for a in row["actions"]] == ["search"]
        # Nothing of the creator's sign-in is copied onto the team's tool.
        assert "access_token" not in str(row["config"])

    def test_the_service_comes_only_from_connector_key(self, app, pg_conn, team):
        """A body can't name a connection or a stored service of its own."""
        tid, principal = team
        teams = _connection(pg_conn, principal, connected_by="adam")
        resp = _post_member(app, pg_conn, "eddie", {
            "connector_key": "telegram", "connection_id": teams, "config": {"connection_id": teams},
        }, tid)
        assert resp.status_code == 200
        row = UserToolsRepository(pg_conn).get(resp.json["id"], principal)
        assert row["connection_id"] is None
        assert "connection_id" not in (row["config"] or {})


class TestAvailableToolsInATeam:
    def _available(self, app, conn, user, tid):
        from docsgpt.api.user.tools.routes import AvailableTools

        with _db(conn), app.test_request_context("/api/available_tools", headers={WORKSPACE_HEADER: tid}):
            from flask import request

            request.decoded_token = {"sub": user}
            resp = AvailableTools().get()
        return {t["name"]: t for t in resp.json["data"]}

    def test_service_tools_are_listed_member_only(self, app, pg_conn, team):
        tid, _ = team
        tools = self._available(app, pg_conn, "eddie", tid)
        assert tools["telegram"]["group"] == "service"
        assert tools["telegram"]["member_only"] is True
        # A paired device still runs on one person's machine.
        assert "remote_device" not in tools

    def test_a_team_connection_for_the_service_lifts_member_only(self, app, pg_conn, team):
        tid, principal = team
        _connection(pg_conn, principal, connected_by="adam")
        tools = self._available(app, pg_conn, "eddie", tid)
        assert tools["telegram"]["member_only"] is False
        assert tools["ntfy"]["member_only"] is True

    def test_personal_tools_carry_no_member_only(self, app, pg_conn):
        from docsgpt.api.user.tools.routes import AvailableTools

        with _db(pg_conn), app.test_request_context("/api/available_tools"):
            from flask import request

            request.decoded_token = {"sub": "eddie"}
            resp = AvailableTools().get()
        tools = {t["name"]: t for t in resp.json["data"]}
        assert tools["telegram"].get("member_only") in (None, False)


class TestRunStateOfAMemberTool:
    def test_an_agent_page_says_it_runs_on_each_persons_account(self, pg_conn, team):
        from docsgpt.api.user.resource_access import NOTE_PER_USER_ACCOUNT, _tool_run_state

        _, principal = team
        with _db(pg_conn):
            reason, connection, run = _tool_run_state(pg_conn, _member_tool(principal), principal, [])
        assert reason is None
        assert run["note"] == NOTE_PER_USER_ACCOUNT and run["credential_mode"] == "member"
        assert connection == (None, "telegram", "Telegram")

    def test_a_forced_owner_mode_stops_it(self, pg_conn, team):
        """With every tool of the service on its owner's account, one with no account of its own can't run."""
        from docsgpt.api.user.resource_access import _tool_run_state

        _, principal = team
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="owner")
        with _db(pg_conn):
            reason, _, _ = _tool_run_state(pg_conn, _member_tool(principal), principal, [])
        assert reason == "connection_removed"
