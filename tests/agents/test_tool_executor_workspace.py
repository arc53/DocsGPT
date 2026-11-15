"""An agentless chat's tools per workspace, and how the executor names a team owner."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from docsgpt.agents.default_tools import resolve_tool_by_id
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.workspaces.principal import principal_id


def _team(conn, owner="alice", name="Ops", members=(("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _tool(conn, owner, name, status=False):
    return UserToolsRepository(conn).create(
        owner, name, config={}, display_name=name, description="",
        actions=[{"name": "act", "active": True}], status=status,
    )


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    monkeypatch.setattr("docsgpt.agents.tool_executor.db_readonly", _yield)
    return pg_conn


def _named(executor, user):
    """The stored (non-synthesized) tools of an agentless chat, by type."""
    return sorted(t["name"] for t in executor._get_user_tools(user).values() if t.get("user_id"))


def _has_defaults(executor, user):
    return any(not t.get("user_id") for t in executor._get_user_tools(user).values())


class TestContract:
    def test_workspace_team_id_starts_as_personal(self):
        assert ToolExecutor(user="eddie").workspace_team_id is None


class TestPersonalChat:
    def test_never_takes_a_team_tool_even_when_switched_on(self, use_conn):
        _tid, principal = _team(use_conn)
        team_tool = _tool(use_conn, principal, "read_webpage")
        _tool(use_conn, "eddie", "cryptoprice", status=True)
        UserToolPreferencesRepository(use_conn).set_in_chat("eddie", str(team_tool["id"]), True)
        assert _named(ToolExecutor(user="eddie"), "eddie") == ["cryptoprice"]


class TestTeamChat:
    def test_takes_the_teams_switched_on_tools_and_defaults_never_personal_ones(self, use_conn):
        tid, principal = _team(use_conn)
        other_tid, other_principal = _team(use_conn, name="Other", members=(("eddie", "team_viewer"),))
        on = _tool(use_conn, principal, "read_webpage")
        _tool(use_conn, principal, "brave", status=True)  # ``status`` means nothing on a team tool
        other = _tool(use_conn, other_principal, "duckduckgo")
        _tool(use_conn, "eddie", "cryptoprice", status=True)
        prefs = UserToolPreferencesRepository(use_conn)
        prefs.set_in_chat("eddie", str(on["id"]), True)
        prefs.set_in_chat("eddie", str(other["id"]), True)

        executor = ToolExecutor(user="eddie")
        executor.workspace_team_id = tid
        assert _named(executor, "eddie") == ["read_webpage"]
        assert _has_defaults(executor, "eddie")
        tools = [t for t in executor._get_user_tools("eddie").values() if t.get("user_id")]
        assert tools[0]["user_id"] == principal  # the principal's row: its secrets decrypt as the team

    def test_membership_is_checked_on_every_call(self, use_conn):
        tid, principal = _team(use_conn)
        on = _tool(use_conn, principal, "read_webpage")
        UserToolPreferencesRepository(use_conn).set_in_chat("vera", str(on["id"]), True)
        executor = ToolExecutor(user="vera")
        executor.workspace_team_id = tid
        assert _named(executor, "vera") == ["read_webpage"]
        TeamMembersRepository(use_conn).remove_member(tid, "vera")
        assert _named(executor, "vera") == []

    def test_a_team_the_caller_is_not_in_yields_no_stored_tools(self, use_conn):
        tid, principal = _team(use_conn)
        on = _tool(use_conn, principal, "read_webpage")
        UserToolPreferencesRepository(use_conn).set_in_chat("stranger", str(on["id"]), True)
        _tool(use_conn, "stranger", "cryptoprice", status=True)
        executor = ToolExecutor(user="stranger")
        executor.workspace_team_id = tid
        assert _named(executor, "stranger") == []


class TestResolveToolById:
    """``default_tools._resolve_shared_tool``: a team member's access is never ``owner`` and uses the role."""

    @pytest.mark.parametrize("member", ["eddie", "vera", "alice"])
    def test_members_resolve_the_principals_row(self, pg_conn, member):
        _tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, "read_webpage")
        row = resolve_tool_by_id(str(tool["id"]), member, user_tools_repo=UserToolsRepository(pg_conn))
        assert row is not None and row["user_id"] == principal

    def test_outsider_does_not_resolve(self, pg_conn):
        _tid, principal = _team(pg_conn)
        tool = _tool(pg_conn, principal, "read_webpage")
        assert resolve_tool_by_id(str(tool["id"]), "stranger", user_tools_repo=UserToolsRepository(pg_conn)) is None


class TestOwnerName:
    def test_a_team_owner_is_named_by_the_team(self, use_conn):
        _tid, principal = _team(use_conn)
        assert ToolExecutor._owner_name(principal) == "Team Ops"
