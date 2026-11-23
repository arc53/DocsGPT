"""Checks of one operation read a workflow agent's workflow and stored graph once, and share them.

Refusing a key, link or webhook checks both the tools on a team's account and the borrowed items an agent uses;
an agent save checks both the team items and the team-account tools it adds. Each pair reads the same workflow
and stored graph at the same point, so the reads happen once. Real repositories on ``pg_conn``; statements are
counted with a cursor spy.
"""

from __future__ import annotations

import re
from contextlib import contextmanager

import pytest
from flask import Flask
from sqlalchemy import event

from docsgpt.api.user.agents.graph_checks import (
    WorkflowReads,
    agent_team_connection_tools,
    agent_team_refs,
    refuse_borrowed_outside_access,
)
from docsgpt.api.user.workflows.routes import _node_refs
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.workflow_edges import WorkflowEdgesRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from tests.api.user.agents.test_borrowed_outside_access import _call, _json, _status
from tests.workspaces.move_support import tool

pytestmark = pytest.mark.integration

OWNER = "wr-owner"
_NODES = re.compile(r"\bFROM\s+workflow_nodes\b", re.IGNORECASE)
_WORKFLOWS = re.compile(r"\bFROM\s+workflows\b", re.IGNORECASE)


@contextmanager
def _statements(conn):
    """Collect the SQL run on ``conn`` while the block runs."""
    seen: list[str] = []

    def spy(_conn, _cursor, statement, *_args):
        seen.append(statement)

    event.listen(conn, "before_cursor_execute", spy)
    try:
        yield seen
    finally:
        event.remove(conn, "before_cursor_execute", spy)


def _count(pattern, statements) -> int:
    return sum(1 for s in statements if pattern.search(s))


def _workflow_agent(conn, node_tool: str) -> dict:
    """A draft workflow agent whose one agent node uses ``node_tool``."""
    wid = str(WorkflowsRepository(conn).create(OWNER, "Pipeline")["id"])
    nodes = WorkflowNodesRepository(conn).bulk_create(
        wid, 1,
        [
            {"node_id": "start-1", "node_type": "start", "title": "Start"},
            {"node_id": "agent-1", "node_type": "agent", "title": "Answer",
             "config": {"agent_type": "classic", "system_prompt": "s", "tools": [node_tool]}},
            {"node_id": "end-1", "node_type": "end", "title": "End"},
        ],
    )
    by_id = {n["node_id"]: n["id"] for n in nodes}
    WorkflowEdgesRepository(conn).bulk_create(
        wid, 1,
        [
            {"edge_id": "e1", "from_node_id": by_id["start-1"], "to_node_id": by_id["agent-1"]},
            {"edge_id": "e2", "from_node_id": by_id["agent-1"], "to_node_id": by_id["end-1"]},
        ],
    )
    return AgentsRepository(conn).create(OWNER, "Flow", "draft", agent_type="workflow", workflow_id=wid)


class TestRefuseOutsideAccess:
    def test_reads_the_workflow_and_its_graph_once(self, pg_conn):
        agent = _workflow_agent(pg_conn, tool(pg_conn, OWNER))
        with _statements(pg_conn) as seen:
            assert refuse_borrowed_outside_access(pg_conn, agent, OWNER) is None

        assert _count(_WORKFLOWS, seen) == 1
        assert _count(_NODES, seen) == 1


class TestWorkflowReads:
    def test_shared_reads_give_the_same_answers_as_fresh_ones(self, pg_conn):
        node_tool = tool(pg_conn, OWNER)
        agent = _workflow_agent(pg_conn, node_tool)
        reads = WorkflowReads(pg_conn)

        assert agent_team_refs(pg_conn, agent, reads=reads) == agent_team_refs(pg_conn, agent)
        assert agent_team_connection_tools(pg_conn, agent, reads=reads) == agent_team_connection_tools(pg_conn, agent)
        assert ("tool", node_tool) in _node_refs(reads.nodes(agent))

    def test_nodes_a_save_brings_skip_the_stored_graph(self, pg_conn):
        agent = _workflow_agent(pg_conn, tool(pg_conn, OWNER))
        with _statements(pg_conn) as seen:
            assert WorkflowReads(pg_conn).nodes(agent, []) == []

        assert seen == []

    def test_no_workflow_reads_nothing(self, pg_conn):
        with _statements(pg_conn) as seen:
            reads = WorkflowReads(pg_conn)
            assert reads.workflow({"user_id": OWNER}) is None
            assert reads.nodes({"user_id": OWNER}) == []

        assert seen == []


class TestAgentSave:
    def test_the_save_checks_read_the_stored_graph_once(self, pg_conn):
        from docsgpt.api.user.agents.routes import UpdateAgent

        agent = _workflow_agent(pg_conn, tool(pg_conn, OWNER))
        added = tool(pg_conn, OWNER, "api_tool")
        aid = str(agent["id"])
        with _statements(pg_conn) as seen:
            resp = _call(Flask(__name__), pg_conn, UpdateAgent, "put", f"/api/update_agent/{aid}", OWNER,
                         json={"tools": [added]}, args=(aid,))

        assert _status(resp) == 200, _json(resp)
        assert [str(t) for t in AgentsRepository(pg_conn).get(aid, OWNER)["tools"]] == [added]
        assert _count(_NODES, seen) == 1
