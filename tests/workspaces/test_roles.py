"""Team roles: ranks, the stored names, the legacy compat names and a person's role in a team."""

from __future__ import annotations

import uuid

import pytest

from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.roles import (
    TEAM_ROLES,
    from_stored_role,
    legacy_member_role,
    role_at_least,
    role_rank,
    team_role_for,
    to_stored_role,
)


def test_ranks():
    assert TEAM_ROLES == ("viewer", "editor", "admin", "owner")
    assert [role_rank(r) for r in TEAM_ROLES] == [1, 2, 3, 4]
    assert role_rank(None) == 0 and role_rank("team_admin") == 0
    assert role_at_least("admin", "editor")
    assert role_at_least("owner", "admin")
    assert not role_at_least("viewer", "editor")
    assert not role_at_least(None, "viewer")


@pytest.mark.parametrize(
    "given, stored",
    [
        ("admin", "team_admin"),
        ("editor", "team_editor"),
        ("viewer", "team_viewer"),
        ("team_admin", "team_admin"),
        ("team_editor", "team_editor"),
        ("team_viewer", "team_viewer"),
        ("team_member", "team_viewer"),  # the old member role is a viewer
        (" Editor ", "team_editor"),
    ],
)
def test_to_stored_role(given, stored):
    assert to_stored_role(given) == stored


@pytest.mark.parametrize("bad", ["owner", "team_owner", "", None, "superuser"])
def test_to_stored_role_refuses_anything_else(bad):
    with pytest.raises(ValueError):
        to_stored_role(bad)


def test_from_stored_and_legacy_names():
    assert [from_stored_role(r) for r in ("team_admin", "team_editor", "team_viewer", "team_member")] == [
        "admin", "editor", "viewer", "viewer",
    ]
    assert from_stored_role("nope") is None
    assert [legacy_member_role(r) for r in ("owner", "admin", "editor", "viewer")] == [
        "team_admin", "team_admin", "team_member", "team_member",
    ]
    assert legacy_member_role(None) is None


class TestTeamRoleFor:
    def _team(self, conn, owner="alice") -> str:
        team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner_id=owner)
        members = TeamMembersRepository(conn)
        members.add_member(str(team["id"]), owner, role="team_admin")
        members.add_member(str(team["id"]), "bob", role="team_editor")
        members.add_member(str(team["id"]), "carol", role="team_viewer")
        # dave holds viewer by hand and admin through the IdP: the strongest wins.
        members.add_member(str(team["id"]), "dave", role="team_viewer")
        members.add_member(str(team["id"]), "dave", role="team_admin", source="oidc_group")
        return str(team["id"])

    def test_each_role(self, pg_conn):
        team_id = self._team(pg_conn)
        roles = {u: team_role_for(pg_conn, u, team_id) for u in ("alice", "bob", "carol", "dave", "erin")}
        assert roles == {"alice": "owner", "bob": "editor", "carol": "viewer", "dave": "admin", "erin": None}

    def test_the_owner_is_owner_even_without_a_row(self, pg_conn):
        team = TeamsRepository(pg_conn).create("Solo", f"solo-{uuid.uuid4().hex[:6]}", owner_id="zed")
        assert team_role_for(pg_conn, "zed", str(team["id"])) == "owner"

    @pytest.mark.parametrize("team_id", ["", None, "not-a-uuid"])
    def test_a_malformed_team_is_no_role(self, pg_conn, team_id):
        assert team_role_for(pg_conn, "alice", team_id) is None

    def test_no_user_is_no_role(self, pg_conn):
        team_id = self._team(pg_conn)
        assert team_role_for(pg_conn, "", team_id) is None
        assert team_role_for(pg_conn, None, team_id) is None
