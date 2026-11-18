"""Tests for TeamItemSharesRepository: a team's items shared with whole other teams."""

from __future__ import annotations

import uuid

import pytest

from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository


def _team(conn, name, owner, members=()):
    tid = str(TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user in members:
        repo.add_member(tid, user, role="team_viewer")
    return tid


@pytest.fixture
def teams(pg_conn):
    ops = _team(pg_conn, "Ops", "alice")
    dev = _team(pg_conn, "Dev", "dora", members=("vic",))
    qa = _team(pg_conn, "QA", "quinn", members=("vic",))
    return ops, dev, qa


class TestTeamItemSharesRepository:
    def test_share_once_per_receiving_team(self, pg_conn, teams):
        ops, dev, _ = teams
        repo = TeamItemSharesRepository(pg_conn)
        item = str(uuid.uuid4())
        first = repo.share(ops, dev, "source", item, "alice")
        again = repo.share(ops, dev, "source", item, "adam")
        assert first["created"] is True and again["created"] is False
        assert again["id"] == first["id"] and again["shared_by"] == "alice"
        with pytest.raises(ValueError):
            repo.share(ops, dev, "workflow", item, "alice")

    def test_lists_from_into_and_for_an_item(self, pg_conn, teams):
        ops, dev, qa = teams
        repo = TeamItemSharesRepository(pg_conn)
        source, tool = str(uuid.uuid4()), str(uuid.uuid4())
        repo.share(ops, dev, "source", source, "alice")
        repo.share(ops, qa, "source", source, "alice")
        repo.share(ops, dev, "tool", tool, "alice")

        assert {(r["team_name"], r["resource_type"]) for r in repo.list_from(ops)} == {
            ("Dev", "source"), ("QA", "source"), ("Dev", "tool"),
        }
        into = repo.list_into(dev)
        assert {r["resource_id"] for r in into} == {source, tool}
        assert {r["owner_team_name"] for r in into} == {"Ops"}
        # The owning team's outside policy comes with each row, so a listing reads no team row per item.
        assert {r["owner_team_policy"] for r in into} == {"admins"}
        assert [r["resource_id"] for r in repo.list_into(dev, "tool")] == [tool]
        assert [r["team_name"] for r in repo.teams_for("source", source)] == ["Dev", "QA"]
        assert repo.list_into(ops) == [] and repo.list_from("nope") == []

    def test_reaching_follows_the_persons_teams(self, pg_conn, teams):
        ops, dev, qa = teams
        repo = TeamItemSharesRepository(pg_conn)
        item = str(uuid.uuid4())
        repo.share(ops, dev, "prompt", item, "alice")
        repo.share(ops, qa, "prompt", item, "alice")

        assert {r["team_name"] for r in repo.reaching("vic", "prompt", item)} == {"Dev", "QA"}
        # The receiving team's Owner reaches it too; someone in neither team doesn't.
        assert [r["team_name"] for r in repo.reaching("dora", "prompt", item)] == ["Dev"]
        assert repo.reaching("alice", "prompt", item) == []
        assert repo.reaching("vic", "source", item) == []

    def test_revoke(self, pg_conn, teams):
        ops, dev, _ = teams
        repo = TeamItemSharesRepository(pg_conn)
        item = str(uuid.uuid4())
        repo.share(ops, dev, "agent", item, "alice")
        assert repo.revoke(dev, "agent", item) is True
        assert repo.revoke(dev, "agent", item) is False
        assert repo.get(dev, "agent", item) is None
