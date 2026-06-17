"""Integration tests for agent team-sharing: repo methods + sharing helpers.

Exercises the real ``team_sharing`` helpers and the new AgentsRepository
methods (get_by_id / list_by_ids / update_by_id) against a real schema.
"""

from __future__ import annotations

import uuid

from application.api.user.team_sharing import (
    can_access,
    effective_write_owner,
    owns_resource,
    team_access_for,
    visible_with_access,
)
from application.storage.db.repositories.team_scope import TeamScopeRepository
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.team_members import TeamMembersRepository
from application.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from application.storage.db.repositories.teams import TeamsRepository


def _team(conn, owner="alice"):
    return TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)


def _agent(conn, owner="alice", name="A"):
    return AgentsRepository(conn).create(owner, name, "published")


class TestAgentRepoTeamMethods:
    def test_get_by_id_ignores_owner(self, pg_conn):
        repo = AgentsRepository(pg_conn)
        agent = _agent(pg_conn, owner="alice")
        # get_by_id has no user scoping — only call after a grant check.
        assert repo.get_by_id(str(agent["id"]))["id"] == str(agent["id"])
        # get_any IS owner-scoped: bob can't reach alice's agent.
        assert repo.get_any(str(agent["id"]), "bob") is None

    def test_list_by_ids(self, pg_conn):
        repo = AgentsRepository(pg_conn)
        a1 = _agent(pg_conn, name="one")
        a2 = _agent(pg_conn, name="two")
        ids = {str(a1["id"]), str(a2["id"])}
        listed = {str(a["id"]) for a in repo.list_by_ids(list(ids))}
        assert listed == ids
        assert repo.list_by_ids([]) == []

    def test_update_by_id_optimistic_lock(self, pg_conn):
        repo = AgentsRepository(pg_conn)
        agent = _agent(pg_conn)
        aid = str(agent["id"])
        ts = repo.get_by_id(aid)["updated_at"]
        # Matching version → applied.
        assert repo.update_by_id(aid, {"name": "renamed"}, expected_updated_at=ts) is True
        assert repo.get_by_id(aid)["name"] == "renamed"
        # Stale version (row exists, no match) → None so the route can 409.
        stale = repo.update_by_id(
            aid, {"name": "again"}, expected_updated_at="2000-01-01T00:00:00+00:00"
        )
        assert stale is None
        # No version supplied → unconditional write.
        assert repo.update_by_id(aid, {"name": "free"}) is True


class TestSharingHelpers:
    def test_owns_resource_dispatch(self, pg_conn):
        agent = _agent(pg_conn, owner="alice")
        aid = str(agent["id"])
        assert owns_resource(pg_conn, "agent", aid, "alice") is True
        assert owns_resource(pg_conn, "agent", aid, "bob") is False
        # type/id mismatch (an agent id under resource_type 'source') → False.
        assert owns_resource(pg_conn, "source", aid, "alice") is False

    def test_can_access_owner_and_team_member(self, pg_conn):
        team = _team(pg_conn, owner="alice")
        agent = _agent(pg_conn, owner="alice")
        aid = str(agent["id"])
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        # Before sharing: bob has no access.
        assert can_access(pg_conn, "agent", aid, "bob") is False
        grants.grant(team["id"], "agent", aid, owner_id="alice", granted_by="alice")
        # After sharing: owner always, member via grant, stranger never.
        assert can_access(pg_conn, "agent", aid, "alice") is True
        assert can_access(pg_conn, "agent", aid, "bob") is True
        assert can_access(pg_conn, "agent", aid, "ghost") is False
        # Empty reference (clearing a source) is always allowed.
        assert can_access(pg_conn, "source", "", "bob") is True

    def test_visible_with_access_and_team_access_for(self, pg_conn):
        team = _team(pg_conn, owner="alice")
        agent = _agent(pg_conn, owner="alice")
        aid = str(agent["id"])
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        grants.grant(
            team["id"], "agent", aid, owner_id="alice", granted_by="alice", access_level="editor"
        )
        assert visible_with_access(pg_conn, "bob", "agent") == {aid: "editor"}
        assert team_access_for(pg_conn, "bob", "agent", aid) == "editor"
        # Owner is not "team-visible" via this path (they own it directly).
        assert visible_with_access(pg_conn, "alice", "agent") == {}


class TestWriteOwnerAndGuards:
    def test_effective_write_owner_paths(self, pg_conn):
        team = _team(pg_conn, owner="alice")
        agent = _agent(pg_conn, owner="alice")
        aid = str(agent["id"])
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        members.add_member(team["id"], "carol", role="team_member")
        # Owner → writes as themselves.
        assert effective_write_owner(pg_conn, "agent", aid, "alice") == "alice"
        # Viewer grant → no write.
        grants.grant(team["id"], "agent", aid, owner_id="alice", granted_by="alice")
        assert effective_write_owner(pg_conn, "agent", aid, "bob") is None
        # Editor grant → writes AS the real owner (so dual-key update matches).
        grants.grant(
            team["id"], "agent", aid, owner_id="alice", granted_by="alice", access_level="editor"
        )
        assert effective_write_owner(pg_conn, "agent", aid, "bob") == "alice"
        # Non-member → no write even with an editor grant on the team.
        assert effective_write_owner(pg_conn, "agent", aid, "stranger") is None

    def test_non_uuid_id_never_crashes(self, pg_conn):
        # Legacy/non-UUID ids can't carry a grant and must not poison the txn.
        scope = TeamScopeRepository(pg_conn)
        assert scope.effective_access("bob", "agent", "legacy-mongo-objectid") is None
        assert scope.can_read("bob", "agent", "not-a-uuid") is False
        assert effective_write_owner(pg_conn, "agent", "not-a-uuid", "bob") is None
        # Connection still usable afterwards (no aborted transaction).
        assert _agent(pg_conn, owner="zed")["user_id"] == "zed"
