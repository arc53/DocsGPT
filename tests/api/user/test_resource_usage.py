"""Which agents use a tool, prompt or source (``used_by`` on the Workspace lists)."""

from __future__ import annotations

import uuid

from docsgpt.agents.default_tools import default_tool_id
from docsgpt.api.user.resource_usage import EMPTY_USAGE, combined_usage, is_in_use, used_by_many
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

ALICE = "alice"
BOB = "bob"


def _agent(conn, owner, name, **kwargs):
    return AgentsRepository(conn).create(owner, name, "published", **kwargs)


def _tool(conn, owner=ALICE, name="read_webpage"):
    return UserToolsRepository(conn).create(owner, name, config={}, display_name=name)


def _source(conn, owner=ALICE, name="src"):
    return SourcesRepository(conn).create(name, user_id=owner)


def _share(conn, resource_type, resource_id, owner, member):
    team = TeamsRepository(conn).create("Acme", f"t-{uuid.uuid4().hex[:8]}", owner)
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, str(resource_id), owner, owner, access_level="viewer"
    )


def _workflow_agent(conn, owner, name, versions: dict[int, dict], current: int):
    """A workflow agent whose workflow holds one agent node per graph version."""
    wf = WorkflowsRepository(conn).create(owner, f"wf-{name}")
    WorkflowsRepository(conn).update(str(wf["id"]), owner, {"current_graph_version": current})
    nodes = WorkflowNodesRepository(conn)
    for version, config in versions.items():
        nodes.create(str(wf["id"]), version, "start", "start")
        nodes.create(str(wf["id"]), version, "agent-1", "agent", config=config)
    return _agent(conn, owner, name, agent_type="workflow", workflow_id=str(wf["id"]))


def _names(usage):
    return [a["name"] for a in usage["agents"]]


class TestTools:
    def test_classic_agents_sorted_by_name(self, pg_conn):
        tool = _tool(pg_conn)
        tid = str(tool["id"])
        _agent(pg_conn, ALICE, "zeta", tools=[tid])
        a = _agent(pg_conn, ALICE, "Alpha", tools=[tid, str(uuid.uuid4())])
        _agent(pg_conn, ALICE, "unrelated", tools=[])
        usage = used_by_many(pg_conn, ALICE, "tool", [tid], owned_ids=[tid])
        assert _names(usage[tid]) == ["Alpha", "zeta"]
        assert usage[tid]["agents"][0] == {"id": str(a["id"]), "name": "Alpha", "agent_type": "classic"}
        assert usage[tid]["others"] == 0

    def test_unused_resource_gets_empty_usage(self, pg_conn):
        tid = str(_tool(pg_conn)["id"])
        usage = used_by_many(pg_conn, ALICE, "tool", [tid], owned_ids=[tid])
        assert usage[tid] == EMPTY_USAGE
        assert not is_in_use(usage[tid])

    def test_default_tool_matches_its_synthetic_id(self, pg_conn):
        memory_id = default_tool_id("memory")
        _agent(pg_conn, ALICE, "mem agent", tools=[memory_id])
        _agent(pg_conn, BOB, "bob's mem agent", tools=[memory_id])
        usage = used_by_many(pg_conn, ALICE, "tool", [memory_id], owned_ids=[])
        # Nobody owns a default tool: other users' agents are neither listed nor counted.
        assert _names(usage[memory_id]) == ["mem agent"]
        assert usage[memory_id]["others"] == 0

    def test_workflow_agent_counts_current_graph_version_only(self, pg_conn):
        old_tool = str(_tool(pg_conn, name="old")["id"])
        new_tool = str(_tool(pg_conn, name="new")["id"])
        _workflow_agent(
            pg_conn, ALICE, "flow",
            {1: {"tools": [old_tool]}, 2: {"tools": [new_tool]}},
            current=2,
        )
        usage = used_by_many(pg_conn, ALICE, "tool", [old_tool, new_tool], owned_ids=[old_tool, new_tool])
        assert _names(usage[new_tool]) == ["flow"]
        # The type picks the editor a link opens.
        assert usage[new_tool]["agents"][0]["agent_type"] == "workflow"
        assert usage[old_tool] == EMPTY_USAGE

    def test_workflow_agent_classic_columns_are_ignored(self, pg_conn):
        tid = str(_tool(pg_conn)["id"])
        # Classic ``tools`` left over on a workflow agent do not run.
        _agent(pg_conn, ALICE, "leftover", agent_type="workflow", tools=[tid])
        usage = used_by_many(pg_conn, ALICE, "tool", [tid], owned_ids=[tid])
        assert usage[tid] == EMPTY_USAGE


class TestVisibility:
    def test_owner_counts_teammates_agents_as_others(self, pg_conn):
        tool = _tool(pg_conn)
        tid = str(tool["id"])
        _share(pg_conn, "tool", tid, ALICE, BOB)
        _agent(pg_conn, ALICE, "mine", tools=[tid])
        _agent(pg_conn, BOB, "bob private", tools=[tid])
        shared_agent = _agent(pg_conn, BOB, "bob shared", tools=[tid])
        _share(pg_conn, "agent", shared_agent["id"], BOB, ALICE)

        mine = used_by_many(pg_conn, ALICE, "tool", [tid], owned_ids=[tid])[tid]
        assert _names(mine) == ["bob shared", "mine"]
        assert mine["others"] == 1
        assert is_in_use(mine)

        # Bob sees the tool through the team; he does not own it, so no others.
        theirs = used_by_many(pg_conn, BOB, "tool", [tid], owned_ids=[])[tid]
        assert _names(theirs) == ["bob private", "bob shared"]
        assert theirs["others"] == 0

    def test_only_others_still_counts_as_in_use(self, pg_conn):
        tid = str(_tool(pg_conn)["id"])
        _agent(pg_conn, BOB, "bob private", tools=[tid])
        usage = used_by_many(pg_conn, ALICE, "tool", [tid], owned_ids=[tid])[tid]
        assert usage == {"agents": [], "others": 1}
        assert is_in_use(usage)

    def test_agent_allowlist_hides_agents_outside_it(self, pg_conn):
        tid = str(_tool(pg_conn)["id"])
        keep = _agent(pg_conn, ALICE, "keep", tools=[tid])
        _agent(pg_conn, ALICE, "hidden", tools=[tid])
        usage = used_by_many(
            pg_conn, ALICE, "tool", [tid], owned_ids=[tid], agent_allowlist={str(keep["id"])}
        )[tid]
        assert _names(usage) == ["keep"]
        assert usage["others"] == 1


class TestSources:
    def test_primary_extra_and_workflow_sources(self, pg_conn):
        s1 = str(_source(pg_conn, name="one")["id"])
        s2 = str(_source(pg_conn, name="two")["id"])
        _agent(pg_conn, ALICE, "primary", source_id=s1)
        _agent(pg_conn, ALICE, "both", source_id=s1, extra_source_ids=[s1, s2])
        _workflow_agent(pg_conn, ALICE, "flow", {3: {"sources": [s2]}}, current=3)
        usage = used_by_many(pg_conn, ALICE, "source", [s1, s2], owned_ids=[s1, s2])
        assert _names(usage[s1]) == ["both", "primary"]
        assert _names(usage[s2]) == ["both", "flow"]


class TestPrompts:
    def test_prompt_row_and_presets(self, pg_conn):
        prompt = PromptsRepository(pg_conn).create(ALICE, "P", "content")
        pid = str(prompt["id"])
        _agent(pg_conn, ALICE, "custom", prompt_id=pid)
        _agent(pg_conn, ALICE, "plain")  # NULL prompt_id: the default preset
        _agent(pg_conn, BOB, "bob plain")  # not visible to alice
        _workflow_agent(pg_conn, ALICE, "flow", {1: {"system_prompt": "inline"}}, current=1)
        ids = ["default", "creative", "strict", pid]
        usage = used_by_many(pg_conn, ALICE, "prompt", ids, owned_ids=[pid])
        assert _names(usage[pid]) == ["custom"]
        assert _names(usage["default"]) == ["plain"]
        assert usage["default"]["others"] == 0
        assert usage["creative"] == EMPTY_USAGE
        assert usage["strict"] == EMPTY_USAGE

    def test_shared_agent_with_default_prompt_is_listed(self, pg_conn):
        agent = _agent(pg_conn, BOB, "bob shared")
        _share(pg_conn, "agent", agent["id"], BOB, ALICE)
        usage = used_by_many(pg_conn, ALICE, "prompt", ["default"], owned_ids=[])
        assert _names(usage["default"]) == ["bob shared"]


class TestBounded:
    def test_query_count_does_not_grow_with_resources(self, pg_conn):
        from sqlalchemy import event

        tools = [str(_tool(pg_conn, name=f"t{i}")["id"]) for i in range(6)]
        for i, tid in enumerate(tools):
            _agent(pg_conn, ALICE, f"a{i}", tools=[tid])
        statements: list[str] = []

        def _count(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(pg_conn, "before_cursor_execute", _count)
        try:
            used_by_many(pg_conn, ALICE, "tool", tools, owned_ids=tools)
        finally:
            event.remove(pg_conn, "before_cursor_execute", _count)
        assert len(statements) <= 4

    def test_empty_ids_runs_no_query(self, pg_conn):
        assert used_by_many(pg_conn, ALICE, "tool", [], owned_ids=[]) == {}


class TestCombinedUsage:
    def test_an_agent_on_several_resources_counts_once(self, pg_conn):
        s1 = str(_source(pg_conn, name="one")["id"])
        s2 = str(_source(pg_conn, name="two")["id"])
        _share(pg_conn, "source", s1, ALICE, BOB)
        _share(pg_conn, "source", s2, ALICE, BOB)
        _agent(pg_conn, ALICE, "mine", source_id=s1, extra_source_ids=[s2])
        _agent(pg_conn, BOB, "bob both", source_id=s1, extra_source_ids=[s2])
        _agent(pg_conn, BOB, "bob one", source_id=s2)

        usage = combined_usage(pg_conn, ALICE, "source", [s1, s2], owned_ids=[s1, s2])
        assert _names(usage) == ["mine"]
        # Per source these would sum to 3; Bob's two agents are two.
        assert usage["others"] == 2

    def test_others_only_for_owned_resources(self, pg_conn):
        theirs = str(_source(pg_conn, owner=BOB, name="theirs")["id"])
        _share(pg_conn, "source", theirs, BOB, ALICE)
        _agent(pg_conn, BOB, "bob private", source_id=theirs)
        usage = combined_usage(pg_conn, ALICE, "source", [theirs], owned_ids=[])
        assert usage == EMPTY_USAGE

    def test_no_ids(self, pg_conn):
        assert combined_usage(pg_conn, ALICE, "source", [], owned_ids=[]) == EMPTY_USAGE
