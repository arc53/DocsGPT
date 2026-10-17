"""Tests for the single resource-access check (roles + per-asset switches)."""

from __future__ import annotations

import uuid

import pytest

from docsgpt.api.user.resource_access import (
    AccessDenied,
    allowed_actions,
    public_settings,
    require,
    resolve,
    set_settings,
    settings_for,
    settings_many,
)
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository


def _team(conn, owner="alice"):
    return TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)


def _share(conn, team, resource_type, resource_id, level, member="bob", owner="alice"):
    TeamMembersRepository(conn).add_member(str(team["id"]), member)
    TeamResourceGrantsRepository(conn).grant(
        str(team["id"]), resource_type, resource_id, owner, owner, access_level=level
    )


def _agent(conn, owner="alice"):
    return str(AgentsRepository(conn).create(owner, "A", "published")["id"])


class TestAllowedActions:
    def test_owner_gets_everything(self):
        actions = allowed_actions("agent", "owner", {})
        assert {"delete", "share", "manage_settings", "move_folder", "edit"} <= actions

    def test_agent_editor_defaults(self):
        actions = allowed_actions("agent", "editor", {})
        assert {"use", "edit", "publish", "view_logs", "manage_schedules", "export",
                "manage_access_details", "edit_policy"} <= actions
        assert not {"delete", "share", "manage_settings", "move_folder"} & actions

    def test_agent_viewer_defaults(self):
        actions = allowed_actions("agent", "viewer", {})
        assert actions == {"use", "pin"}

    def test_switches_widen_and_narrow(self):
        settings = {
            "editors_can_share": True,
            "editors_can_delete": True,
            "editors_can_manage_access_details": False,
            "viewers_can_see_logs": True,
        }
        editor = allowed_actions("agent", "editor", settings)
        assert {"share", "delete"} <= editor
        assert "manage_access_details" not in editor
        assert "view_logs" in allowed_actions("agent", "viewer", settings)

    def test_switches_never_touch_owner_only_settings(self):
        # Even with every switch on, managing the switches stays owner-only.
        settings = {"editors_can_share": True, "editors_can_delete": True}
        assert "manage_settings" not in allowed_actions("agent", "editor", settings)

    def test_tool_viewer_can_use_in_own_by_default(self):
        assert "use_in_own" in allowed_actions("tool", "viewer", {})
        assert "use_in_own" not in allowed_actions(
            "tool", "viewer", {"viewers_can_use_in_agents": False}
        )
        assert "edit_credentials" in allowed_actions("tool", "editor", {})
        assert "edit_credentials" not in allowed_actions(
            "tool", "editor", {"editors_can_change_credentials": False}
        )

    def test_source_and_prompt_defaults(self):
        assert "view_config" in allowed_actions("source", "viewer", {})
        assert "edit" not in allowed_actions("source", "viewer", {})
        assert "edit" in allowed_actions("source", "editor", {})
        assert "reconnect" not in allowed_actions("source", "editor", {})
        assert "duplicate" in allowed_actions("prompt", "viewer", {})
        assert "edit" in allowed_actions("prompt", "editor", {})
        assert "edit" not in allowed_actions("prompt", "viewer", {})

    def test_no_access_means_nothing(self):
        assert allowed_actions("agent", None, {}) == set()


class TestSettings:
    def test_defaults_when_no_row(self, pg_conn):
        aid = _agent(pg_conn)
        assert settings_for(pg_conn, "agent", aid) == {
            "editors_can_share": False,
            "editors_can_delete": False,
            "editors_can_manage_access_details": True,
            "viewers_can_see_logs": False,
        }

    def test_set_and_read_back(self, pg_conn):
        aid = _agent(pg_conn)
        set_settings(pg_conn, "agent", aid, {"viewers_can_see_logs": True}, "alice")
        assert settings_for(pg_conn, "agent", aid)["viewers_can_see_logs"] is True
        # A partial update keeps earlier values.
        set_settings(pg_conn, "agent", aid, {"editors_can_share": True}, "alice")
        merged = settings_for(pg_conn, "agent", aid)
        assert merged["viewers_can_see_logs"] is True
        assert merged["editors_can_share"] is True

    def test_unknown_key_rejected(self, pg_conn):
        aid = _agent(pg_conn)
        with pytest.raises(ValueError):
            set_settings(pg_conn, "agent", aid, {"viewers_can_delete": True}, "alice")
        with pytest.raises(ValueError):
            set_settings(pg_conn, "agent", aid, {"editors_can_share": "yes"}, "alice")

    def test_settings_many(self, pg_conn):
        a1, a2 = _agent(pg_conn), _agent(pg_conn)
        set_settings(pg_conn, "agent", a1, {"editors_can_delete": True}, "alice")
        many = settings_many(pg_conn, "agent", [a1, a2, "not-a-uuid"])
        assert many[a1]["editors_can_delete"] is True
        assert many[a2]["editors_can_delete"] is False
        assert many["not-a-uuid"]["editors_can_delete"] is False

    def test_public_settings_shape(self):
        rows = public_settings("prompt", {"editors_can_share": True})
        assert [r["key"] for r in rows] == ["editors_can_share", "viewers_can_duplicate"]
        assert rows[0] == {"key": "editors_can_share", "value": True, "default": False}


class TestResolve:
    def test_owner(self, pg_conn):
        aid = _agent(pg_conn)
        ra = resolve(pg_conn, "agent", aid, "alice")
        assert ra.access == "owner"
        assert ra.owner_id == "alice"
        assert ra.can("delete")

    def test_editor_and_viewer_via_team(self, pg_conn):
        team = _team(pg_conn)
        aid = _agent(pg_conn)
        _share(pg_conn, team, "agent", aid, "editor", member="bob")
        ra = resolve(pg_conn, "agent", aid, "bob")
        assert ra.access == "editor"
        assert ra.owner_id == "alice"
        assert ra.can("view_logs") and not ra.can("delete")

        aid2 = _agent(pg_conn)
        _share(pg_conn, team, "agent", aid2, "viewer", member="carol")
        rv = resolve(pg_conn, "agent", aid2, "carol")
        assert rv.access == "viewer"
        assert rv.actions == frozenset({"use", "pin"})

    def test_switch_applies_to_grantee(self, pg_conn):
        team = _team(pg_conn)
        aid = _agent(pg_conn)
        _share(pg_conn, team, "agent", aid, "viewer")
        set_settings(pg_conn, "agent", aid, {"viewers_can_see_logs": True}, "alice")
        assert resolve(pg_conn, "agent", aid, "bob").can("view_logs")

    def test_stranger_and_bad_ids(self, pg_conn):
        aid = _agent(pg_conn)
        assert resolve(pg_conn, "agent", aid, "mallory") is None
        assert resolve(pg_conn, "agent", "not-a-uuid", "alice") is None
        assert resolve(pg_conn, "agent", str(uuid.uuid4()), "alice") is None
        assert resolve(pg_conn, "nope", aid, "alice") is None

    def test_payload(self, pg_conn):
        aid = _agent(pg_conn)
        payload = resolve(pg_conn, "agent", aid, "alice").payload()
        assert payload["access"] == "owner"
        assert "delete" in payload["allowed_actions"]
        assert payload["allowed_actions"] == sorted(payload["allowed_actions"])


class TestRequire:
    def test_allowed_returns_access(self, pg_conn):
        aid = _agent(pg_conn)
        assert require(pg_conn, "agent", aid, "alice", "delete").owner_id == "alice"

    def test_visible_but_not_allowed_is_403(self, pg_conn):
        team = _team(pg_conn)
        aid = _agent(pg_conn)
        _share(pg_conn, team, "agent", aid, "viewer")
        with pytest.raises(AccessDenied) as exc:
            require(pg_conn, "agent", aid, "bob", "edit")
        assert exc.value.status == 403

    def test_invisible_is_404(self, pg_conn):
        aid = _agent(pg_conn)
        with pytest.raises(AccessDenied) as exc:
            require(pg_conn, "agent", aid, "mallory", "use")
        assert exc.value.status == 404

    def test_unknown_action_is_a_bug(self, pg_conn):
        aid = _agent(pg_conn)
        with pytest.raises(KeyError):
            require(pg_conn, "agent", aid, "alice", "fly")
