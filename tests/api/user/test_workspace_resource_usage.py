"""``used_by`` on a team's items lists the team's agents to its members.

A team's agents are reached by team role, not by a grant, so a member sees which of them use a team item, and
may open the editor of each from the Editor role up. Someone outside the team learns nothing about them.
"""

from __future__ import annotations

import uuid

import pytest

from docsgpt.api.user.resource_usage import used_by_many
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.principal import principal_id

OWNER, ADMIN, EDITOR, VIEWER, STRANGER = "ru-alice", "ru-adam", "ru-eddie", "ru-vera", "ru-stan"


def _team(conn):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _setup(conn):
    tid, principal = _team(conn)
    source = str(SourcesRepository(conn).create("Handbook", user_id=principal)["id"])
    agent = str(AgentsRepository(conn).create(principal, "Team bot", "published", source_id=source)["id"])
    return source, agent


class TestTeamUsage:
    def test_an_editor_sees_the_team_agent_and_may_open_it(self, pg_conn):
        source, agent = _setup(pg_conn)
        usage = used_by_many(pg_conn, EDITOR, "source", [source], deletable_ids=[])
        assert usage[source]["agents"] == [
            {"id": agent, "name": "Team bot", "agent_type": "classic", "can_edit": True, "status": "published"}
        ]

    def test_a_viewer_sees_it_but_may_not_open_its_editor(self, pg_conn):
        source, agent = _setup(pg_conn)
        usage = used_by_many(pg_conn, VIEWER, "source", [source], deletable_ids=[])
        assert [(a["id"], a["can_edit"]) for a in usage[source]["agents"]] == [(agent, False)]

    def test_an_admin_deleting_sees_every_team_agent(self, pg_conn):
        source, agent = _setup(pg_conn)
        usage = used_by_many(pg_conn, ADMIN, "source", [source], deletable_ids=[source])
        assert [a["id"] for a in usage[source]["agents"]] == [agent]
        assert usage[source]["others"] == 0

    def test_an_outsider_learns_nothing(self, pg_conn):
        source, _agent = _setup(pg_conn)
        usage = used_by_many(pg_conn, STRANGER, "source", [source], deletable_ids=[])
        assert usage[source] == {"agents": [], "others": 0}


def _uses(conn, sources: int, agents: int) -> tuple[list[str], set[str]]:
    """A new team whose classic agents name every one of its sources and read them through a folder too,
    beside as many workflow agents reading the same folder; return the source ids and the agent ids."""
    from sqlalchemy import text

    from tests.workspaces.move_support import file, folder, workflow

    _tid, principal = _team(conn)
    repo = SourcesRepository(conn)
    ids = [str(repo.create(f"doc {i}", user_id=principal)["id"]) for i in range(sources)]
    shelf = folder(conn, principal, "Shelf")
    for sid in ids:
        file(conn, principal, "source", sid, shelf)
    used: set[str] = set()
    for i in range(agents):
        used.add(str(AgentsRepository(conn).create(
            principal, f"bot {i}", "published", extra_source_ids=ids, knowledge_folder_ids=[shelf]
        )["id"]))
        wid = workflow(conn, principal, f"flow {i}", nodes=[{"folders": [shelf]}])
        conn.execute(text("UPDATE workflows SET current_graph_version = 1 WHERE id = CAST(:i AS uuid)"), {"i": wid})
        used.add(str(AgentsRepository(conn).create(
            principal, f"flow {i}", "published", agent_type="workflow", workflow_id=wid
        )["id"]))
    return ids, used


def _statements(conn, user, ids, deletable):
    from sqlalchemy import event

    statements: list[str] = []

    def _count(_conn, _cursor, statement, *args):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", _count)
    try:
        usage = used_by_many(conn, user, "source", ids, deletable_ids=deletable)
    finally:
        event.remove(conn, "before_cursor_execute", _count)
    return usage, statements


class TestTeamUsageQueryCount:
    """However many sources and agents a team has, its usage is read in the same number of queries."""

    @pytest.mark.parametrize("deletable", [False, True])
    def test_team_actions_are_worked_out_once_per_owning_team(self, pg_conn, deletable):
        ids, agents = _uses(pg_conn, 12, 4)
        usage, statements = _statements(pg_conn, EDITOR, ids, ids if deletable else [])
        assert sum("outside_policy FROM teams" in s for s in statements) <= 1
        for sid in ids:
            assert {a["id"] for a in usage[sid]["agents"]} == agents
            assert all(a["can_edit"] for a in usage[sid]["agents"]) and usage[sid]["others"] == 0

    @pytest.mark.parametrize("deletable", [False, True])
    def test_the_same_queries_for_a_small_team_and_a_large_one(self, pg_conn, deletable):
        # The holders reading a folder, and what their folders hold, load together, not one holder at a time.
        small, _ = _uses(pg_conn, 2, 1)
        large, agents = _uses(pg_conn, 12, 4)
        _usage, few = _statements(pg_conn, EDITOR, small, small if deletable else [])
        usage, more = _statements(pg_conn, EDITOR, large, large if deletable else [])
        assert len(more) == len(few)
        assert {a["id"] for a in usage[large[0]]["agents"]} == agents

    def test_a_viewer_reads_the_same_agents_without_their_editors(self, pg_conn):
        ids, agents = _uses(pg_conn, 3, 2)
        usage, _ = _statements(pg_conn, VIEWER, ids, [])
        for sid in ids:
            assert {(a["id"], a["can_edit"]) for a in usage[sid]["agents"]} == {(a, False) for a in agents}


class TestSourcesListingQueryCount:
    def test_a_team_sources_page_costs_the_same_however_many_sources_and_agents(self, pg_conn):
        """Every matching source's usage feeds the filters and counts, so it is read in fixed queries."""
        from flask import Flask
        from sqlalchemy import event, text

        from docsgpt.api.user.sources.routes import PaginatedSources
        from docsgpt.workspaces.principal import team_of_principal
        from tests.api.user.test_team_shared_lists import _call

        app = Flask(__name__)
        counts, totals = [], []
        for sources, agents in ((3, 1), (15, 4)):
            ids, _agents = _uses(pg_conn, sources, agents)
            owner = pg_conn.execute(text("SELECT user_id FROM sources WHERE id = CAST(:i AS uuid)"), {"i": ids[0]})
            team_id = team_of_principal(owner.scalar())
            statements: list[str] = []

            def _count(_conn, _cursor, statement, *args, into=statements):
                into.append(statement)

            event.listen(pg_conn, "before_cursor_execute", _count)
            try:
                resp = _call(app, pg_conn, PaginatedSources, "/api/sources/paginated?rows=5&usage=in_use", EDITOR,
                             team_id=team_id)
            finally:
                event.remove(pg_conn, "before_cursor_execute", _count)
            assert resp.status_code == 200, resp.json
            counts.append(len(statements))
            totals.append((resp.json["total"], resp.json["usage_counts"]["in_use"], len(resp.json["paginated"])))
        assert counts[0] == counts[1]
        assert totals == [(3, 3, 3), (15, 15, 5)]
