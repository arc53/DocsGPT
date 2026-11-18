"""What a run does with a team's tools that sign in somewhere.

A member-mode tool runs on each invoker's own account, so a team MCP tool must never run as the team
(its principal) and pick up a sign-in the team holds for the same server. An owner-mode tool on a team
connection runs only for the team's own members, in the app: never for an API key, widget, webhook or
public link, nor for another team the tool or its agent reached, and not while the connection is paused.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.user.resource_access import run_reader
from docsgpt.connectors import service
from docsgpt.security.encryption import encrypt_json
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id

SERVER = "https://m.example.com"


@pytest.fixture
def team(pg_conn):
    """Team Ops: alice owns it; adam is an Admin, eddie an Editor. Returns (team_id, principal)."""
    row = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(pg_conn)
    members.add_member(tid, "alice", role="team_admin")
    members.add_member(tid, "adam", role="team_admin")
    members.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch.multiple("docsgpt.connectors.service", db_session=_yield, db_readonly=_yield), \
            patch.multiple("docsgpt.connectors.resolve", db_readonly=_yield), \
            patch.multiple("docsgpt.agents.tool_executor", db_readonly=_yield):
        yield


def _mcp_row(conn, owner, *, connected_by=None, token="t"):
    row = ConnectorSessionsRepository(conn).create(
        owner, f"mcp:{SERVER}", connector_key="custom_mcp", auth_kind="mcp_oauth",
        account_label=f"{owner[:8]}@example.com", server_url=SERVER, connected_by=connected_by,
        encrypted_credentials=encrypt_json({"tokens": {"access_token": token}}, owner),
    )
    return str(row["id"])


def _telegram_row(conn, owner, *, connected_by=None):
    row = ConnectorSessionsRepository(conn).create(
        owner, "telegram", connector_key="telegram", auth_kind="api_key",
        account_label=f"{uuid.uuid4().hex[:6]}-bot", connected_by=connected_by,
        encrypted_credentials=encrypt_json({"credentials": {"token": "bot-token"}}, owner),
    )
    return str(row["id"])


def _member_mcp_tool(principal):
    return {
        "id": str(uuid.uuid4()), "user_id": principal, "name": "mcp_tool",
        "config": {"server_url": f"{SERVER}/mcp", "auth_type": "oauth"},
        "actions": [{"name": "search", "active": True, "require_approval": False}],
        "connection_id": None, "credential_mode": "member", "connector_key": "custom_mcp",
    }


def _owner_tool(principal, cid):
    return {
        "id": str(uuid.uuid4()), "user_id": principal, "name": "telegram", "config": {},
        "actions": [{"name": "telegram_send_message", "active": True, "require_approval": False}],
        "connection_id": cid, "credential_mode": "owner",
    }


def _executor(user, **flags):
    from docsgpt.agents.tool_executor import ToolExecutor

    return ToolExecutor(user=user, **flags)


def _pause(executor, tool, action="telegram_send_message"):
    call = SimpleNamespace(id="call-1", name=action, arguments="{}", thought_signature=None)
    with patch("docsgpt.agents.tool_executor.ToolActionParser") as parser:
        parser.return_value.parse_args.return_value = ("t1", action, {})
        return executor.check_pause({"t1": tool}, call, "OpenAILLM")


class TestMemberModeNeverRunsAsTheTeam:
    def test_a_team_member_tool_uses_the_members_own_sign_in_not_the_teams(self, pg_conn, team):
        """The team holds a sign-in for the same server; the member's own is the one used."""
        _, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam", token="team-token")
        eddies = _mcp_row(pg_conn, "eddie", token="eddie-token")
        tool = _member_mcp_tool(principal)
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            _executor("eddie")._get_or_load_tool(tool, "t1", "search")
        kwargs = manager.return_value.load_tool.call_args.kwargs
        # MCP tokens are read as ``user_id`` (by ``connection_id`` when set): the member, never the team.
        assert kwargs["user_id"] == "eddie"
        assert kwargs["tool_config"]["connection_id"] == eddies

    def test_without_their_own_sign_in_the_tool_is_not_loaded_at_all(self, pg_conn, team):
        _, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam", token="team-token")
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor("eddie")._get_or_load_tool(_member_mcp_tool(principal), "t1", "search")
        manager.return_value.load_tool.assert_not_called()

    def test_a_member_tool_whose_lookup_failed_is_not_loaded_as_its_owner(self, pg_conn, team):
        _, principal = team
        with _db(pg_conn), patch("docsgpt.connectors.resolve.resolve_connection", side_effect=RuntimeError), \
                patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor("eddie")._get_or_load_tool(_member_mcp_tool(principal), "t1", "search")
        manager.return_value.load_tool.assert_not_called()

    def test_the_team_itself_running_it_gets_no_account(self, pg_conn, team):
        _, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam", token="team-token")
        with _db(pg_conn), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor(principal, headless=True)._get_or_load_tool(_member_mcp_tool(principal), "t1", "search")
        manager.return_value.load_tool.assert_not_called()

    def test_without_their_own_sign_in_the_card_connects_a_personal_account(self, pg_conn, team):
        _, principal = team
        teams = _mcp_row(pg_conn, principal, connected_by="adam", token="team-token")
        with _db(pg_conn):
            pause = _pause(_executor("eddie"), _member_mcp_tool(principal), action="search")
        required = pause["connection_required"]
        assert required["status"] == "missing"
        assert required["owner_account"] is False
        # No one else's connection id: the card makes the member's own.
        assert "connection_id" not in required
        assert teams not in str(pause)

    def test_a_team_sign_in_is_never_read_without_its_id(self, pg_conn, team):
        """MCP tokens read for a team with no connection named find nothing, even when the team has one."""
        from docsgpt.agents.tools.mcp_tool import DBTokenStorage

        _, principal = team
        _mcp_row(pg_conn, principal, connected_by="adam", token="team-token")
        with _db(pg_conn):
            assert service.read_mcp_secrets(principal, SERVER) == {}
            assert DBTokenStorage(f"{SERVER}/mcp", principal)._fetch_session_data() == {}

    def test_a_person_still_reads_their_own_latest_sign_in(self, pg_conn):
        _mcp_row(pg_conn, "eddie", token="eddie-token")
        with _db(pg_conn):
            assert service.read_mcp_secrets("eddie", SERVER)["tokens"]["access_token"] == "eddie-token"


class TestTeamConnectionStaysInTheTeam:
    def test_a_member_in_the_app_runs_it(self, pg_conn, team):
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        with _db(pg_conn), run_reader("eddie"), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            pause = _pause(_executor("eddie"), tool)
            _executor("eddie")._get_or_load_tool(tool, "t1", "telegram_send_message")
        # The team's account is not theirs: a write asks first, as for any shared account.
        assert pause["pause_type"] == "awaiting_approval"
        assert manager.return_value.load_tool.call_args.kwargs["tool_config"]["token"] == "bot-token"

    @pytest.mark.parametrize("flags", [{"external_caller": True}, {"public_link_caller": True}])
    def test_an_api_key_widget_or_public_link_caller_never_runs_it(self, pg_conn, team, flags):
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        with _db(pg_conn), run_reader("eddie"), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            pause = _pause(_executor(principal, **flags), tool)
            with pytest.raises(service.ConnectionUnavailable):
                _executor(principal, **flags)._get_or_load_tool(tool, "t1", "telegram_send_message")
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "team_connection_outside"
        manager.return_value.load_tool.assert_not_called()

    def test_an_anonymous_reader_never_runs_it(self, pg_conn, team):
        """A webhook run is read by nobody known."""
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        with _db(pg_conn), run_reader(""), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            with pytest.raises(service.ConnectionUnavailable):
                _executor(principal, headless=True)._get_or_load_tool(tool, "t1", "telegram_send_message")
        manager.return_value.load_tool.assert_not_called()

    def test_a_receiving_teams_member_never_runs_it(self, pg_conn, team):
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        with _db(pg_conn), run_reader("zed"), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            pause = _pause(_executor("zed"), tool)
            with pytest.raises(service.ConnectionUnavailable):
                _executor("zed")._get_or_load_tool(tool, "t1", "telegram_send_message")
        assert pause["error_type"] == "team_connection_outside"
        manager.return_value.load_tool.assert_not_called()

    def test_a_schedule_set_by_a_member_runs_it(self, pg_conn, team):
        """A team agent's scheduled run executes as the team and is read by whoever set it."""
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        with _db(pg_conn), run_reader("eddie"), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            _executor(principal, headless=True)._get_or_load_tool(tool, "t1", "telegram_send_message")
        manager.return_value.load_tool.assert_called_once()

    def test_outside_callers_do_not_even_see_it(self, pg_conn, team):
        _, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        stored = {**tool, "id": str(uuid.uuid4()), "connection_id": None, "name": "read_webpage"}
        executor = _executor(principal, external_caller=True)
        executor.user_api_key = "key"
        with _db(pg_conn), run_reader(""), \
                patch.object(type(executor), "_get_tools_by_api_key", return_value={"a": tool, "b": stored}):
            tools = executor.get_tools()
        assert set(tools) == {"b"}

    def test_a_member_mode_team_tool_is_not_held_back_from_outside(self, pg_conn, team):
        """It runs on each caller's own account, never the team's."""
        _, principal = team
        tool = _member_mcp_tool(principal)
        executor = _executor("eddie", public_link_caller=True)
        executor.user_api_key = "key"
        with _db(pg_conn), run_reader("eddie"), \
                patch.object(type(executor), "_get_tools_by_api_key", return_value={"a": tool}):
            assert set(executor.get_tools()) == {"a"}


class TestPausedTeamConnection:
    def test_a_paused_connection_refuses_the_call_with_its_reason(self, pg_conn, team):
        tid, principal = team
        tool = _owner_tool(principal, _telegram_row(pg_conn, principal, connected_by="adam"))
        pg_conn.execute(text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = 'adam'"),
                        {"t": tid})
        with _db(pg_conn), run_reader("eddie"), patch("docsgpt.agents.tool_executor.ToolManager") as manager:
            pause = _pause(_executor("eddie"), tool)
            with pytest.raises(service.ConnectionUnavailable):
                _executor("eddie")._get_or_load_tool(tool, "t1", "telegram_send_message")
        # Nobody in the chat can fix it: no Connect card, a refusal that names why.
        assert pause["pause_type"] == "headless_denied"
        assert pause["error_type"] == "connection_paused"
        assert "connection_required" not in pause
        manager.return_value.load_tool.assert_not_called()
