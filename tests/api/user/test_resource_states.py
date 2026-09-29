"""Run state of every resource attached to an agent or a workflow's nodes.

An agent (or workflow) runs its attached tools, sources and prompt as its
owner, or as the editor who sponsored them. When one stops being usable the
run drops it (a prompt falls back to the default) and the edit page says why:
``resource_states`` on the agent and workflow reads. The state comes from the
same checks the run uses, so a resource marked stopped is never used by a run
and one marked active is. Uses real repositories on ``pg_conn``.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    REASON_CANNOT_EDIT_HOLDER,
    REASON_CANNOT_EDIT_RESOURCE,
    REASON_CONNECTION_NEEDS_RECONNECT,
    REASON_CONNECTION_REMOVED,
    REASON_CONNECTOR_DISABLED,
    REASON_DELETED,
    REASON_OWNER_LOST_ACCESS,
    agent_refs,
    ref_access,
    resource_states,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.connector_policies import ConnectorPoliciesRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from tests.api.user.test_resource_sponsors import (
    EDITOR,
    OTHER,
    OWNER,
    VIEWER,
    _agent,
    _call,
    _confirm,
    _editor_resources,
    _patch_db,
    _put,
    _row,
    _status,
    _wf_body,
)


@pytest.fixture
def app():
    return Flask(__name__)


def _body(resp) -> dict:
    return resp[0] if isinstance(resp, tuple) else resp.get_json()


def _by_key(states) -> dict:
    return {s["key"]: s for s in states}


def _team_source(conn, team_id, level="viewer"):
    """OTHER's source, shared with the agent's team (OWNER a member)."""
    if not TeamMembersRepository(conn).is_member(OWNER, team_id):
        TeamMembersRepository(conn).add_member(team_id, OWNER)
    if not TeamMembersRepository(conn).is_member(OTHER, team_id):
        TeamMembersRepository(conn).add_member(team_id, OTHER)
    source = str(SourcesRepository(conn).create("team-src", user_id=OTHER)["id"])
    TeamResourceGrantsRepository(conn).grant(team_id, "source", source, OTHER, OTHER, access_level=level)
    return source


def _connection(conn, user=OWNER, status="connected", provider="telegram"):
    return str(conn.execute(
        text(
            "INSERT INTO connector_sessions (user_id, provider, connector_key, auth_kind, status, "
            "account_label) VALUES (:u, :p, :p, 'api_key', :s, :u) RETURNING id"
        ),
        {"u": user, "p": provider, "s": status},
    ).scalar())


def _states(conn, agent_id, viewer=OWNER):
    agent = _row(conn, agent_id)
    return _by_key(resource_states(conn, "agent", agent, agent_refs(agent), viewer))


def _get_agent(app, conn, agent_id, user):
    from docsgpt.api.user.agents.routes import GetAgent

    return _call(app, conn, GetAgent, "get", f"/api/get_agent?id={agent_id}", user).get_json()


# ---------------------------------------------------------------------------
# Reasons
# ---------------------------------------------------------------------------


class TestReasons:
    def test_owned_resources_are_active(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        source = str(SourcesRepository(pg_conn).create("mine", user_id=OWNER)["id"])
        prompt = str(PromptsRepository(pg_conn).create(OWNER, "p", "x")["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool], source_id=source, prompt_id=prompt)
        states = _states(pg_conn, agent_id)
        assert {k: s["state"] for k, s in states.items()} == {
            f"tool:{tool}": "active", f"source:{source}": "active", f"prompt:{prompt}": "active",
        }
        assert all(s["reason"] is None for s in states.values())

    def test_owner_lost_team_grant(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [source]})
        assert _states(pg_conn, agent_id)[f"source:{source}"]["state"] == "active"

        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        state = _states(pg_conn, agent_id)[f"source:{source}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_OWNER_LOST_ACCESS)
        # The owner is told to ask the source's owner, but not who that is:
        # they can no longer see the source.
        assert state["contact"] is None
        assert state["contact_role"] == "resource_owner"
        assert state["name"] == "team-src"

    def test_deleted_tool(self, pg_conn):
        """A deleted source or prompt leaves the agent by itself (FK, trigger); a tool id stays."""
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        UserToolsRepository(pg_conn).delete(tool, OWNER)
        state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_DELETED)
        assert state["contact"] is None
        assert state["name"] is None

    def test_sponsor_lost_the_agent(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        assert _states(pg_conn, agent_id)[f"tool:{tool}"]["state"] == "active"
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_CANNOT_EDIT_HOLDER)
        assert state["sponsor"] == {"user_id": EDITOR, "label": EDITOR}

    def test_sponsor_lost_the_resource(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "tool", tool, OTHER, OTHER, access_level="editor", target_user_id=EDITOR
        )
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "tool", tool, target_user_id=EDITOR)
        state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["reason"] == REASON_CANNOT_EDIT_RESOURCE

    def test_connection_needs_reconnect(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="reconnect_needed"),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_CONNECTION_NEEDS_RECONNECT)
        assert state["can_reconnect"] is True
        assert state["connection"]["connector_key"] == "telegram"
        assert state["connection"]["id"]
        assert state["contact"] is None

    def test_disconnected_account_needs_reconnect(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="disconnected"),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["reason"] == REASON_CONNECTION_NEEDS_RECONNECT

    def test_editor_is_told_whom_to_ask_to_reconnect(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="reconnect_needed"),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id, viewer=EDITOR)[f"tool:{tool}"]
        assert state["can_reconnect"] is False
        # The agent's owner is someone the editor knows.
        assert state["contact"] == {"user_id": OWNER, "label": OWNER}
        # Only the account's owner gets its connection id and own name.
        assert state["connection"] == {"id": None, "connector_key": "telegram", "name": "Telegram"}

    def test_connection_removed_but_tool_kept(self, pg_conn):
        from docsgpt.connectors import service

        cid = _connection(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "telegram", connection_id=cid)["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:id AS uuid)"),
                              {"id": cid}).mappings().one()
        service.remove_connection(pg_conn, dict(row), tools="keep")
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_CONNECTION_REMOVED)
        assert state["connection"]["name"] == "Telegram"
        assert state["can_reconnect"] is False

    def test_connector_disabled_by_admin(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            assert _states(pg_conn, agent_id)[f"tool:{tool}"]["state"] == "active"
            ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["reason"] == REASON_CONNECTOR_DISABLED

    def test_prompt_the_owner_lost(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        prompt = str(PromptsRepository(pg_conn).create(OTHER, "theirs", "x")["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "prompt", prompt, OTHER, OTHER)
        TeamMembersRepository(pg_conn).add_member(team_id, OWNER)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"prompt_id": prompt})
        assert _states(pg_conn, agent_id)[f"prompt:{prompt}"]["state"] == "active"
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "prompt", prompt)
        assert _states(pg_conn, agent_id)[f"prompt:{prompt}"]["reason"] == REASON_OWNER_LOST_ACCESS

    def test_presets_and_builtin_tools_are_not_listed(self, pg_conn):
        from docsgpt.agents.default_tools import loaded_builtin_agent_tools, synthesize_builtin_agent_tool

        builtin = next(iter(loaded_builtin_agent_tools()), None)
        tools = [str(synthesize_builtin_agent_tool(builtin)["id"])] if builtin else []
        agent_id, _ = _agent(pg_conn, tools=tools)
        assert _states(pg_conn, agent_id) == {}


class TestCredentials:
    """Whose account or credentials each running tool uses, for the share dialog."""

    _SEND = {"name": "send_message", "active": True}
    _READ = {"name": "get_updates", "active": True}

    def test_owner_mode_connection_names_the_account_holder(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn), actions=[self._SEND, self._READ],
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["state"] == "active"
        assert state["credential_mode"] == "owner"
        assert state["account"] == {"user_id": OWNER, "label": OWNER}
        assert state["connection"]["name"] == "Telegram"
        # A running tool's connection id is never sent.
        assert state["connection"]["id"] is None
        assert state["owner_credential_writes"] == ["send_message"]
        assert state["writes_allowed"] is True

    def test_member_mode_connection_has_no_account_holder(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn), credential_mode="member",
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["credential_mode"] == "member"
        assert state["account"] is None
        assert state["connection"]["connector_key"] == "telegram"

    def test_admin_forced_mode_wins(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="member")
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["credential_mode"] == "member"
        assert state["account"] is None

    def test_teammates_owner_mode_tool_uses_their_account(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        for member in (OWNER, OTHER):
            if not TeamMembersRepository(pg_conn).is_member(member, team_id):
                TeamMembersRepository(pg_conn).add_member(team_id, member)
        tool = str(UserToolsRepository(pg_conn).create(
            OTHER, "telegram", connection_id=_connection(pg_conn, user=OTHER),
        )["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"tools": [tool]})
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["state"] == "active"
        assert state["account"] == {"user_id": OTHER, "label": OTHER}

    def test_tool_without_stored_credentials(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        source = str(SourcesRepository(pg_conn).create("mine", user_id=OWNER)["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool], source_id=source)
        states = _states(pg_conn, agent_id)
        assert states[f"tool:{tool}"]["credential_mode"] is None
        assert states[f"tool:{tool}"]["account"] is None
        assert states[f"tool:{tool}"]["connection"] is None
        assert states[f"tool:{tool}"]["owner_credential_writes"] == []
        assert states[f"source:{source}"]["owner_credential_writes"] == []
        assert states[f"source:{source}"]["credential_mode"] is None

    def test_api_tool_write_that_sends_a_saved_key(self, pg_conn):
        actions = {
            "create_ticket": {
                "method": "POST",
                "headers": {"properties": {"Authorization": {"has_value": True}}},
            },
            "list_tickets": {
                "method": "GET",
                "headers": {"properties": {"Authorization": {"has_value": True}}},
            },
        }
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "api_tool", config={"actions": actions},
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["owner_credential_writes"] == ["create_ticket"]
        # The saved key is its owner's, whoever runs it.
        assert state["account"] == {"user_id": OWNER, "label": OWNER}
        assert state["credential_mode"] is None

    def test_mcp_server_signed_in_by_a_teammate(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        for member in (OWNER, OTHER):
            if not TeamMembersRepository(pg_conn).is_member(member, team_id):
                TeamMembersRepository(pg_conn).add_member(team_id, member)
        tool = str(UserToolsRepository(pg_conn).create(
            OTHER, "mcp_tool", config={"server_url": "https://mcp.example.com", "auth_type": "bearer"},
        )["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"tools": [tool]})
        assert _states(pg_conn, agent_id)[f"tool:{tool}"]["account"] == {"user_id": OTHER, "label": OTHER}

    def test_account_holder_the_reader_shares_no_team_with_is_not_named(self, pg_conn):
        """An editor outside the team that shares the tool learns only that it's someone else's."""
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        agent_id, _ = _agent(pg_conn)
        private = str(TeamsRepository(pg_conn).create("P", f"p-{uuid.uuid4().hex[:8]}", OTHER)["id"])
        TeamMembersRepository(pg_conn).add_member(private, OWNER)
        if not TeamMembersRepository(pg_conn).is_member(OTHER, private):
            TeamMembersRepository(pg_conn).add_member(private, OTHER)
        tool = str(UserToolsRepository(pg_conn).create(
            OTHER, "telegram", connection_id=_connection(pg_conn, user=OTHER),
        )["id"])
        TeamResourceGrantsRepository(pg_conn).grant(private, "tool", tool, OTHER, OTHER)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"tools": [tool]})
        with _patch_db(pg_conn):
            as_owner = _states(pg_conn, agent_id)[f"tool:{tool}"]
            as_editor = _states(pg_conn, agent_id, viewer=EDITOR)[f"tool:{tool}"]
        assert as_owner["account"] == {"user_id": OTHER, "label": OTHER}
        assert as_editor["state"] == "active"
        assert as_editor["account"] == {"user_id": None, "label": None}

    def test_admin_turned_writes_off(self, pg_conn):
        from docsgpt.storage.db.repositories.app_metadata import AppMetadataRepository
        from docsgpt.storage.db.repositories.connector_policies import allow_writes_key

        cid = _connection(pg_conn, provider="github")
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "mcp_tool", connection_id=cid,
            config={"server_url": "https://api.githubcopilot.com/mcp/", "auth_type": "bearer"},
            actions=[{"name": "create_issue", "active": True}],
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            assert _states(pg_conn, agent_id)[f"tool:{tool}"]["writes_allowed"] is True
            AppMetadataRepository(pg_conn).set(allow_writes_key("github"), "false")
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["state"] == "active"
        assert state["writes_allowed"] is False
        assert state["owner_credential_writes"] == []


class TestRunsAs:
    """Whose access a running item runs with: the owner's, or a live sponsor's."""

    def test_sponsored_item_runs_as_its_sponsor(self, app, pg_conn):
        agent_id, _ = _agent(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["runs_as"] == {"user_id": EDITOR, "label": EDITOR}

    def test_owners_own_item_runs_as_the_owner(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        assert _states(pg_conn, agent_id)[f"tool:{tool}"]["runs_as"] is None

    def test_owner_who_gains_access_runs_it_even_with_a_sponsor_on_record(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        source = str(SourcesRepository(pg_conn).create("editor-src", user_id=EDITOR)["id"])
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"sources": [source], "confirm_sponsor": _confirm(("source", source))})) == 200
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "source", source, EDITOR, EDITOR)
        if not TeamMembersRepository(pg_conn).is_member(OWNER, team_id):
            TeamMembersRepository(pg_conn).add_member(team_id, OWNER)
        state = _states(pg_conn, agent_id)[f"source:{source}"]
        assert state["state"] == "active"
        assert state["runs_as"] is None


class TestTakeOver:
    def test_editor_who_can_edit_the_item_may_take_over(self, pg_conn):
        """An owner-lost resource the reading editor can edit is theirs to take over."""
        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [source]})
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "source", source, OTHER, OTHER, access_level="editor", target_user_id=EDITOR
        )
        assert _states(pg_conn, agent_id, viewer=EDITOR)[f"source:{source}"]["can_confirm"] is True
        assert _states(pg_conn, agent_id, viewer=OWNER)[f"source:{source}"]["can_confirm"] is False

    def test_take_over_of_an_owner_lost_item_is_accepted(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [source]})
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "source", source, OTHER, OTHER, access_level="editor", target_user_id=EDITOR
        )
        resp = _put(app, pg_conn, agent_id, EDITOR,
                    {"sources": [source], "confirm_sponsor": _confirm(("source", source))})
        assert _status(resp) == 200, _body(resp)
        assert _states(pg_conn, agent_id)[f"source:{source}"]["state"] == "active"

    def test_agent_read_carries_the_audience_when_something_can_be_taken_over(self, app, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER, access_level="editor")
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=OTHER
        )
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        data = _get_agent(app, pg_conn, agent_id, OTHER)
        assert "sponsor_audience" not in data
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        data = _get_agent(app, pg_conn, agent_id, OTHER)
        assert _by_key(data["resource_states"])[f"tool:{tool}"]["can_confirm"] is True
        assert data["sponsor_audience"]["teams"] == ["T"]


# ---------------------------------------------------------------------------
# Who sees it
# ---------------------------------------------------------------------------


class TestVisibility:
    def _agent_with_stopped_tool(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        UserToolsRepository(pg_conn).delete(tool, OWNER)
        return agent_id, tool

    @pytest.mark.parametrize("user", [OWNER, EDITOR])
    def test_owner_and_editor_get_states(self, app, pg_conn, user):
        agent_id, tool = self._agent_with_stopped_tool(pg_conn)
        data = _get_agent(app, pg_conn, agent_id, user)
        assert _by_key(data["resource_states"])[f"tool:{tool}"]["reason"] == REASON_DELETED

    def test_viewer_gets_none(self, app, pg_conn):
        agent_id, _ = self._agent_with_stopped_tool(pg_conn)
        data = _get_agent(app, pg_conn, agent_id, VIEWER)
        assert data.get("resource_states", []) == []
        assert "sponsor_audience" not in data

    def test_shared_agent_view_carries_no_states(self, app, pg_conn):
        """The public-link read never carries run state."""
        from docsgpt.api.user.agents.sharing import SharedAgent

        agent_id, _ = self._agent_with_stopped_tool(pg_conn)
        token = uuid.uuid4().hex
        AgentsRepository(pg_conn).update_by_id(agent_id, {"shared": True, "shared_token": token})
        resp = _call(app, pg_conn, SharedAgent, "get", f"/api/shared_agent?token={token}", VIEWER)
        body = _body(resp)
        assert "resource_states" not in body
        assert "sponsor_audience" not in body


# ---------------------------------------------------------------------------
# Parity with the run
# ---------------------------------------------------------------------------


class TestParityWithRun:
    def test_stopped_source_is_not_retrieved(self, app, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        own = str(SourcesRepository(pg_conn).create("own", user_id=OWNER)["id"])
        AgentsRepository(pg_conn).update_by_id(agent_id, {"source_id": own, "extra_source_ids": [source]})
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        states = _states(pg_conn, agent_id)
        _, rows = authorized_agent_sources(pg_conn, _row(pg_conn, agent_id))
        used = {f"source:{r['id']}" for r in rows}
        assert used == {k for k, s in states.items() if s["type"] == "source" and s["state"] == "active"}
        assert f"source:{source}" not in used

    def test_stopped_tool_is_not_loaded(self, app, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        own = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, team_id = _agent(pg_conn, tools=[own])
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [own, tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        agent = _row(pg_conn, agent_id)
        states = _states(pg_conn, agent_id)
        with _patch_db(pg_conn):
            loaded = ToolExecutor(user_api_key=agent["key"], user=OWNER)._get_tools_by_api_key(agent["key"])
        assert {f"tool:{t}" for t in loaded} == {k for k, s in states.items() if s["state"] == "active"}

    def test_stopped_prompt_falls_back_to_default(self, app, pg_conn):
        from docsgpt.api.answer.services.stream_processor import authorized_prompt_id

        agent_id, team_id = _agent(pg_conn)
        _, prompt, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"prompt_id": prompt, "confirm_sponsor": _confirm(("prompt", prompt))})) == 200
        agent = _row(pg_conn, agent_id)
        with _patch_db(pg_conn):
            assert _states(pg_conn, agent_id)[f"prompt:{prompt}"]["state"] == "active"
            assert authorized_prompt_id(prompt, OWNER, agent) == prompt
            TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
            assert _states(pg_conn, agent_id)[f"prompt:{prompt}"]["state"] == "stopped"
            assert authorized_prompt_id(prompt, OWNER, _row(pg_conn, agent_id)) == "default"

    def test_ref_access_names_the_principal(self, app, pg_conn):
        own = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, _ = _agent(pg_conn, tools=[own])
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(_put(app, pg_conn, agent_id, EDITOR,
                            {"tools": [own, tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        agent = _row(pg_conn, agent_id)
        assert ref_access(pg_conn, "agent", agent, "tool", own).principal == OWNER
        assert ref_access(pg_conn, "agent", agent, "tool", tool).principal == EDITOR
        missing = str(uuid.uuid4())
        state = ref_access(pg_conn, "agent", agent, "tool", missing)
        assert (state.principal, state.reason) == (None, REASON_DELETED)


class TestRunLog:
    def test_dropped_source_logs_type_id_and_reason(self, pg_conn, caplog):
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        agent_id, _ = _agent(pg_conn)
        missing = str(uuid.uuid4())
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [missing]})
        with caplog.at_level(logging.INFO):
            authorized_agent_sources(pg_conn, _row(pg_conn, agent_id))
        [record] = [r for r in caplog.records if getattr(r, "event", None) == "resource_stopped"]
        assert (record.holder_type, record.holder_id) == ("agent", agent_id)
        assert (record.resource_type, record.resource_id, record.reason) == ("source", missing, REASON_DELETED)
        assert f"reason={REASON_DELETED}" in record.getMessage()

    def test_dropped_tool_logs_reason(self, pg_conn, caplog):
        from docsgpt.agents.tool_executor import ToolExecutor

        missing = str(uuid.uuid4())
        agent_id, _ = _agent(pg_conn, tools=[missing])
        agent = _row(pg_conn, agent_id)
        with _patch_db(pg_conn), caplog.at_level(logging.INFO):
            assert ToolExecutor(user_api_key=agent["key"], user=OWNER)._get_tools_by_api_key(agent["key"]) == {}
        records = [r for r in caplog.records if getattr(r, "event", None) == "resource_stopped"]
        assert [(r.resource_type, r.resource_id, r.reason) for r in records] == [("tool", missing, REASON_DELETED)]


    def test_dropped_node_tool_logs_reason(self, pg_conn, caplog):
        from docsgpt.agents.tool_executor import ToolExecutor

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        missing = str(uuid.uuid4())
        executor = ToolExecutor(user=VIEWER)
        executor.allowed_tool_ids = [missing]
        executor.tool_owner = OWNER
        executor.tool_holder = wf
        with _patch_db(pg_conn), caplog.at_level(logging.INFO):
            assert executor.get_tools() == {}
        [record] = [r for r in caplog.records if getattr(r, "event", None) == "resource_stopped"]
        assert (record.holder_type, record.holder_id) == ("workflow", str(wf["id"]))
        assert (record.resource_type, record.resource_id, record.reason) == ("tool", missing, REASON_DELETED)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class TestWorkflowStates:
    def _setup(self, pg_conn):
        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        agent_id, team_id = _agent(pg_conn, agent_type="workflow", workflow_id=str(wf["id"]))
        return str(wf["id"]), agent_id, team_id

    def _put(self, app, pg_conn, wid, user, body):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", user, json=body, args=(wid,))

    def _get(self, app, pg_conn, wid, user):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        return _call(app, pg_conn, WorkflowDetail, "get", f"/api/workflows/{wid}", user, args=(wid,))

    def test_node_states_on_the_workflow_read(self, app, pg_conn):
        wid, agent_id, team_id = self._setup(pg_conn)
        tool, _, source = _editor_resources(pg_conn)
        confirm = _confirm(("tool", tool), ("source", source))
        assert _status(self._put(app, pg_conn, wid, EDITOR, _wf_body(tool, source, confirm=confirm))) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        data = _body(self._get(app, pg_conn, wid, OWNER))["data"]
        states = _by_key(data["resource_states"])
        assert states[f"tool:{tool}"]["reason"] == REASON_CANNOT_EDIT_HOLDER
        assert states[f"source:{source}"]["reason"] == REASON_CANNOT_EDIT_HOLDER

    def test_workflow_engine_drops_what_the_read_marks_stopped(self, app, pg_conn):
        from types import SimpleNamespace

        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine

        wid, agent_id, team_id = self._setup(pg_conn)
        _, _, source = _editor_resources(pg_conn)
        own = str(SourcesRepository(pg_conn).create("own", user_id=OWNER)["id"])
        assert _status(self._put(app, pg_conn, wid, OWNER, _wf_body(source=own))) == 200
        body = _wf_body(source=source, confirm=_confirm(("source", source)))
        body["nodes"][1]["data"]["config"]["sources"] = [source, own]
        assert _status(self._put(app, pg_conn, wid, EDITOR, body)) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)

        engine = WorkflowEngine.__new__(WorkflowEngine)
        engine.agent = SimpleNamespace(
            workflow_row=WorkflowsRepository(pg_conn).get_by_id(wid),
            _resolve_owner_id=lambda: OWNER, user=OWNER, decoded_token={"sub": OWNER},
        )
        with _patch_db(pg_conn):
            allowed = engine._authorized_node_sources([source, own])
        states = _by_key(_body(self._get(app, pg_conn, wid, OWNER))["data"]["resource_states"])
        assert {f"source:{s}" for s in allowed} == {k for k, s in states.items() if s["state"] == "active"}

    def test_deleted_node_tool(self, app, pg_conn):
        wid, _, _ = self._setup(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        assert _status(self._put(app, pg_conn, wid, OWNER, _wf_body(tool))) == 200
        UserToolsRepository(pg_conn).delete(tool, OWNER)
        state = _by_key(_body(self._get(app, pg_conn, wid, OWNER))["data"]["resource_states"])[f"tool:{tool}"]
        assert state["reason"] == REASON_DELETED

    def test_sponsor_details_only_for_editors(self, app, pg_conn):
        """B: the workflow read gives sponsor details only to people who may edit."""
        from docsgpt.api.user import resource_access

        wid, _, _ = self._setup(pg_conn)
        tool, _, _ = _editor_resources(pg_conn)
        assert _status(self._put(app, pg_conn, wid, EDITOR,
                                 _wf_body(tool, confirm=_confirm(("tool", tool))))) == 200
        assert _body(self._get(app, pg_conn, wid, EDITOR))["data"]["resource_sponsors"]
        # A future role that may view but not edit reads no details.
        original = resource_access.holder_editable_by
        try:
            resource_access.holder_editable_by = lambda *a, **k: False
            data = _body(self._get(app, pg_conn, wid, EDITOR))["data"]
        finally:
            resource_access.holder_editable_by = original
        assert data["resource_sponsors"] == []
        assert data["resource_states"] == []
        assert data["ref_details"] == {"tools": [], "sources": []}

    def test_ref_details_hide_names_nobody_here_can_use(self, app, pg_conn):
        """A: a node naming someone else's resource doesn't reveal its name."""
        wid, _, _ = self._setup(pg_conn)
        secret = str(UserToolsRepository(pg_conn).create("sp-stranger", "api_tool", custom_name="Secret")["id"])
        own = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool", custom_name="Mine")["id"])
        body = _wf_body(tools=[own])
        assert _status(self._put(app, pg_conn, wid, OWNER, body)) == 200
        # Written straight to the graph, the way an older unchecked save left it.
        pg_conn.execute(
            text("UPDATE workflow_nodes SET config = jsonb_set(config, '{config,tools}', CAST(:t AS jsonb)) "
                 "WHERE workflow_id = CAST(:w AS uuid) AND node_type = 'agent'"),
            {"t": f'["{own}", "{secret}"]', "w": wid},
        )
        data = _body(self._get(app, pg_conn, wid, OWNER))["data"]
        names = {t["id"]: t.get("name") for t in data["ref_details"]["tools"]}
        assert own in names
        assert secret not in names
        state = _by_key(data["resource_states"])[f"tool:{secret}"]
        assert state["state"] == "stopped" and state["name"] is None

    def test_owner_save_refuses_a_node_ref_the_owner_cannot_use(self, app, pg_conn):
        wid, _, _ = self._setup(pg_conn)
        secret = str(UserToolsRepository(pg_conn).create("sp-stranger", "api_tool")["id"])
        resp = self._put(app, pg_conn, wid, OWNER, _wf_body(secret))
        assert _status(resp) == 403

    def test_owner_create_refuses_a_node_ref_the_owner_cannot_use(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowList

        secret = str(SourcesRepository(pg_conn).create("x", user_id="sp-stranger")["id"])
        resp = _call(app, pg_conn, WorkflowList, "post", "/api/workflows", OWNER, json=_wf_body(source=secret))
        assert _status(resp) == 403

    def test_workflow_audience_when_something_can_be_taken_over(self, app, pg_conn):
        wid, agent_id, team_id = self._setup(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OTHER, "api_tool")["id"])
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER, access_level="editor")
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=OTHER
        )
        assert _status(self._put(app, pg_conn, wid, EDITOR,
                                 _wf_body(tool, confirm=_confirm(("tool", tool))))) == 200
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)
        data = _body(self._get(app, pg_conn, wid, OTHER))["data"]
        assert _by_key(data["resource_states"])[f"tool:{tool}"]["can_confirm"] is True
        assert data["sponsor_audience"]["teams"] == ["T"]


# ---------------------------------------------------------------------------
# Connections as the run resolves them
# ---------------------------------------------------------------------------


class TestConnectionModes:
    def test_member_mode_tool_runs_on_each_persons_account(self, pg_conn):
        """The owner's own account doesn't decide a member-mode tool; each caller's does."""
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="reconnect_needed"),
            credential_mode="member",
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("active", None)
        assert state["note"] == "per_user_account"

    def test_admin_forced_member_mode_runs_on_each_persons_account(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="disconnected"),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", credential_mode="member")
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["note"]) == ("active", "per_user_account")

    def test_member_mode_tool_still_stops_when_the_service_is_off(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn), credential_mode="member",
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        ConnectorPoliciesRepository(pg_conn).upsert("telegram", enabled=False)
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["reason"] == REASON_CONNECTOR_DISABLED

    def test_owner_mode_tool_has_no_note(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["note"]) == ("active", None)

    @pytest.mark.parametrize("name", ["ntfy", "brave"])
    def test_service_tool_that_never_had_a_connection_runs(self, pg_conn, name):
        """A tokenless ntfy (or a legacy tool) has no connection and needs none."""
        tool = str(UserToolsRepository(pg_conn).create(OWNER, name, config={"server_url": "https://ntfy.sh"})["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("active", None)

    def test_removed_connection_is_remembered_on_the_kept_tool(self, pg_conn):
        from docsgpt.connectors import service

        cid = _connection(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "telegram", connection_id=cid)["id"])
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:id AS uuid)"),
                              {"id": cid}).mappings().one()
        service.remove_connection(pg_conn, dict(row), tools="keep")
        kept = UserToolsRepository(pg_conn).get_any(tool, OWNER)
        assert kept["connection_id"] is None
        assert kept["config"]["removed_connection"] == "telegram"


# ---------------------------------------------------------------------------
# Whom to ask, without naming strangers
# ---------------------------------------------------------------------------


class TestContact:
    def _owners_grant_only(self, conn, team_id, resource_type, resource_id):
        """Share OTHER's resource with OWNER alone, so the agent's editors can't see it."""
        for member in (OWNER, OTHER):
            if not TeamMembersRepository(conn).is_member(member, team_id):
                TeamMembersRepository(conn).add_member(team_id, member)
        TeamResourceGrantsRepository(conn).grant(
            team_id, resource_type, resource_id, OTHER, OTHER, target_user_id=OWNER
        )

    def test_editor_who_can_see_the_item_is_told_its_owner(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [source]})
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "source", source, OTHER, OTHER, target_user_id=EDITOR
        )
        state = _states(pg_conn, agent_id, viewer=EDITOR)[f"source:{source}"]
        assert state["contact"] == {"user_id": OTHER, "label": OTHER}
        assert state["contact_role"] == "resource_owner"

    def test_editor_who_cannot_see_the_item_gets_no_identity(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        tool = str(UserToolsRepository(pg_conn).create(
            OTHER, "telegram", connection_id=_connection(pg_conn, user=OTHER, status="reconnect_needed"),
        )["id"])
        self._owners_grant_only(pg_conn, team_id, "tool", tool)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"tools": [tool]})
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id, viewer=EDITOR)[f"tool:{tool}"]
        assert state["reason"] == REASON_CONNECTION_NEEDS_RECONNECT
        assert state["contact"] is None
        assert state["contact_role"] == "resource_owner"
        assert state["connection"]["id"] is None

    def test_old_graph_naming_a_strangers_tool_reveals_nobody(self, app, pg_conn):
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        wid = str(wf["id"])
        _agent(pg_conn, agent_type="workflow", workflow_id=wid)
        stranger_tool = str(UserToolsRepository(pg_conn).create("sp-stranger", "api_tool")["id"])
        own = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        assert _status(_call(app, pg_conn, WorkflowDetail, "put", f"/api/workflows/{wid}", OWNER,
                             json=_wf_body(own), args=(wid,))) == 200
        pg_conn.execute(
            text("UPDATE workflow_nodes SET config = jsonb_set(config, '{config,tools}', CAST(:t AS jsonb)) "
                 "WHERE workflow_id = CAST(:w AS uuid) AND node_type = 'agent'"),
            {"t": f'["{stranger_tool}"]', "w": wid},
        )
        data = _body(_call(app, pg_conn, WorkflowDetail, "get", f"/api/workflows/{wid}", OWNER, args=(wid,)))
        state = _by_key(data["data"]["resource_states"])[f"tool:{stranger_tool}"]
        assert state["reason"] == REASON_OWNER_LOST_ACCESS
        assert state["contact"] is None
        assert state["name"] is None


class TestNamingPeople:
    """One rule names every person on the page: only people the reader knows."""

    def test_contact_the_reader_shares_no_team_with_is_not_named(self, pg_conn):
        """Seeing the item isn't enough: its owner left every team the reader is in."""
        agent_id, team_id = _agent(pg_conn)
        source = _team_source(pg_conn, team_id)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"extra_source_ids": [source]})
        TeamResourceGrantsRepository(pg_conn).revoke(team_id, "source", source)
        TeamResourceGrantsRepository(pg_conn).grant(
            team_id, "source", source, OTHER, OTHER, target_user_id=EDITOR
        )
        TeamMembersRepository(pg_conn).remove_member(team_id, OTHER)
        state = _states(pg_conn, agent_id, viewer=EDITOR)[f"source:{source}"]
        assert state["reason"] == REASON_OWNER_LOST_ACCESS
        assert state["contact"] is None
        assert state["contact_role"] == "resource_owner"

    def test_account_of_a_teammate_whose_tool_the_reader_cannot_see_is_not_named(self, pg_conn):
        agent_id, team_id = _agent(pg_conn)
        TeamMembersRepository(pg_conn).add_member(team_id, OWNER)
        TeamMembersRepository(pg_conn).add_member(team_id, OTHER)
        tool = str(UserToolsRepository(pg_conn).create(
            OTHER, "telegram", connection_id=_connection(pg_conn, user=OTHER),
        )["id"])
        TeamResourceGrantsRepository(pg_conn).grant(team_id, "tool", tool, OTHER, OTHER, target_user_id=OWNER)
        AgentsRepository(pg_conn).update_by_id(agent_id, {"tools": [tool]})
        with _patch_db(pg_conn):
            as_owner = _states(pg_conn, agent_id)[f"tool:{tool}"]
            as_editor = _states(pg_conn, agent_id, viewer=EDITOR)[f"tool:{tool}"]
        assert as_owner["account"] == {"user_id": OTHER, "label": OTHER}
        assert as_editor["account"] == {"user_id": None, "label": None}

    def test_a_sponsor_from_another_team_is_named_to_the_owner_only(self, app, pg_conn):
        from docsgpt.api.user.resource_access import sponsor_details
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        second = "sp-editor-2"
        agent_id, _ = _agent(pg_conn)
        other_team = str(TeamsRepository(pg_conn).create("T2", f"t2-{uuid.uuid4().hex[:8]}", OWNER)["id"])
        TeamMembersRepository(pg_conn).add_member(other_team, second)
        TeamResourceGrantsRepository(pg_conn).grant(
            other_team, "agent", agent_id, OWNER, OWNER, access_level="editor", target_user_id=second
        )
        tool = str(UserToolsRepository(pg_conn).create(second, "api_tool")["id"])
        assert _status(_put(app, pg_conn, agent_id, second,
                            {"tools": [tool], "confirm_sponsor": _confirm(("tool", tool))})) == 200
        agent = _row(pg_conn, agent_id)
        as_owner = _states(pg_conn, agent_id)[f"tool:{tool}"]
        as_editor = _states(pg_conn, agent_id, viewer=EDITOR)[f"tool:{tool}"]
        assert as_owner["runs_as"] == {"user_id": second, "label": second}
        assert as_owner["sponsor"] == {"user_id": second, "label": second}
        assert as_editor["runs_as"] == {"user_id": None, "label": None}
        assert as_editor["sponsor"] == {"user_id": None, "label": None}
        [owner_detail] = sponsor_details(pg_conn, "agent", agent, viewer=OWNER)
        [editor_detail] = sponsor_details(pg_conn, "agent", agent, viewer=EDITOR)
        assert (owner_detail["user_id"], owner_detail["label"]) == (second, second)
        assert (editor_detail["user_id"], editor_detail["label"]) == (None, None)
        assert editor_detail["active"] is True


class TestRemovedConnectionMarker:
    def test_removed_connection_without_a_catalog_key_is_still_marked(self, pg_conn):
        from docsgpt.connectors import service

        cid = str(pg_conn.execute(
            text(
                "INSERT INTO connector_sessions (user_id, provider, auth_kind, status) "
                "VALUES (:u, 'legacy-service', 'api_key', 'connected') RETURNING id"
            ),
            {"u": OWNER},
        ).scalar())
        tool = str(UserToolsRepository(pg_conn).create(OWNER, "telegram", connection_id=cid)["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        row = pg_conn.execute(text("SELECT * FROM connector_sessions WHERE id = CAST(:id AS uuid)"),
                              {"id": cid}).mappings().one()
        service.remove_connection(pg_conn, dict(row), tools="keep")
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("stopped", REASON_CONNECTION_REMOVED)
        assert state["connection"]["name"] == "Telegram"

    def test_kept_tool_given_its_own_credentials_runs(self, pg_conn):
        from docsgpt.security.encryption import encrypt_credentials

        tool = str(UserToolsRepository(pg_conn).create(OWNER, "telegram", config={
            "removed_connection": "telegram",
            "encrypted_credentials": encrypt_credentials({"token": "t"}, OWNER),
        })["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert (state["state"], state["reason"]) == ("active", None)

    def test_a_stopped_tool_says_nothing_about_how_it_runs(self, pg_conn):
        tool = str(UserToolsRepository(pg_conn).create(
            OWNER, "telegram", connection_id=_connection(pg_conn, status="reconnect_needed"),
        )["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])
        with _patch_db(pg_conn):
            state = _states(pg_conn, agent_id)[f"tool:{tool}"]
        assert state["reason"] == REASON_CONNECTION_NEEDS_RECONNECT
        assert (state["note"], state["credential_mode"], state["account"]) == (None, None, None)
        assert (state["owner_credential_writes"], state["writes_allowed"]) == ([], True)


# ---------------------------------------------------------------------------
# Reads never fail on run state
# ---------------------------------------------------------------------------


class TestBestEffort:
    def test_agent_read_survives_a_state_error(self, app, pg_conn, monkeypatch):
        from docsgpt.api.user.agents import routes

        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        agent_id, _ = _agent(pg_conn, tools=[tool])

        def _boom(*_a, **_k):
            raise RuntimeError("state failed")

        monkeypatch.setattr(routes, "resource_states", _boom)
        data = _get_agent(app, pg_conn, agent_id, OWNER)
        assert data["resource_states"] == []
        assert data["name"] == "Shared"

    def test_workflow_read_survives_a_state_error(self, app, pg_conn, monkeypatch):
        from docsgpt.api.user.workflows import routes
        from docsgpt.api.user.workflows.routes import WorkflowDetail

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        wid = str(wf["id"])
        _agent(pg_conn, agent_type="workflow", workflow_id=wid)

        def _boom(*_a, **_k):
            raise RuntimeError("state failed")

        monkeypatch.setattr(routes, "resource_states", _boom)
        resp = _call(app, pg_conn, WorkflowDetail, "get", f"/api/workflows/{wid}", OWNER, args=(wid,))
        assert _status(resp) == 200
        assert _body(resp)["data"]["resource_states"] == []

    def test_resolves_are_cached_within_a_read(self, pg_conn, monkeypatch):
        from docsgpt.api.user import resource_access

        tool = str(UserToolsRepository(pg_conn).create(OWNER, "api_tool")["id"])
        calls = []
        real = resource_access._resolve_uncached

        def _spy(*args):
            calls.append(args[1:])
            return real(*args)

        monkeypatch.setattr(resource_access, "_resolve_uncached", _spy)
        with resource_access.cached_resolves():
            first = resource_access.resolve(pg_conn, "tool", tool, OWNER)
            second = resource_access.resolve(pg_conn, "tool", tool.upper(), OWNER)
        assert first == second
        assert len(calls) == 1
        # Outside a read nothing is cached: a revoked grant denies at once.
        resource_access.resolve(pg_conn, "tool", tool, OWNER)
        assert len(calls) == 2
