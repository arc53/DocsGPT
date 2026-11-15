"""The workspace branch of ``resource_access``: team-owned items resolve from the caller's team role only.

The expected action table below is the decided one, copied on purpose, not imported, so a change to
``WORKSPACE_ACTIONS`` that drifts from the decided table fails here.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from docsgpt.agents.default_tools import default_tool_id
from docsgpt.api.user.resource_access import (
    ACTIONS,
    CODE_WORKSPACE_MISMATCH,
    WORKSPACE_ACTIONS,
    AccessDenied,
    _user_labels,
    borrowed_refs,
    can_sponsor_ref,
    can_use_ref,
    payload_for,
    plan_sponsors,
    require,
    resolve,
    resource_owner,
    set_settings,
    sponsor_state,
    workspace_mismatch_refusal,
    workspace_mismatches,
)
from docsgpt.api.user.team_sharing import effective_write_owner
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FoldersRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.team_scope import TeamScopeRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id

# WORKSPACE_ACTIONS as decided: the weakest team role per action on a team-owned item.
EXPECTED = {
    "agent": {
        "viewer": {"use", "pin"},
        "editor": {"view", "edit", "edit_policy", "view_logs", "manage_schedules", "export", "move_folder"},
        "admin": {"publish", "manage_access_details", "delete", "move_out"},
    },
    "source": {
        "viewer": {"use", "view_config"},
        "editor": {"edit", "move_folder"},
        "admin": {"reconnect", "delete", "move_out"},
    },
    "tool": {
        "viewer": {"use", "use_in_own"},
        "editor": {"edit", "edit_credentials", "move_folder"},
        "admin": {"delete", "move_out"},
    },
    "prompt": {
        "viewer": {"use", "duplicate"},
        "editor": {"edit", "move_folder"},
        "admin": {"delete", "move_out"},
    },
}

_ORDER = ("viewer", "editor", "admin")


def _expected(kind: str, role: str) -> set[str]:
    level = "admin" if role == "owner" else role
    out: set[str] = set()
    for step in _ORDER[: _ORDER.index(level) + 1]:
        out |= EXPECTED[kind][step]
    return out


def _team(conn, owner="alice", name="Ops", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _item(conn, kind: str, owner: str, name: str = "Thing") -> str:
    if kind == "agent":
        row = AgentsRepository(conn).create(owner, name, "published")
    elif kind == "source":
        row = SourcesRepository(conn).create(name, user_id=owner)
    elif kind == "prompt":
        row = PromptsRepository(conn).create(owner, name, "Be brief.")
    else:
        row = UserToolsRepository(conn).create(owner, "api_tool")
    return str(row["id"])


ROLES = {"owner": "alice", "admin": "adam", "editor": "eddie", "viewer": "vera"}


class TestTableMatchesThePlan:
    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    def test_workspace_actions_table(self, kind):
        table = WORKSPACE_ACTIONS[kind]
        for role in _ORDER:
            assert {a for a, r in table.items() if r == role} == EXPECTED[kind][role]

    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    def test_share_and_settings_are_absent_for_team_items(self, kind):
        assert "share" not in WORKSPACE_ACTIONS[kind]
        assert "manage_settings" not in WORKSPACE_ACTIONS[kind]
        assert "move_to_team" not in WORKSPACE_ACTIONS[kind]

    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    def test_move_to_team_is_owner_only_on_personal_items(self, kind):
        assert ACTIONS[kind]["move_to_team"] == "owner"

    def test_folder_tree_actions(self):
        folder = WORKSPACE_ACTIONS["folder"]
        assert folder["list"] == "viewer"
        assert {a for a, r in folder.items() if r == "editor"} == {"create", "rename", "move", "file", "delete"}
        assert folder["move_out"] == "admin"


class TestResolveMatrix:
    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    @pytest.mark.parametrize("role", ["owner", "admin", "editor", "viewer"])
    def test_role_decides(self, pg_conn, kind, role):
        tid, principal = _team(pg_conn)
        rid = _item(pg_conn, kind, principal)
        ra = resolve(pg_conn, kind, rid, ROLES[role])
        assert ra is not None
        assert ra.access == ("admin" if role in ("owner", "admin") else role)
        assert ra.access != "owner"
        assert ra.team_role == role
        assert ra.team_id == tid
        assert ra.owner_id == principal
        assert set(ra.actions) == _expected(kind, role)

    @pytest.mark.parametrize("kind", ["agent", "source", "tool", "prompt"])
    def test_non_member_gets_nothing(self, pg_conn, kind):
        _, principal = _team(pg_conn)
        rid = _item(pg_conn, kind, principal)
        assert resolve(pg_conn, kind, rid, "nora") is None
        with pytest.raises(AccessDenied) as denied:
            require(pg_conn, kind, rid, "nora", "use")
        assert denied.value.status == 404

    def test_switches_do_not_apply(self, pg_conn):
        _, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        set_settings(pg_conn, "agent", aid, {"viewers_can_see_logs": True, "editors_can_delete": True}, "alice")
        assert not resolve(pg_conn, "agent", aid, "vera").can("view_logs")
        assert not resolve(pg_conn, "agent", aid, "eddie").can("delete")

    def test_require_on_team_items(self, pg_conn):
        _, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        assert require(pg_conn, "agent", aid, "adam", "move_out").owner_id == principal
        for action in ("share", "manage_settings", "move_to_team"):
            with pytest.raises(AccessDenied) as denied:
                require(pg_conn, "agent", aid, "alice", action)
            assert denied.value.status == 403
        with pytest.raises(AccessDenied) as denied:
            require(pg_conn, "agent", aid, "eddie", "publish")
        assert denied.value.status == 403

    def test_move_to_team_needs_the_person_owner(self, pg_conn):
        tid, _ = _team(pg_conn)
        aid = _item(pg_conn, "agent", "eddie")
        assert require(pg_conn, "agent", aid, "eddie", "move_to_team").access == "owner"
        TeamResourceGrantsRepository(pg_conn).grant(tid, "agent", aid, "eddie", "eddie", access_level="editor")
        with pytest.raises(AccessDenied) as denied:
            require(pg_conn, "agent", aid, "vera", "move_to_team")
        assert denied.value.status == 403
        with pytest.raises(AccessDenied):
            require(pg_conn, "agent", aid, "eddie", "move_out")

    def test_personal_items_are_unchanged(self, pg_conn):
        tid, _ = _team(pg_conn)
        aid = _item(pg_conn, "agent", "eddie")
        TeamResourceGrantsRepository(pg_conn).grant(tid, "agent", aid, "eddie", "eddie", access_level="viewer")
        ra = resolve(pg_conn, "agent", aid, "vera")
        assert ra.access == "viewer"
        assert ra.team_id is None and ra.team_role is None
        assert resolve(pg_conn, "agent", aid, "eddie").access == "owner"


class TestFailsClosed:
    def _stale_grant(self, conn, tid, rid, owner, level="editor"):
        conn.execute(
            text(
                "INSERT INTO team_resource_grants (team_id, resource_type, resource_id, owner_id, granted_by, "
                "access_level) VALUES (CAST(:t AS uuid), 'agent', CAST(:r AS uuid), :o, :o, :l)"
            ),
            {"t": tid, "r": rid, "o": owner, "l": level},
        )

    def test_stale_grant_left_from_before_a_move_gives_nothing(self, pg_conn):
        _, principal = _team(pg_conn)
        other_tid, _ = _team(pg_conn, owner="olga", name="Other", members=(("nora", "team_viewer"),))
        aid = _item(pg_conn, "agent", principal)
        # A grant row whose denormalised owner is the person who used to own it (passes the CHECK).
        self._stale_grant(pg_conn, other_tid, aid, "alice")
        assert resolve(pg_conn, "agent", aid, "nora") is None
        scope = TeamScopeRepository(pg_conn)
        assert scope.effective_access("nora", "agent", aid) is None
        assert not scope.can_read("nora", "agent", aid)
        assert aid not in scope.visible_with_access("nora", "agent")
        assert aid not in scope.visible_resource_ids("nora", "agent")

    def test_forced_grant_with_a_principal_owner_gives_nothing(self, pg_conn):
        _, principal = _team(pg_conn)
        other_tid, _ = _team(pg_conn, owner="olga", name="Other", members=(("nora", "team_viewer"),))
        aid = _item(pg_conn, "agent", principal)
        pg_conn.execute(
            text("ALTER TABLE team_resource_grants DROP CONSTRAINT team_resource_grants_personal_owner_chk")
        )
        self._stale_grant(pg_conn, other_tid, aid, principal)
        assert resolve(pg_conn, "agent", aid, "nora") is None
        assert TeamScopeRepository(pg_conn).visible_with_access("nora", "agent") == {}

    def test_a_grant_never_raises_a_members_role(self, pg_conn):
        tid, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        self._stale_grant(pg_conn, tid, aid, "alice", level="editor")
        ra = resolve(pg_conn, "agent", aid, "vera")
        assert ra.access == "viewer"
        assert not ra.can("edit")

    def test_instance_admin_has_no_item_access(self, pg_conn):
        _, principal = _team(pg_conn)
        pg_conn.execute(text("INSERT INTO user_roles (user_id, role) VALUES ('root', 'admin')"))
        for kind in ("agent", "source", "tool", "prompt"):
            assert resolve(pg_conn, kind, _item(pg_conn, kind, principal), "root") is None

    def test_another_teams_principal_gets_nothing(self, pg_conn):
        _, principal = _team(pg_conn)
        _, other = _team(pg_conn, owner="olga", name="Other", members=())
        aid = _item(pg_conn, "agent", principal)
        assert resolve(pg_conn, "agent", aid, other) is None

    def test_a_removed_member_loses_access_at_once(self, pg_conn):
        tid, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        assert resolve(pg_conn, "agent", aid, "vera") is not None
        TeamMembersRepository(pg_conn).remove_member(tid, "vera")
        assert resolve(pg_conn, "agent", aid, "vera") is None


class TestPrincipal:
    @pytest.mark.parametrize("kind", ["source", "tool", "prompt"])
    def test_principal_resolves_its_own_items(self, pg_conn, kind):
        tid, principal = _team(pg_conn)
        rid = _item(pg_conn, kind, principal)
        ra = resolve(pg_conn, kind, rid, principal)
        assert ra.access == "owner"
        assert ra.team_id == tid
        assert can_use_ref(pg_conn, kind, rid, principal)

    def test_principal_cannot_use_a_members_personal_item(self, pg_conn):
        _, principal = _team(pg_conn)
        sid = _item(pg_conn, "source", "eddie")
        assert not can_use_ref(pg_conn, "source", sid, principal)

    def test_resource_owner(self, pg_conn):
        _, principal = _team(pg_conn)
        sid = _item(pg_conn, "source", principal)
        assert resource_owner(pg_conn, "source", sid) == principal
        assert resource_owner(pg_conn, "source", str(uuid.uuid4())) is None
        assert resource_owner(pg_conn, "source", "not-a-uuid") is None


class TestWriteOwner:
    @pytest.mark.parametrize("user", ["alice", "adam", "eddie"])
    def test_editors_and_up_write_as_the_principal(self, pg_conn, user):
        _, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        assert effective_write_owner(pg_conn, "agent", aid, user) == principal

    @pytest.mark.parametrize("user", ["vera", "nora"])
    def test_viewers_and_strangers_cannot_write(self, pg_conn, user):
        _, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        assert effective_write_owner(pg_conn, "agent", aid, user) is None

    def test_personal_editor_grant_still_writes_as_the_owner(self, pg_conn):
        tid, _ = _team(pg_conn)
        aid = _item(pg_conn, "agent", "eddie")
        TeamResourceGrantsRepository(pg_conn).grant(tid, "agent", aid, "eddie", "eddie", access_level="editor")
        assert effective_write_owner(pg_conn, "agent", aid, "vera") == "eddie"


class TestPayload:
    def test_team_item_payload(self, pg_conn):
        tid, principal = _team(pg_conn)
        aid = _item(pg_conn, "agent", principal)
        payload = resolve(pg_conn, "agent", aid, "eddie").payload()
        assert payload["access"] == "editor"
        assert payload["team_role"] == "editor"
        assert payload["origin"] == "team"
        assert payload["workspace"] == {"kind": "team", "team_id": tid}
        assert set(payload["allowed_actions"]) == _expected("agent", "editor")

    def test_personal_payloads(self, pg_conn):
        tid, _ = _team(pg_conn)
        aid = _item(pg_conn, "agent", "eddie")
        TeamResourceGrantsRepository(pg_conn).grant(tid, "agent", aid, "eddie", "eddie", access_level="viewer")
        own = resolve(pg_conn, "agent", aid, "eddie").payload()
        shared = resolve(pg_conn, "agent", aid, "vera").payload()
        assert own["origin"] == "own" and shared["origin"] == "shared"
        assert own["workspace"] == shared["workspace"] == {"kind": "personal", "team_id": None}
        assert own["team_role"] is None

    def test_payload_for_lists(self):
        tid = str(uuid.uuid4())
        team = payload_for("prompt", None, None, team_id=tid, team_role="owner")
        assert team["access"] == "admin"
        assert team["team_role"] == "owner"
        assert team["origin"] == "team"
        assert team["workspace"] == {"kind": "team", "team_id": tid}
        assert set(team["allowed_actions"]) == _expected("prompt", "owner")
        personal = payload_for("prompt", "owner", {})
        assert personal["origin"] == "own"
        assert "move_to_team" in personal["allowed_actions"]
        assert payload_for("prompt", "viewer", {})["origin"] == "shared"
        # No role in the team, no actions: fails closed.
        assert payload_for("prompt", None, None, team_id=tid, team_role=None)["allowed_actions"] == []


class TestSponsorsOnTeamHolders:
    def test_team_holder_takes_no_sponsors(self, pg_conn):
        _, principal = _team(pg_conn)
        holder = AgentsRepository(pg_conn).create(principal, "Team agent", "published")
        sid = _item(pg_conn, "source", "eddie")
        plan = plan_sponsors(
            pg_conn, "agent", holder, principal, "eddie", [("source", sid)], confirmed=[f"source:{sid}"]
        )
        assert plan.sponsors == {}
        assert plan.needs_confirmation == []
        assert plan.not_allowed == [("source", sid)]

    def test_team_holder_records_are_ignored(self, pg_conn):
        _, principal = _team(pg_conn)
        sid = _item(pg_conn, "source", "eddie")
        holder = {"id": str(uuid.uuid4()), "user_id": principal, "resource_sponsors": {f"source:{sid}": "eddie"}}
        assert sponsor_state(pg_conn, "agent", holder, "source", sid) == (None, None)

    def test_a_principal_is_never_a_sponsor(self, pg_conn):
        _, principal = _team(pg_conn)
        sid = _item(pg_conn, "source", principal)
        aid = AgentsRepository(pg_conn).create("eddie", "Mine", "published")
        holder = {**aid, "resource_sponsors": {f"source:{sid}": principal}}
        sponsor, reason = sponsor_state(pg_conn, "agent", holder, "source", sid)
        assert sponsor is None and reason is None


    def test_a_team_item_is_never_sponsored_onto_a_personal_agent(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_source = _item(pg_conn, "source", principal)
        holder = AgentsRepository(pg_conn).create("olga", "Olga's agent", "published")
        # eddie edits olga's agent through a grant, and edits the team's source as a team Editor.
        TeamResourceGrantsRepository(pg_conn).grant(tid, "agent", str(holder["id"]), "olga", "olga", "editor")
        assert not can_sponsor_ref(pg_conn, "source", team_source, "eddie")
        plan = plan_sponsors(pg_conn, "agent", holder, "olga", "eddie", [("source", team_source)])
        assert plan.not_allowed == [("source", team_source.lower())]
        assert plan.sponsors == {} and plan.needs_confirmation == []


class TestWorkspaceMismatch:
    def test_team_holder_refs(self, pg_conn):
        _, principal = _team(pg_conn)
        _, other = _team(pg_conn, owner="olga", name="Other", members=())
        own_source = _item(pg_conn, "source", principal)
        own_tool = _item(pg_conn, "tool", principal)
        personal_source = _item(pg_conn, "source", "eddie")
        foreign_prompt = _item(pg_conn, "prompt", other)
        team_folder = str(FoldersRepository(pg_conn).create(principal, "Team docs")["id"])
        personal_folder = str(FoldersRepository(pg_conn).create("eddie", "Mine")["id"])
        refs = [
            ("source", own_source),
            ("tool", own_tool),
            ("source", personal_source),
            ("prompt", foreign_prompt),
            ("prompt", "default"),
            ("source", "default"),
            ("tool", default_tool_id("memory")),
            ("source", str(uuid.uuid4())),  # gone: runs nowhere, not a mismatch
            ("folder", team_folder),
            ("folder", personal_folder),
            ("source", ""),
        ]
        assert workspace_mismatches(pg_conn, principal, refs) == [
            ("source", personal_source.lower()),
            ("prompt", foreign_prompt.lower()),
            ("folder", personal_folder.lower()),
        ]

    def test_an_unknown_kind_or_a_legacy_id_fails_closed(self, pg_conn):
        _, principal = _team(pg_conn)
        assert workspace_mismatches(pg_conn, principal, [("source", "65f0c0ffee"), ("widget", "x")]) == [
            ("source", "65f0c0ffee"),
            ("widget", "x"),
        ]

    def test_personal_holders_are_not_judged_here(self, pg_conn):
        _, principal = _team(pg_conn)
        team_source = _item(pg_conn, "source", principal)
        assert workspace_mismatches(pg_conn, "eddie", [("source", team_source)]) == []

    def test_refusal_names_only_what_the_caller_sees(self, pg_conn):
        _, principal = _team(pg_conn)
        mine = _item(pg_conn, "source", "eddie", name="My notes")
        theirs = _item(pg_conn, "source", "olga", name="Secret")
        body, status = workspace_mismatch_refusal(pg_conn, [("source", mine), ("source", theirs)], "eddie")
        assert status == 400
        assert body["code"] == CODE_WORKSPACE_MISMATCH
        assert body["error"] == CODE_WORKSPACE_MISMATCH
        names = {r["id"]: r["name"] for r in body["resources"]}
        assert names == {mine: "My notes", theirs: None}
        assert {r["key"] for r in body["resources"]} == {f"source:{mine}", f"source:{theirs}"}


class TestBorrowedAndLabels:
    def test_a_team_item_on_a_personal_agent_is_borrowed(self, pg_conn):
        _, principal = _team(pg_conn)
        team_source = _item(pg_conn, "source", principal)
        team_tool = _item(pg_conn, "tool", principal)
        assert borrowed_refs(pg_conn, "eddie", [("source", team_source), ("tool", team_tool)]) == [
            ("source", team_source.lower()),
            ("tool", team_tool.lower()),
        ]

    def test_a_team_agent_using_its_own_items_borrows_nothing(self, pg_conn):
        _, principal = _team(pg_conn)
        team_source = _item(pg_conn, "source", principal)
        assert borrowed_refs(pg_conn, principal, [("source", team_source)]) == []

    def test_principal_is_labelled_with_the_team_name(self, pg_conn):
        _, principal = _team(pg_conn, name="Support")
        UsersRepository(pg_conn).upsert("eddie", email="eddie@x.io")
        labels = _user_labels(pg_conn, [principal, "eddie", "vera"])
        assert labels == {principal: "Support", "eddie": "eddie@x.io"}
