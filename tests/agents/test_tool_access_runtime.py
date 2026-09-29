"""Runtime resolution of team-shared tools (owner context, live grant checks)."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from docsgpt.agents.default_tools import resolve_tool_by_id
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.api.user.resource_access import set_settings
from docsgpt.security.encryption import encrypt_credentials
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import (
    UserToolPreferencesRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

OWNER = "alice"


def _tool(conn, name="read_webpage", config=None, status=True):
    return UserToolsRepository(conn).create(
        OWNER, name, config=config or {}, display_name=name, description="",
        actions=[{"name": "act", "active": True}], status=status,
    )


def _share(conn, tool_id, member, level="viewer"):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", OWNER)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), "tool", str(tool_id), OWNER, OWNER, access_level=level
    )
    return team


def _revoke(conn, team, tool_id):
    TeamResourceGrantsRepository(conn).revoke(str(team["id"]), "tool", str(tool_id))


@pytest.fixture
def use_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    monkeypatch.setattr("docsgpt.agents.tool_executor.db_readonly", _yield)
    return pg_conn


class TestResolveToolById:
    def test_owner_resolves(self, pg_conn):
        tool = _tool(pg_conn)
        row = resolve_tool_by_id(str(tool["id"]), OWNER, user_tools_repo=UserToolsRepository(pg_conn))
        assert row is not None and row["user_id"] == OWNER

    def test_grantee_with_use_in_own_resolves_owner_row(self, pg_conn):
        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "bob")
        row = resolve_tool_by_id(str(tool["id"]), "bob", user_tools_repo=UserToolsRepository(pg_conn))
        assert row is not None and row["user_id"] == OWNER

    def test_viewer_without_use_in_own_does_not_resolve(self, pg_conn):
        tool = _tool(pg_conn)
        _share(pg_conn, tool["id"], "bob")
        set_settings(pg_conn, "tool", str(tool["id"]), {"viewers_can_use_in_agents": False}, OWNER)
        repo = UserToolsRepository(pg_conn)
        assert resolve_tool_by_id(str(tool["id"]), "bob", user_tools_repo=repo) is None
        # Editors keep use_in_own when the viewer switch is off.
        _share(pg_conn, tool["id"], "carol", "editor")
        assert resolve_tool_by_id(str(tool["id"]), "carol", user_tools_repo=repo) is not None

    def test_stranger_does_not_resolve(self, pg_conn):
        tool = _tool(pg_conn)
        assert resolve_tool_by_id(str(tool["id"]), "eve", user_tools_repo=UserToolsRepository(pg_conn)) is None


class TestAgentToolsForOwner:
    def _agent(self, conn, owner, tool_ids):
        key = f"k-{uuid.uuid4().hex[:8]}"
        AgentsRepository(conn).create(owner, "A", "published", key=key, tools=[str(t) for t in tool_ids])
        return key

    def test_team_tool_on_grantees_agent_resolves_then_drops_on_revoke(self, use_conn):
        tool = _tool(use_conn)
        team = _share(use_conn, tool["id"], "bob")
        key = self._agent(use_conn, "bob", [tool["id"]])
        # Carol chats with Bob's agent: tools resolve under Bob, the agent owner.
        tools = ToolExecutor(user_api_key=key, user="carol")._get_tools_by_api_key(key)
        assert str(tool["id"]) in tools
        assert tools[str(tool["id"])]["user_id"] == OWNER
        _revoke(use_conn, team, tool["id"])
        assert ToolExecutor(user_api_key=key, user="carol")._get_tools_by_api_key(key) == {}

    def test_explicit_ids_path_checks_the_caller(self, use_conn):
        tool = _tool(use_conn)
        executor = ToolExecutor(user="bob")
        assert executor._get_tools_by_ids([str(tool["id"])]) == {}
        _share(use_conn, tool["id"], "bob")
        assert str(tool["id"]) in executor._get_tools_by_ids([str(tool["id"])])


class TestAgentlessChatTools:
    def test_includes_in_chat_team_tools(self, use_conn):
        own = _tool(use_conn, name="brave")
        shared = _tool(use_conn, name="read_webpage")
        team = _share(use_conn, shared["id"], "bob")
        UserToolsRepository(use_conn).create("bob", "cryptoprice", status=True)
        names = lambda: sorted(  # noqa: E731
            t["name"] for t in ToolExecutor(user="bob")._get_user_tools("bob").values() if t.get("user_id")
        )
        assert names() == ["cryptoprice"]  # sharing alone never adds to chats
        UserToolPreferencesRepository(use_conn).set_in_chat("bob", str(shared["id"]), True)
        assert names() == ["cryptoprice", "read_webpage"]
        set_settings(use_conn, "tool", str(shared["id"]), {"viewers_can_use_in_agents": False}, OWNER)
        assert names() == ["cryptoprice"]
        set_settings(use_conn, "tool", str(shared["id"]), {"viewers_can_use_in_agents": True}, OWNER)
        _revoke(use_conn, team, shared["id"])
        assert names() == ["cryptoprice"]
        assert own["id"]  # the owner's own tool never leaks into bob's chat


class TestRuntimeCredentials:
    def test_mcp_tool_loads_with_owner_identity(self, monkeypatch):
        executor = ToolExecutor(user="bob")
        mock_tm = Mock()
        monkeypatch.setattr("docsgpt.agents.tool_executor.ToolManager", lambda config: mock_tm)
        tool_data = {"id": str(uuid.uuid4()), "name": "mcp_tool", "user_id": OWNER, "config": {}}
        executor._get_or_load_tool(tool_data, "t1", "act")
        assert mock_tm.load_tool.call_args.kwargs["user_id"] == OWNER

    def test_api_tool_secret_values_decrypt_with_owner(self):
        from docsgpt.agents.tool_executor import api_tool_action_with_secrets

        blob = encrypt_credentials({"a": {"headers": {"X-Key": "sk"}}}, OWNER)
        tool_data = {
            "user_id": OWNER,
            "config": {
                "encrypted_action_secrets": blob,
                "actions": {"a": {"url": "https://x", "headers": {"properties": {
                    "X-Key": {"value": "", "has_value": True, "filled_by_llm": False}}}}},
            },
        }
        action = api_tool_action_with_secrets(tool_data, "a", "bob")
        assert action["headers"]["properties"]["X-Key"]["value"] == "sk"
        # The stored row is not mutated.
        assert tool_data["config"]["actions"]["a"]["headers"]["properties"]["X-Key"]["value"] == ""
