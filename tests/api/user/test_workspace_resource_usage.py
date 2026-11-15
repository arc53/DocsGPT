"""``used_by`` on a team's items lists the team's agents to its members (STEP1_PLAN WP4a).

A team's agents are reached by team role, not by a grant, so a member sees which of them use a team item, and
may open the editor of each from the Editor role up. Someone outside the team learns nothing about them.
"""

from __future__ import annotations

import uuid

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
