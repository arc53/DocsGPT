"""A team's outside policy decides who may take its items outside: Admins (default), Editors too, or nobody.

Outside is a share with another team, and an agent's key, widget, public link and webhook. The policy moves
``publish``, ``manage_access_details`` and ``share_outside`` between Admin and Editor; ``locked`` takes
``manage_access_details``, ``share_outside``, ``move_out`` and ``export`` from everyone, the Owner included,
while ``publish`` stays with Admins (a draft goes live, but no key is made). Every team call of the action
table has to name the policy: one that doesn't raises instead of falling back to a fixed table.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    WORKSPACE_ACTIONS,
    build_team,
    cached_resolves,
    payload_for,
    resolve,
    workspace_allowed_actions,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.outside import (
    DEFAULT_POLICY,
    POLICIES,
    may_set_policy,
    may_take_outside,
    outside_minimum,
    team_policy,
)
from docsgpt.workspaces.principal import principal_id

ROLES = ("viewer", "editor", "admin", "owner")
KINDS = ("agent", "source", "tool", "prompt")

#: The actions the policy governs, and the actions a lock takes from everyone.
OUTSIDE = {"publish", "manage_access_details", "share_outside"}
LOCK_REMOVES = {"manage_access_details", "share_outside", "move_out", "export"}

#: Today's table (Admins and Owner take items outside) as each role sees it.
ADMINS = {
    "agent": {
        "viewer": {"use", "pin"},
        "editor": {"use", "pin", "view", "edit", "edit_policy", "view_logs", "manage_schedules", "export",
                   "move_folder"},
        "admin": {"use", "pin", "view", "edit", "edit_policy", "view_logs", "manage_schedules", "export",
                  "move_folder", "publish", "manage_access_details", "share_outside", "delete", "move_out"},
    },
    "source": {
        "viewer": {"use", "view_config"},
        "editor": {"use", "view_config", "edit", "move_folder"},
        "admin": {"use", "view_config", "edit", "move_folder", "reconnect", "delete", "move_out", "share_outside"},
    },
    "tool": {
        "viewer": {"use", "use_in_own"},
        "editor": {"use", "use_in_own", "edit", "edit_credentials", "move_folder"},
        "admin": {"use", "use_in_own", "edit", "edit_credentials", "move_folder", "delete", "move_out",
                  "share_outside"},
    },
    "prompt": {
        "viewer": {"use", "duplicate"},
        "editor": {"use", "duplicate", "edit", "move_folder"},
        "admin": {"use", "duplicate", "edit", "move_folder", "delete", "move_out", "share_outside"},
    },
}


def _admins(kind: str, role: str) -> set[str]:
    return set(ADMINS[kind]["admin" if role == "owner" else role])


def _expected(kind: str, role: str, policy: str) -> set[str]:
    actions = _admins(kind, role)
    if policy == "editors" and role in ("editor",):
        actions |= OUTSIDE & set(WORKSPACE_ACTIONS[kind])
    if policy == "locked":
        actions -= LOCK_REMOVES
    return actions


class TestActionsByPolicy:
    @pytest.mark.parametrize("policy", POLICIES)
    @pytest.mark.parametrize("role", ROLES)
    @pytest.mark.parametrize("kind", KINDS)
    def test_each_role_under_each_policy(self, kind, role, policy):
        assert workspace_allowed_actions(kind, role, policy=policy) == _expected(kind, role, policy)

    @pytest.mark.parametrize("kind", KINDS)
    def test_share_outside_is_in_the_table_of_every_kind(self, kind):
        assert WORKSPACE_ACTIONS[kind]["share_outside"] == "admin"

    def test_editors_too_opens_publishing_and_outside_access_to_editors(self):
        actions = workspace_allowed_actions("agent", "editor", policy="editors")
        assert {"publish", "manage_access_details", "share_outside"} <= actions
        # Moving out and deleting stay with Admins.
        assert not {"move_out", "delete"} & actions

    def test_locked_leaves_publish_to_admins_and_nothing_outside_to_the_owner(self):
        owner = workspace_allowed_actions("agent", "owner", policy="locked")
        assert "publish" in owner
        assert not LOCK_REMOVES & owner
        assert "publish" not in workspace_allowed_actions("agent", "editor", policy="locked")

    @pytest.mark.parametrize("policy", POLICIES)
    def test_viewers_never_take_anything_outside(self, policy):
        for kind in KINDS:
            assert not (OUTSIDE | {"move_out"}) & workspace_allowed_actions(kind, "viewer", policy=policy)

    def test_a_locked_team_keeps_its_folders_in(self):
        assert "move_out" in workspace_allowed_actions("folder", "admin", policy="admins")
        assert "move_out" not in workspace_allowed_actions("folder", "owner", policy="locked")
        assert "create" in workspace_allowed_actions("folder", "editor", policy="locked")

    def test_an_unknown_policy_reads_as_locked(self):
        assert workspace_allowed_actions("agent", "owner", policy="bogus") == _expected("agent", "owner", "locked")

    def test_no_role_no_actions(self):
        assert workspace_allowed_actions("agent", None, policy="editors") == set()


class TestEveryTeamCallNamesThePolicy:
    def test_the_action_table(self):
        with pytest.raises(ValueError):
            workspace_allowed_actions("agent", "admin")
        with pytest.raises(ValueError):
            workspace_allowed_actions("agent", "admin", policy=None)

    def test_build_team(self):
        with pytest.raises(ValueError):
            build_team("agent", str(uuid.uuid4()), principal_id(uuid.uuid4()), "admin")
        ra = build_team("agent", str(uuid.uuid4()), principal_id(uuid.uuid4()), "editor", policy="editors")
        assert ra.can("manage_access_details")

    def test_the_team_branch_of_payload_for(self):
        tid = str(uuid.uuid4())
        with pytest.raises(ValueError):
            payload_for("agent", None, None, team_id=tid, team_role="admin")
        locked = payload_for("agent", None, None, team_id=tid, team_role="owner", policy="locked")
        assert "manage_access_details" not in locked["allowed_actions"]
        # A personal item needs no policy.
        assert "share" in payload_for("agent", "owner", {})["allowed_actions"]


class TestPolicyRules:
    def test_outside_minimum(self):
        assert outside_minimum("admins") == "admin"
        assert outside_minimum("editors") == "editor"
        assert outside_minimum("locked") is None
        assert outside_minimum(None) is None
        assert DEFAULT_POLICY == "admins"

    @pytest.mark.parametrize(
        "role,policy,allowed",
        [
            ("admin", "admins", True), ("owner", "admins", True), ("editor", "admins", False),
            ("editor", "editors", True), ("viewer", "editors", False), ("owner", "locked", False),
            (None, "editors", False),
        ],
    )
    def test_may_take_outside(self, role, policy, allowed):
        assert may_take_outside(role, policy) is allowed

    @pytest.mark.parametrize(
        "role,current,new,allowed",
        [
            # Admins and the Owner change it while it isn't locked; locking included.
            ("admin", "admins", "editors", True),
            ("admin", "editors", "locked", True),
            ("owner", "admins", "locked", True),
            # Once locked only the Owner changes it.
            ("admin", "locked", "admins", False),
            ("admin", "locked", "editors", False),
            ("owner", "locked", "admins", True),
            # Editors and Viewers never; nobody sets an unknown value.
            ("editor", "admins", "editors", False),
            ("viewer", "admins", "locked", False),
            (None, "admins", "locked", False),
            ("owner", "admins", "everyone", False),
        ],
    )
    def test_may_set_policy(self, role, current, new, allowed):
        assert may_set_policy(role, current, new) is allowed


def _team(conn):
    row = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "alice")
    tid = str(row["id"])
    members = TeamMembersRepository(conn)
    members.add_member(tid, "alice", role="team_admin")
    members.add_member(tid, "eddie", role="team_editor")
    return tid, principal_id(tid)


def _set_policy(conn, tid, policy):
    conn.execute(text("UPDATE teams SET outside_policy = :p WHERE id = CAST(:t AS uuid)"), {"p": policy, "t": tid})


class TestThePolicyIsReadLive:
    def test_a_new_team_takes_items_out_through_its_admins(self, pg_conn):
        tid, _ = _team(pg_conn)
        assert team_policy(pg_conn, tid) == "admins"
        assert TeamsRepository(pg_conn).get(tid)["outside_policy"] == "admins"

    def test_a_missing_or_malformed_team_reads_locked(self, pg_conn):
        assert team_policy(pg_conn, str(uuid.uuid4())) == "locked"
        assert team_policy(pg_conn, "not-a-team") == "locked"

    def test_resolve_follows_the_policy_of_the_items_team(self, pg_conn):
        tid, principal = _team(pg_conn)
        aid = str(AgentsRepository(pg_conn).create(principal, "Desk", "published")["id"])
        assert not resolve(pg_conn, "agent", aid, "eddie").can("manage_access_details")
        _set_policy(pg_conn, tid, "editors")
        assert resolve(pg_conn, "agent", aid, "eddie").can("manage_access_details")
        _set_policy(pg_conn, tid, "locked")
        alice = resolve(pg_conn, "agent", aid, "alice")
        assert alice.can("publish") and not alice.can("manage_access_details") and not alice.can("export")

    def test_one_read_reads_a_teams_policy_once(self, pg_conn):
        tid, _ = _team(pg_conn)
        with cached_resolves():
            assert team_policy(pg_conn, tid) == "admins"
            _set_policy(pg_conn, tid, "locked")
            assert team_policy(pg_conn, tid) == "admins"
            # A locked read (a write about to act on it) always reads the row.
            assert team_policy(pg_conn, tid, lock="share") == "locked"
        assert team_policy(pg_conn, tid) == "locked"

    def test_the_repository_sets_and_reads_the_policy(self, pg_conn):
        tid, _ = _team(pg_conn)
        repo = TeamsRepository(pg_conn)
        assert repo.set_outside_policy(tid, "locked") == "admins"
        assert repo.get_outside_policy(tid) == "locked"
        assert repo.get_outside_policy(tid, lock="update") == "locked"
        with pytest.raises(ValueError):
            repo.set_outside_policy(tid, "everyone")
        assert repo.set_outside_policy(str(uuid.uuid4()), "admins") is None
