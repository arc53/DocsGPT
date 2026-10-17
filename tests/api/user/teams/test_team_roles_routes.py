"""Team sharing routes on the role model (``resource_access``), against real Postgres.

Driven through the real app.py chokepoint; only ``handle_auth`` /
``resolve_roles`` are patched, and the route modules' sessions are pointed at
the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from docsgpt.api.user.resource_access import set_settings, settings_for
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import (
    TeamResourceGrantsRepository,
)
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository


@pytest.fixture
def client():
    from docsgpt.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app.test_client()


@pytest.fixture
def db(pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    with ExitStack() as stack:
        for target in (
            "docsgpt.api.user.teams.routes.db_readonly",
            "docsgpt.api.user.teams.routes.db_session",
            "docsgpt.api.user.team_authz.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        stack.enter_context(patch("docsgpt.api.user.teams.routes.publish_user_event"))
        yield pg_conn


@contextmanager
def _as(sub, *roles):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=list(roles) or ["user"]
    ):
        yield


def _body(resp):
    return json.loads(resp.data)


def _team(conn, owner="alice", members=(("bob", "team_member"),)):
    team = TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _agent(conn, owner="alice", name="Helper"):
    return str(AgentsRepository(conn).create(owner, name, "published")["id"])


def _grant(conn, tid, rid, level="viewer", rtype="agent", owner="alice", target=None):
    TeamResourceGrantsRepository(conn).grant(
        tid, rtype, rid, owner, owner, access_level=level, target_user_id=target
    )


def _grants(conn, tid):
    return TeamResourceGrantsRepository(conn).list_for_team(tid)


# --- POST /api/teams/<tid>/grants -------------------------------------------


class TestShareNeedsShareAction:
    def test_editor_without_switch_gets_403(self, client, db):
        tid = _team(db, members=(("bob", "team_member"), ("carol", "team_member")))
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        with _as("bob"):
            resp = client.post(
                f"/api/teams/{tid}/grants",
                json={"resource_type": "agent", "resource_id": aid, "target_user_id": "carol"},
            )
        assert resp.status_code == 403

    def test_editor_with_switch_can_share_as_owner(self, client, db):
        tid = _team(db, members=(("bob", "team_member"), ("carol", "team_member")))
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.post(
                f"/api/teams/{tid}/grants",
                json={
                    "resource_type": "agent",
                    "resource_id": aid,
                    "target_user_id": "carol",
                    "access_level": "viewer",
                },
            )
        assert resp.status_code == 201
        grant = _body(resp)["grant"]
        assert grant["owner_id"] == "alice"
        assert grant["granted_by"] == "bob"

    def test_editor_with_switch_can_change_level(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.post(
                f"/api/teams/{tid}/grants",
                json={"resource_type": "agent", "resource_id": aid, "access_level": "viewer"},
            )
        assert resp.status_code == 201
        assert _grants(db, tid)[0]["access_level"] == "viewer"

    def test_viewer_gets_403(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.post(
                f"/api/teams/{tid}/grants",
                json={"resource_type": "agent", "resource_id": aid, "access_level": "editor"},
            )
        assert resp.status_code == 403

    def test_stranger_resource_is_404(self, client, db):
        tid = _team(db)
        aid = _agent(db, owner="mallory")
        with _as("bob"):
            resp = client.post(
                f"/api/teams/{tid}/grants", json={"resource_type": "agent", "resource_id": aid}
            )
        assert resp.status_code == 404
        assert _grants(db, tid) == []

    def test_owner_shares(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        with _as("alice"):
            resp = client.post(
                f"/api/teams/{tid}/grants",
                json={"resource_type": "agent", "resource_id": aid, "access_level": "editor"},
            )
        assert resp.status_code == 201
        assert _grants(db, tid)[0]["owner_id"] == "alice"

    def test_caller_must_be_member(self, client, db):
        tid = _team(db, owner="carol", members=())
        aid = _agent(db)
        with _as("alice"):
            resp = client.post(
                f"/api/teams/{tid}/grants", json={"resource_type": "agent", "resource_id": aid}
            )
        assert resp.status_code == 403


# --- DELETE /api/teams/<tid>/grants -----------------------------------------


class TestUnshare:
    def test_owner_who_left_can_unshare(self, client, db):
        tid = _team(db, owner="carol", members=(("alice", "team_member"),))
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        TeamMembersRepository(db).remove_member(tid, "alice")
        with _as("alice"):
            resp = client.delete(
                f"/api/teams/{tid}/grants?resource_type=agent&resource_id={aid}"
            )
        assert resp.status_code == 200
        assert _body(resp)["success"] is True
        assert _grants(db, tid) == []

    def test_team_admin_unshares_someone_elses(self, client, db):
        tid = _team(db, owner="carol", members=(("alice", "team_member"),))
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("carol"):
            resp = client.delete(
                f"/api/teams/{tid}/grants?resource_type=agent&resource_id={aid}"
            )
        assert resp.status_code == 200
        assert _grants(db, tid) == []

    def test_member_without_share_gets_403(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        with _as("bob"):
            resp = client.delete(
                f"/api/teams/{tid}/grants?resource_type=agent&resource_id={aid}"
            )
        assert resp.status_code == 403
        assert len(_grants(db, tid)) == 1

    def test_editor_with_switch_unshares_member_grant(self, client, db):
        tid = _team(db, members=(("bob", "team_member"), ("carol", "team_member")))
        aid = _agent(db)
        _grant(db, tid, aid, "editor", target="bob")
        _grant(db, tid, aid, "viewer", target="carol")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.delete(
                f"/api/teams/{tid}/grants?resource_type=agent&resource_id={aid}&target_user_id=carol"
            )
        assert resp.status_code == 200
        assert [g["target_user_id"] for g in _grants(db, tid)] == ["bob"]

    def test_outsider_without_share_gets_403(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("mallory"):
            resp = client.delete(
                f"/api/teams/{tid}/grants?resource_type=agent&resource_id={aid}"
            )
        assert resp.status_code == 403


# --- GET /api/resource_shares -----------------------------------------------


class TestResourceShares:
    def test_viewer_gets_403(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("bob"):
            resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 403

    def test_editor_with_switch_lists(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 200
        assert len(_body(resp)["shares"]) == 1

    def test_owner_lists(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("alice"):
            resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 200
        assert _body(resp)["shares"][0]["team_name"] == "Acme"

    def test_stranger_404(self, client, db):
        aid = _agent(db)
        with _as("mallory"):
            resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 404


# --- GET/PUT /api/resource_settings -----------------------------------------


class TestResourceSettings:
    def test_owner_get_shape(self, client, db):
        aid = _agent(db)
        with _as("alice"):
            resp = client.get(f"/api/resource_settings?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 200
        body = _body(resp)
        assert body["success"] is True
        assert body["resource_type"] == "agent"
        assert body["resource_id"] == aid
        assert body["access"] == "owner"
        assert "manage_settings" in body["allowed_actions"]
        assert body["settings"][0] == {"key": "editors_can_share", "value": False, "default": False}

    def test_viewer_can_read(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("bob"):
            resp = client.get(f"/api/resource_settings?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 200
        assert _body(resp)["access"] == "viewer"
        assert _body(resp)["allowed_actions"] == ["pin", "use"]

    def test_stranger_404(self, client, db):
        aid = _agent(db)
        with _as("mallory"):
            resp = client.get(f"/api/resource_settings?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 404

    def test_bad_type_400(self, client, db):
        with _as("alice"):
            resp = client.get(
                f"/api/resource_settings?resource_type=nope&resource_id={uuid.uuid4()}"
            )
        assert resp.status_code == 400

    def test_owner_put(self, client, db):
        aid = _agent(db)
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={
                    "resource_type": "agent",
                    "resource_id": aid,
                    "settings": {"editors_can_share": True},
                },
            )
        assert resp.status_code == 200
        body = _body(resp)
        assert body["settings"][0]["value"] is True
        assert body["access"] == "owner"
        assert settings_for(db, "agent", aid)["editors_can_share"] is True

    def test_put_reflects_new_actions_for_prompt(self, client, db):
        pid = str(PromptsRepository(db).create("alice", "P", "text")["id"])
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={
                    "resource_type": "prompt",
                    "resource_id": pid,
                    "settings": {"viewers_can_duplicate": False},
                },
            )
        assert resp.status_code == 200
        assert {s["key"]: s["value"] for s in _body(resp)["settings"]}["viewers_can_duplicate"] is False

    def test_put_unknown_key_400(self, client, db):
        aid = _agent(db)
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={"resource_type": "agent", "resource_id": aid, "settings": {"nope": True}},
            )
        assert resp.status_code == 400

    def test_put_non_bool_400(self, client, db):
        aid = _agent(db)
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={
                    "resource_type": "agent",
                    "resource_id": aid,
                    "settings": {"editors_can_share": "yes"},
                },
            )
        assert resp.status_code == 400

    def test_put_bad_type_400(self, client, db):
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={"resource_type": "nope", "resource_id": str(uuid.uuid4()), "settings": {}},
            )
        assert resp.status_code == 400

    def test_editor_put_403(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "editor")
        set_settings(db, "agent", aid, {"editors_can_share": True}, "alice")
        with _as("bob"):
            resp = client.put(
                "/api/resource_settings",
                json={
                    "resource_type": "agent",
                    "resource_id": aid,
                    "settings": {"editors_can_delete": True},
                },
            )
        assert resp.status_code == 403
        assert settings_for(db, "agent", aid)["editors_can_delete"] is False


# --- GET /api/teams/<tid>/grants --------------------------------------------


class TestGrantListing:
    def test_rows_are_enriched(self, client, db):
        UsersRepository(db).upsert("alice", email="alice@example.com")
        UsersRepository(db).upsert("bob", email="bob@example.com")
        tid = _team(db)
        aid = _agent(db, name="Support bot")
        tool = UserToolsRepository(db).create("alice", "api_tool", custom_name="CRM")
        _grant(db, tid, aid, "editor", target="bob")
        _grant(db, tid, str(tool["id"]), "viewer", rtype="tool")
        with _as("bob"):
            resp = client.get(f"/api/teams/{tid}/grants")
        assert resp.status_code == 200
        body = _body(resp)
        assert body["team_role"] == "team_member"
        by_type = {g["resource_type"]: g for g in body["grants"]}
        agent_row = by_type["agent"]
        assert agent_row["resource_name"] == "Support bot"
        assert agent_row["owner_id"] == "alice"
        assert agent_row["owner_label"] == "alice@example.com"
        assert agent_row["target_user_label"] == "bob@example.com"
        assert agent_row["granted_by_label"] == "alice@example.com"
        assert agent_row["created_at"]
        assert agent_row["access_level"] == "editor"
        assert agent_row["caller"]["access"] == "editor"
        assert "edit" in agent_row["caller"]["allowed_actions"]
        tool_row = by_type["tool"]
        assert tool_row["resource_name"] == "CRM"
        assert tool_row["target_user_label"] is None
        assert tool_row["caller"] == {
            "access": "viewer",
            "allowed_actions": ["use", "use_in_own"],
        }

    def test_owner_caller_and_missing_labels(self, client, db):
        tid = _team(db)
        aid = _agent(db)
        _grant(db, tid, aid, "viewer")
        with _as("alice"):
            body = _body(client.get(f"/api/teams/{tid}/grants"))
        row = body["grants"][0]
        assert body["team_role"] == "team_admin"
        assert row["caller"]["access"] == "owner"
        assert row["owner_label"] is None

    def test_member_does_not_see_others_personal_grants(self, client, db):
        tid = _team(db, members=(("bob", "team_member"), ("carol", "team_member")))
        a1, a2, a3 = _agent(db, name="Team"), _agent(db, name="Bob"), _agent(db, name="Carol")
        _grant(db, tid, a1, "viewer")
        _grant(db, tid, a2, "viewer", target="bob")
        _grant(db, tid, a3, "viewer", target="carol")
        with _as("bob"):
            names = {g["resource_name"] for g in _body(client.get(f"/api/teams/{tid}/grants"))["grants"]}
        assert names == {"Team", "Bob"}

    def test_admin_and_sharer_see_all(self, client, db):
        tid = _team(
            db,
            owner="carol",
            members=(("alice", "team_member"), ("bob", "team_member"), ("dave", "team_member")),
        )
        aid = _agent(db)
        _grant(db, tid, aid, "viewer", target="bob")
        with _as("carol"):  # team_admin
            assert len(_body(client.get(f"/api/teams/{tid}/grants"))["grants"]) == 1
        with _as("alice"):  # owner of the resource (has share)
            assert len(_body(client.get(f"/api/teams/{tid}/grants"))["grants"]) == 1
        with _as("dave"):
            assert _body(client.get(f"/api/teams/{tid}/grants"))["grants"] == []

    def test_resource_type_filter_kept(self, client, db):
        tid = _team(db)
        _grant(db, tid, _agent(db), "viewer")
        pid = str(PromptsRepository(db).create("alice", "P", "text")["id"])
        _grant(db, tid, pid, "viewer", rtype="prompt")
        with _as("bob"):
            body = _body(client.get(f"/api/teams/{tid}/grants?resource_type=prompt"))
        assert [g["resource_name"] for g in body["grants"]] == ["P"]


# --- Team owner protection --------------------------------------------------


class TestTeamOwnerProtection:
    def test_admin_cannot_demote_owner(self, client, db):
        tid = _team(db, members=(("bob", "team_admin"),))
        with _as("bob"):
            resp = client.put(f"/api/teams/{tid}/members/alice", json={"role": "team_member"})
        assert resp.status_code == 403
        assert TeamMembersRepository(db).role_for("alice", tid) == "team_admin"

    def test_admin_cannot_remove_owner(self, client, db):
        tid = _team(db, members=(("bob", "team_admin"),))
        with _as("bob"):
            resp = client.delete(f"/api/teams/{tid}/members/alice")
        assert resp.status_code == 403
        assert TeamMembersRepository(db).is_member("alice", tid)

    def test_owner_must_transfer_before_leaving(self, client, db):
        tid = _team(db, members=(("bob", "team_admin"),))
        with _as("alice"):
            resp = client.delete(f"/api/teams/{tid}/members/alice")
        assert resp.status_code == 400
        assert "transfer" in _body(resp)["message"].lower()
        assert TeamMembersRepository(db).is_member("alice", tid)

    def test_owner_cannot_self_demote(self, client, db):
        tid = _team(db, members=(("bob", "team_admin"),))
        with _as("alice"):
            resp = client.put(f"/api/teams/{tid}/members/alice", json={"role": "team_member"})
        assert resp.status_code == 400

    def test_admin_can_still_manage_other_admins(self, client, db):
        tid = _team(db, members=(("bob", "team_admin"), ("carol", "team_admin")))
        with _as("bob"):
            resp = client.put(f"/api/teams/{tid}/members/carol", json={"role": "team_member"})
        assert resp.status_code == 200

    def test_team_payloads_carry_is_owner(self, client, db):
        tid = _team(db)
        with _as("alice"):
            listed = _body(client.get("/api/teams"))["teams"]
            detail = _body(client.get(f"/api/teams/{tid}"))["team"]
        assert listed[0]["is_owner"] is True
        assert detail["is_owner"] is True
        assert detail["owner_id"] == "alice"
        with _as("bob"):
            assert _body(client.get("/api/teams"))["teams"][0]["is_owner"] is False
            assert _body(client.get(f"/api/teams/{tid}"))["team"]["is_owner"] is False
