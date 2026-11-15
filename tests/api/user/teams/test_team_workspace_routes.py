"""Teams API on the workspace roles (Owner, Admin, Editor, Viewer), with the step-1 compat fields.

Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` /
``resolve_roles`` are patched, and the route modules' sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.workspaces.principal import principal_id


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


def _people(conn, *users):
    repo = UsersRepository(conn)
    for user in users:
        repo.upsert(user, email=f"{user}@x.io")


def _team(conn, owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"), ("vera", "team_viewer"))):
    _people(conn, owner, *(u for u, _ in members))
    team = TeamsRepository(conn).create("Acme", f"acme-{uuid.uuid4().hex[:8]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _stored(conn, tid, user):
    return {m["role"] for m in TeamMembersRepository(conn).list_members(tid) if m["user_id"] == user}


def _events(conn, event):
    return conn.execute(
        text("SELECT metadata FROM auth_events WHERE event = :e ORDER BY id"), {"e": event}
    ).scalars().all()


class TestMemberAdd:
    def test_a_new_member_joins_as_viewer(self, client, db):
        tid = _team(db)
        _people(db, "nina")
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "nina"})
        assert resp.status_code == 200, resp.data
        assert _stored(db, tid, "nina") == {"team_viewer"}

    @pytest.mark.parametrize(
        "sent, stored",
        [
            ("viewer", "team_viewer"),
            ("editor", "team_editor"),
            ("admin", "team_admin"),
            ("team_member", "team_viewer"),  # today's UI
            ("team_admin", "team_admin"),  # today's UI
        ],
    )
    def test_roles_and_their_compat_names(self, client, db, sent, stored):
        tid = _team(db)
        _people(db, "nina")
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"email": "nina@x.io", "role": sent})
        assert resp.status_code == 200, resp.data
        assert _stored(db, tid, "nina") == {stored}

    @pytest.mark.parametrize("bad", ["owner", "superuser", ""])
    def test_bad_roles_are_400(self, client, db, bad):
        tid = _team(db)
        _people(db, "nina")
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "nina", "role": bad})
        assert resp.status_code == 400
        assert _stored(db, tid, "nina") == set()

    def test_an_unknown_user_id_is_404_and_writes_nothing(self, client, db):
        tid = _team(db)
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "ghost"})
        assert resp.status_code == 404
        assert UsersRepository(db).get("ghost") is None

    def test_a_principal_can_never_be_a_member(self, client, db):
        tid = _team(db)
        other = TeamsRepository(db).create("Other", f"o-{uuid.uuid4().hex[:6]}", "alice")
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": principal_id(other["id"])})
        assert resp.status_code == 404
        assert _stored(db, tid, principal_id(other["id"])) == set()

    def test_editors_cannot_add(self, client, db):
        tid = _team(db)
        _people(db, "nina")
        with _as("eddie"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "nina"})
        assert resp.status_code == 403

    def test_re_adding_with_another_role_is_a_role_change(self, client, db):
        tid = _team(db)
        with _as("adam"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "vera", "role": "editor"})
        assert resp.status_code == 200
        assert _stored(db, tid, "vera") == {"team_editor"}
        changed = _events(db, "team.member_role_changed")
        assert changed and changed[-1]["from_role"] == "viewer" and changed[-1]["role"] == "editor"


class TestRoleChange:
    @pytest.mark.parametrize(
        "sent, stored",
        [("editor", "team_editor"), ("admin", "team_admin"), ("team_member", "team_viewer"), ("viewer", "team_viewer")],
    )
    def test_admin_changes_a_role(self, client, db, sent, stored):
        tid = _team(db)
        with _as("adam"):
            resp = client.put(f"/api/teams/{tid}/members/eddie", json={"role": sent})
        assert resp.status_code == 200, resp.data
        assert _stored(db, tid, "eddie") == {stored}

    def test_role_change_is_audited(self, client, db):
        tid = _team(db)
        with _as("alice"):
            client.put(f"/api/teams/{tid}/members/vera", json={"role": "admin"})
        meta = _events(db, "team.member_role_changed")[-1]
        assert meta["team_id"] == tid
        assert meta["target_user"] == "vera"
        assert meta["from_role"] == "viewer"
        assert meta["role"] == "admin"

    def test_editor_cannot_change_roles(self, client, db):
        tid = _team(db)
        with _as("eddie"):
            resp = client.put(f"/api/teams/{tid}/members/vera", json={"role": "editor"})
        assert resp.status_code == 403
        assert _stored(db, tid, "vera") == {"team_viewer"}

    def test_owner_is_not_assignable(self, client, db):
        tid = _team(db)
        with _as("alice"):
            resp = client.put(f"/api/teams/{tid}/members/eddie", json={"role": "owner"})
        assert resp.status_code == 400
        assert TeamsRepository(db).get(tid)["owner_id"] == "alice"

    @pytest.mark.parametrize("role", ["editor", "viewer", "team_member"])
    def test_owner_cannot_be_demoted(self, client, db, role):
        tid = _team(db)
        with _as("adam"):
            resp = client.put(f"/api/teams/{tid}/members/alice", json={"role": role})
        assert resp.status_code == 403
        assert _stored(db, tid, "alice") == {"team_admin"}

    @pytest.mark.parametrize("role", ["editor", "viewer"])
    def test_last_admin_cannot_be_demoted(self, client, db, role):
        # carol owns the team but holds no admin row (an old team); bob is the only admin.
        _people(db, "carol", "bob")
        team = TeamsRepository(db).create("Old", f"old-{uuid.uuid4().hex[:6]}", "carol")
        tid = str(team["id"])
        TeamMembersRepository(db).add_member(tid, "bob", role="team_admin")
        with _as("bob"):
            resp = client.put(f"/api/teams/{tid}/members/bob", json={"role": role})
        assert resp.status_code == 409
        assert _stored(db, tid, "bob") == {"team_admin"}

    def test_admin_steps_down_while_another_admin_remains(self, client, db):
        tid = _team(db)
        with _as("adam"):
            resp = client.put(f"/api/teams/{tid}/members/adam", json={"role": "editor"})
        assert resp.status_code == 200
        assert _stored(db, tid, "adam") == {"team_editor"}


class TestPayloads:
    def test_member_rows_carry_role_and_compat(self, client, db):
        tid = _team(db)
        with _as("vera"):
            resp = client.get(f"/api/teams/{tid}/members")
        assert resp.status_code == 200
        rows = {m["user_id"]: m for m in _body(resp)["members"]}
        assert {u: m["team_role"] for u, m in rows.items()} == {
            "alice": "owner", "adam": "admin", "eddie": "editor", "vera": "viewer",
        }
        # Today's role select only knows these two values.
        assert {u: m["role"] for u, m in rows.items()} == {
            "alice": "team_admin", "adam": "team_admin", "eddie": "team_member", "vera": "team_member",
        }

    def test_team_list_detail_and_grants_carry_the_callers_role(self, client, db):
        tid = _team(db)
        for user, role, legacy in (
            ("alice", "owner", "team_admin"),
            ("adam", "admin", "team_admin"),
            ("eddie", "editor", "team_member"),
            ("vera", "viewer", "team_member"),
        ):
            with _as(user):
                teams = _body(client.get("/api/teams"))["teams"]
                detail = _body(client.get(f"/api/teams/{tid}"))["team"]
                grants = _body(client.get(f"/api/teams/{tid}/grants"))
            listed = next(t for t in teams if str(t["id"]) == tid)
            assert (listed["role"], listed["member_role"]) == (role, legacy)
            assert (detail["role"], detail["member_role"]) == (role, legacy)
            assert (grants["role"], grants["team_role"]) == (role, legacy)
            assert {m["user_id"]: m["team_role"] for m in detail["members"]}["alice"] == "owner"

    def test_create_answers_owner(self, client, db):
        _people(db, "alice")
        with _as("alice"):
            resp = client.post("/api/teams", json={"name": "New"})
        team = _body(resp)["team"]
        assert (team["role"], team["member_role"]) == ("owner", "team_admin")

    def test_grant_rows_say_where_they_come_from(self, client, db):
        tid = _team(db)
        aid = str(AgentsRepository(db).create("eddie", "Mine", "published")["id"])
        TeamResourceGrantsRepository(db).grant(tid, "agent", aid, "eddie", "eddie", access_level="viewer")
        with _as("vera"):
            grants = _body(client.get(f"/api/teams/{tid}/grants"))["grants"]
        assert grants[0]["origin"] == "personal_shared"


class TestTeamItems:
    def _team_agent(self, db, tid):
        return str(AgentsRepository(db).create(principal_id(tid), "Team agent", "published")["id"])

    @pytest.mark.parametrize("user", ["alice", "adam"])
    def test_granting_a_team_item_is_409(self, client, db, user):
        tid = _team(db)
        other = _team(db, owner="olga", members=())
        TeamMembersRepository(db).add_member(other, user, role="team_viewer")
        aid = self._team_agent(db, tid)
        with _as(user):
            resp = client.post(
                f"/api/teams/{other}/grants", json={"resource_type": "agent", "resource_id": aid}
            )
        assert resp.status_code == 409
        assert _body(resp)["error"] == "team_item"
        assert TeamResourceGrantsRepository(db).list_for_resource("agent", aid) == []

    def test_a_stranger_still_gets_404(self, client, db):
        tid = _team(db)
        other = _team(db, owner="olga", members=())
        aid = self._team_agent(db, tid)
        with _as("olga"):
            resp = client.post(
                f"/api/teams/{other}/grants", json={"resource_type": "agent", "resource_id": aid}
            )
        assert resp.status_code == 404

    def test_share_dialog_for_a_team_item(self, client, db):
        tid = _team(db)
        aid = self._team_agent(db, tid)
        with _as("vera"):
            resp = client.get(f"/api/resource_shares?resource_type=agent&resource_id={aid}")
        assert resp.status_code == 200
        body = _body(resp)
        assert body["shares"] == []
        assert body["workspace"]["kind"] == "team" and body["workspace"]["team_id"] == tid
        assert body["members_count"] == 4
        assert body["outside_access"] == {"api_key": False, "public_link": False, "webhook": False, "paid_by": None}

    def test_settings_cannot_be_changed_on_a_team_item(self, client, db):
        tid = _team(db)
        aid = self._team_agent(db, tid)
        with _as("alice"):
            resp = client.put(
                "/api/resource_settings",
                json={"resource_type": "agent", "resource_id": aid, "settings": {"editors_can_delete": True}},
            )
        assert resp.status_code == 403


class TestTeamDelete:
    def test_a_team_that_owns_items_is_409_with_counts(self, client, db):
        tid = _team(db)
        AgentsRepository(db).create(principal_id(tid), "A", "published")
        SourcesRepository(db).create("S", user_id=principal_id(tid))
        with _as("alice"):
            resp = client.delete(f"/api/teams/{tid}")
        assert resp.status_code == 409
        body = _body(resp)
        assert body["error"] == "team_not_empty"
        assert body["counts"]["agent"] == 1 and body["counts"]["source"] == 1
        assert TeamsRepository(db).get(tid) is not None

    def test_an_empty_team_is_deleted(self, client, db):
        tid = _team(db)
        with _as("alice"):
            resp = client.delete(f"/api/teams/{tid}")
        assert resp.status_code == 200
        assert TeamsRepository(db).get(tid) is None
