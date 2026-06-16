"""Tests for the teams repositories against a real Postgres schema.

Covers TeamsRepository, TeamMembersRepository, TeamResourceGrantsRepository,
TeamScopeRepository, and the dangling-grant cleanup trigger from migration 0021.
"""

from __future__ import annotations

import uuid

from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.team_members import TeamMembersRepository
from application.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from application.storage.db.repositories.team_scope import TeamScopeRepository
from application.storage.db.repositories.teams import TeamsRepository
from application.storage.db.repositories.users import UsersRepository


def _new_team(conn, name="Acme", slug=None, owner="alice"):
    slug = slug or f"acme-{uuid.uuid4().hex[:8]}"
    return TeamsRepository(conn).create(name=name, slug=slug, owner_id=owner)


class TestTeamsRepository:
    def test_create_get_roundtrip(self, pg_conn):
        repo = TeamsRepository(pg_conn)
        team = _new_team(pg_conn, slug="acme")
        assert team["name"] == "Acme"
        assert team["owner_id"] == "alice"
        fetched = repo.get(team["id"])
        assert fetched["id"] == team["id"]
        assert repo.get_by_slug("acme")["id"] == team["id"]
        assert repo.slug_exists("acme") is True
        assert repo.slug_exists("nope") is False

    def test_slug_is_case_insensitive(self, pg_conn):
        repo = TeamsRepository(pg_conn)
        _new_team(pg_conn, slug="Acme")
        # CITEXT slug — lookups are case-insensitive.
        assert repo.get_by_slug("acme") is not None

    def test_list_for_user_annotates_role(self, pg_conn):
        teams = TeamsRepository(pg_conn)
        members = TeamMembersRepository(pg_conn)
        t1 = _new_team(pg_conn, name="One", owner="alice")
        t2 = _new_team(pg_conn, name="Two", owner="bob")
        members.add_member(t1["id"], "alice", role="team_admin")
        members.add_member(t2["id"], "alice", role="team_member")
        rows = {r["name"]: r["member_role"] for r in teams.list_for_user("alice")}
        assert rows == {"One": "team_admin", "Two": "team_member"}

    def test_list_for_user_empty(self, pg_conn):
        assert TeamsRepository(pg_conn).list_for_user("nobody") == []

    def test_update_and_reassign_owner(self, pg_conn):
        repo = TeamsRepository(pg_conn)
        team = _new_team(pg_conn)
        assert repo.update(team["id"], {"name": "Renamed", "bogus": "x"}) is True
        assert repo.get(team["id"])["name"] == "Renamed"
        assert repo.reassign_owner(team["id"], "carol") is True
        assert repo.get(team["id"])["owner_id"] == "carol"

    def test_delete_cascades_members(self, pg_conn):
        teams = TeamsRepository(pg_conn)
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        members.add_member(team["id"], "alice", role="team_admin")
        assert teams.delete(team["id"]) is True
        assert members.list_members(team["id"]) == []


class TestTeamMembers:
    def test_role_for_strongest_wins(self, pg_conn):
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        members.add_member(team["id"], "alice", role="team_member")
        members.add_member(team["id"], "alice", role="team_admin")
        assert members.role_for("alice", team["id"]) == "team_admin"
        assert members.is_member("alice", team["id"]) is True

    def test_role_for_non_member_is_none(self, pg_conn):
        team = _new_team(pg_conn)
        assert TeamMembersRepository(pg_conn).role_for("ghost", team["id"]) is None

    def test_list_team_ids_for(self, pg_conn):
        members = TeamMembersRepository(pg_conn)
        t1 = _new_team(pg_conn, name="One")
        t2 = _new_team(pg_conn, name="Two")
        members.add_member(t1["id"], "alice", role="team_member")
        members.add_member(t2["id"], "alice", role="team_member")
        assert set(members.list_team_ids_for("alice")) == {t1["id"], t2["id"]}

    def test_set_manual_role_demotes(self, pg_conn):
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        members.add_member(team["id"], "alice", role="team_admin")
        members.set_manual_role(team["id"], "alice", "team_member")
        assert members.role_for("alice", team["id"]) == "team_member"
        # Exactly one manual row remains.
        rows = [m for m in members.list_members(team["id"]) if m["source"] == "manual"]
        assert len(rows) == 1 and rows[0]["role"] == "team_member"

    def test_count_admins_and_last_admin_guard_data(self, pg_conn):
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        members.add_member(team["id"], "alice", role="team_admin")
        members.add_member(team["id"], "bob", role="team_admin")
        assert members.count_admins(team["id"]) == 2
        members.remove_member(team["id"], "bob")
        assert members.count_admins(team["id"]) == 1

    def test_remove_member_scoped_by_source(self, pg_conn):
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        members.add_member(team["id"], "alice", role="team_member", source="manual")
        members.add_member(team["id"], "alice", role="team_member", source="oidc_group")
        # Removing only the oidc grant keeps the manual one (IdP sync can't wipe manual).
        members.remove_member(team["id"], "alice", source="oidc_group")
        assert members.is_member("alice", team["id"]) is True
        members.remove_member(team["id"], "alice")
        assert members.is_member("alice", team["id"]) is False


class TestResourceGrants:
    def test_grant_then_list(self, pg_conn):
        team = _new_team(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        rid = str(uuid.uuid4())
        row = grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        assert row["access_level"] == "viewer"
        listed = grants.list_for_team(team["id"], "agent")
        assert len(listed) == 1 and listed[0]["resource_id"] == rid

    def test_re_share_updates_access_level(self, pg_conn):
        team = _new_team(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        grants.grant(
            team["id"], "agent", rid, owner_id="alice", granted_by="alice", access_level="editor"
        )
        assert grants.get(team["id"], "agent", rid)["access_level"] == "editor"
        # ON CONFLICT — still exactly one row.
        assert len(grants.list_for_team(team["id"], "agent")) == 1

    def test_revoke(self, pg_conn):
        team = _new_team(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        assert grants.revoke(team["id"], "agent", rid) is True
        assert grants.get(team["id"], "agent", rid) is None

    def test_list_for_resource_includes_team_name(self, pg_conn):
        team = _new_team(pg_conn, name="Acme")
        grants = TeamResourceGrantsRepository(pg_conn)
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "prompt", rid, owner_id="alice", granted_by="alice")
        rows = grants.list_for_resource("prompt", rid)
        assert rows[0]["team_name"] == "Acme"


class TestTeamScope:
    def test_visible_ids_via_membership(self, pg_conn):
        team = _new_team(pg_conn)
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        assert scope.visible_resource_ids("bob", "agent") == {rid}
        # A non-member sees nothing.
        assert scope.visible_resource_ids("ghost", "agent") == set()
        # Wrong resource type is filtered out.
        assert scope.visible_resource_ids("bob", "source") == set()

    def test_revoking_membership_drops_visibility(self, pg_conn):
        team = _new_team(pg_conn)
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        members.remove_member(team["id"], "bob")
        # Live JOIN — visibility gone immediately, grant row untouched.
        assert scope.visible_resource_ids("bob", "agent") == set()
        assert grants.get(team["id"], "agent", rid) is not None

    def test_effective_access_editor_wins_across_teams(self, pg_conn):
        t1 = _new_team(pg_conn, name="One")
        t2 = _new_team(pg_conn, name="Two")
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        members.add_member(t1["id"], "bob", role="team_member")
        members.add_member(t2["id"], "bob", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(t1["id"], "tool", rid, owner_id="alice", granted_by="alice")  # viewer
        grants.grant(
            t2["id"], "tool", rid, owner_id="alice", granted_by="alice", access_level="editor"
        )
        assert scope.effective_access("bob", "tool", rid) == "editor"
        assert scope.can_write("bob", "tool", rid) is True
        assert scope.can_read("bob", "tool", rid) is True
        # Non-member: no access.
        assert scope.effective_access("ghost", "tool", rid) is None
        assert scope.can_write("ghost", "tool", rid) is False


class TestPerMemberSharing:
    def test_member_grant_visible_only_to_target(self, pg_conn):
        team = _new_team(pg_conn)
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        members.add_member(team["id"], "carol", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(
            team["id"], "agent", rid, owner_id="alice", granted_by="alice", target_user_id="bob"
        )
        # Only the targeted member sees a per-member grant.
        assert scope.visible_resource_ids("bob", "agent") == {rid}
        assert scope.visible_resource_ids("carol", "agent") == set()
        assert scope.effective_access("bob", "agent", rid) == "viewer"
        assert scope.effective_access("carol", "agent", rid) is None

    def test_whole_team_and_member_grants_coexist(self, pg_conn):
        team = _new_team(pg_conn)
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        members.add_member(team["id"], "carol", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")  # whole team
        grants.grant(
            team["id"], "agent", rid, owner_id="alice", granted_by="alice",
            target_user_id="bob", access_level="editor",
        )
        # Distinct rows (functional dedup over COALESCE(target,'')).
        assert len(grants.list_for_team(team["id"], "agent")) == 2
        # bob gets the strongest across whole-team + his member grant; carol only viewer.
        assert scope.effective_access("bob", "agent", rid) == "editor"
        assert scope.effective_access("carol", "agent", rid) == "viewer"

    def test_revoke_member_grant_keeps_whole_team(self, pg_conn):
        team = _new_team(pg_conn)
        members = TeamMembersRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        members.add_member(team["id"], "bob", role="team_member")
        rid = str(uuid.uuid4())
        grants.grant(team["id"], "agent", rid, owner_id="alice", granted_by="alice")
        grants.grant(
            team["id"], "agent", rid, owner_id="alice", granted_by="alice", target_user_id="bob"
        )
        assert grants.revoke(team["id"], "agent", rid, target_user_id="bob") is True
        assert grants.get(team["id"], "agent", rid, target_user_id="bob") is None
        # Whole-team grant untouched.
        assert grants.get(team["id"], "agent", rid) is not None

    def test_member_grant_needs_membership_for_visibility(self, pg_conn):
        # A grant targeting a non-member is inert — the live JOIN requires the
        # viewer to be a team member.
        team = _new_team(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        scope = TeamScopeRepository(pg_conn)
        rid = str(uuid.uuid4())
        grants.grant(
            team["id"], "agent", rid, owner_id="alice", granted_by="alice", target_user_id="ghost"
        )
        assert scope.visible_resource_ids("ghost", "agent") == set()


class TestEmailLookup:
    def test_upsert_stores_and_find_by_email_case_insensitive(self, pg_conn):
        users = UsersRepository(pg_conn)
        users.upsert("sub-1", email="Alice@Example.com")
        row = users.find_by_email("alice@example.com")
        assert row is not None and row["user_id"] == "sub-1"
        assert users.find_by_email("nobody@example.com") is None
        assert users.find_by_email("") is None

    def test_upsert_without_email_preserves_existing(self, pg_conn):
        users = UsersRepository(pg_conn)
        users.upsert("sub-2", email="bob@example.com")
        users.upsert("sub-2")  # a non-OIDC upsert must not wipe the stored email
        assert users.find_by_email("bob@example.com")["user_id"] == "sub-2"

    def test_list_members_includes_email(self, pg_conn):
        users = UsersRepository(pg_conn)
        members = TeamMembersRepository(pg_conn)
        team = _new_team(pg_conn)
        users.upsert("carol", email="carol@team.com")
        members.add_member(team["id"], "carol", role="team_member")
        row = next(m for m in members.list_members(team["id"]) if m["user_id"] == "carol")
        assert row["email"] == "carol@team.com"


class TestCleanupTrigger:
    def test_deleting_agent_scrubs_its_grants(self, pg_conn):
        team = _new_team(pg_conn)
        agents = AgentsRepository(pg_conn)
        grants = TeamResourceGrantsRepository(pg_conn)
        agent = agents.create("alice", "My Agent", "published")
        agent_id = str(agent["id"])
        grants.grant(team["id"], "agent", agent_id, owner_id="alice", granted_by="alice")
        assert grants.get(team["id"], "agent", agent_id) is not None
        # AFTER DELETE trigger (migration 0021) removes the dangling grant.
        agents.delete(agent_id, "alice")
        assert grants.get(team["id"], "agent", agent_id) is None
