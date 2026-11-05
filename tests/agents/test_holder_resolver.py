"""One runtime resolver for the tools and sources an agent or a workflow node runs with.

``resolve_holder_tools`` and ``authorized_holder_sources`` (resource_access)
back the agent run (ToolExecutor by key or id, stream_processor, the
headless runner) and the workflow node run (ToolExecutor's scoped ids, the
engine's node sources) alike. Real repositories on ``pg_conn``.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from docsgpt.agents.default_tools import default_tool_id
from docsgpt.api.user.resource_access import (
    REASON_CANNOT_EDIT_HOLDER,
    authorized_holder_sources,
    resolve_holder_tools,
    sponsor_key,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

from tests.api.user.test_resource_sponsors import EDITOR, OWNER, _agent, _editor_resources, _patch_db, _row


def _owner_tool(conn, name="api_tool"):
    return str(UserToolsRepository(conn).create(OWNER, name)["id"])


def _sponsored_agent(conn, tool=None, source=None):
    """The owner's agent, shared with EDITOR as editor, holding EDITOR's tool and source as their sponsor."""
    sponsors = {}
    if tool:
        sponsors[sponsor_key("tool", tool)] = EDITOR
    if source:
        sponsors[sponsor_key("source", source)] = EDITOR
    agent_id, team_id = _agent(conn, tools=[tool] if tool else [], source_id=source)
    AgentsRepository(conn).update(agent_id, OWNER, {"resource_sponsors": sponsors})
    return _row(conn, agent_id), team_id


def _revoke_editor(conn, team_id, agent_id):
    TeamResourceGrantsRepository(conn).revoke(team_id, "agent", agent_id, target_user_id=EDITOR)


class TestResolveHolderTools:
    def test_owner_tools_resolve_as_the_owner(self, pg_conn):
        tool = _owner_tool(pg_conn)
        agent_id, _ = _agent(pg_conn, tools=[tool])
        tools = resolve_holder_tools(pg_conn, "agent", _row(pg_conn, agent_id), [tool])
        assert {tid: row["user_id"] for tid, row in tools.items()} == {tool: OWNER}

    def test_sponsor_fallback_then_revoked(self, pg_conn, caplog):
        tool, _, _ = _editor_resources(pg_conn)
        agent, team_id = _sponsored_agent(pg_conn, tool=tool)
        tools = resolve_holder_tools(pg_conn, "agent", agent, [tool])
        assert {tid: row["user_id"] for tid, row in tools.items()} == {tool: EDITOR}

        _revoke_editor(pg_conn, team_id, str(agent["id"]))
        with caplog.at_level(logging.INFO):
            assert resolve_holder_tools(pg_conn, "agent", agent, [tool]) == {}
        [record] = [r for r in caplog.records if getattr(r, "event", None) == "resource_stopped"]
        assert (record.resource_id, record.reason) == (tool, REASON_CANNOT_EDIT_HOLDER)

    def test_a_tool_the_owner_lost_is_dropped(self, pg_conn):
        tool, _, _ = _editor_resources(pg_conn)  # EDITOR's tool, never shared and not sponsored
        agent_id, _ = _agent(pg_conn, tools=[tool])
        assert resolve_holder_tools(pg_conn, "agent", _row(pg_conn, agent_id), [tool]) == {}

    @pytest.mark.parametrize("holder_type", ["agent", "workflow"])
    def test_headless_drops_chat_only_tools(self, pg_conn, holder_type):
        scheduler = default_tool_id("scheduler")
        holder = {"id": None, "user_id": OWNER}
        assert scheduler in resolve_holder_tools(pg_conn, holder_type, holder, [scheduler])
        assert resolve_holder_tools(pg_conn, holder_type, holder, [scheduler], headless=True) == {}

    def test_workflow_only_builtins_run_only_in_workflow_nodes(self, pg_conn):
        read_document = default_tool_id("read_document")
        holder = {"id": None, "user_id": OWNER}
        assert resolve_holder_tools(pg_conn, "agent", holder, [read_document]) == {}
        assert read_document in resolve_holder_tools(pg_conn, "workflow", holder, [read_document])

    @pytest.mark.parametrize("holder_type", ["agent", "workflow"])
    def test_server_attached_tools_are_never_a_saved_choice(self, pg_conn, holder_type):
        check_job = default_tool_id("check_job")
        assert resolve_holder_tools(pg_conn, holder_type, {"id": None, "user_id": OWNER}, [check_job]) == {}


class TestAuthorizedHolderSources:
    def test_owner_sponsor_revoked_and_duplicates(self, pg_conn):
        own = str(SourcesRepository(pg_conn).create("own", user_id=OWNER)["id"])
        _, _, editor_source = _editor_resources(pg_conn)
        agent, team_id = _sponsored_agent(pg_conn, source=editor_source)
        refs = [own, editor_source, own.upper(), None, ""]
        assert authorized_holder_sources(pg_conn, "agent", agent, refs) == [own, editor_source]
        _revoke_editor(pg_conn, team_id, str(agent["id"]))
        assert authorized_holder_sources(pg_conn, "agent", agent, refs) == [own]


class TestRuntimeCallersShareIt:
    """The agent run and the workflow node run reach the same resolver."""

    def test_agent_run_by_key_and_node_scoped_ids(self, pg_conn):
        from docsgpt.agents.tool_executor import ToolExecutor

        tool, _, _ = _editor_resources(pg_conn)
        agent, _ = _sponsored_agent(pg_conn, tool=tool)
        with _patch_db(pg_conn):
            by_key = ToolExecutor(user_api_key=agent["key"], user="someone")._get_tools_by_api_key(agent["key"])
        assert {tid: row["user_id"] for tid, row in by_key.items()} == {tool: EDITOR}

        wf = WorkflowsRepository(pg_conn).create(OWNER, "wf")
        WorkflowsRepository(pg_conn).update(
            str(wf["id"]), OWNER, {"resource_sponsors": {sponsor_key("tool", tool): EDITOR}}
        )
        AgentsRepository(pg_conn).update(str(agent["id"]), OWNER, {"workflow_id": str(wf["id"])})
        node = ToolExecutor(user="someone")
        node.allowed_tool_ids = [tool, default_tool_id("check_job")]
        node.tool_owner = OWNER
        node.tool_holder = WorkflowsRepository(pg_conn).get_by_id(str(wf["id"]))
        with _patch_db(pg_conn):
            scoped = node.get_tools()
        # The sponsor is found live, without a precomputed principal map; check_job is skipped.
        assert {tid: row["user_id"] for tid, row in scoped.items()} == {tool: EDITOR}

    def test_engine_and_stream_processor_sources(self, pg_conn):
        from docsgpt.agents.workflows.workflow_engine import WorkflowEngine
        from docsgpt.api.answer.services.stream_processor import authorized_agent_sources

        own = str(SourcesRepository(pg_conn).create("own", user_id=OWNER)["id"])
        agent_id, _ = _agent(pg_conn, source_id=own)
        with patch("docsgpt.api.user.resource_access.authorized_holder_sources", return_value=[own]) as spy:
            primary, rows = authorized_agent_sources(pg_conn, _row(pg_conn, agent_id))
            assert spy.call_args.args[1] == "agent"
            engine = WorkflowEngine.__new__(WorkflowEngine)
            engine.agent = SimpleNamespace(
                workflow_row={"id": None}, _resolve_owner_id=lambda: OWNER, user=OWNER, decoded_token={"sub": OWNER},
            )
            with _patch_db(pg_conn):
                assert engine._authorized_node_sources([own]) == [own]
            assert spy.call_args.args[1] == "workflow"
        assert str(primary["id"]) == own and [str(r["id"]) for r in rows] == [own]
