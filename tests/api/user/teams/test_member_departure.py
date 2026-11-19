"""What a member pays for in a team, and the notice its admins get when a removal or demotion pauses it.

A team connection pauses when whoever connected it leaves or drops below Admin, so it counts too.

Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` / ``resolve_roles`` are
patched, the route module's sessions are pointed at the per-test ``pg_conn``, and ``notify_user`` is captured.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
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


@pytest.fixture
def notices():
    with patch("docsgpt.api.user.teams.routes.notify_user") as notify:
        yield notify


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _body(resp):
    return json.loads(resp.data)


def _team(conn, name="Operations"):
    users = UsersRepository(conn)
    for user in ("lena", "jonas", "dana", "tomas"):
        users.upsert(user, email=f"{user}@x.io")
    team = TeamsRepository(conn).create(name, f"ops-{uuid.uuid4().hex[:6]}", "lena")
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, "lena", role="team_admin")
    repo.add_member(tid, "jonas", role="team_admin")
    repo.add_member(tid, "dana", role="team_admin")
    repo.add_member(tid, "tomas", role="team_viewer")
    return tid


def _agent(conn, tid, name="Carrier desk", payer=None, key=False):
    return str(AgentsRepository(conn).create(
        principal_id(tid), name, "published", access_payer_id=payer,
        key=f"k-{uuid.uuid4().hex}" if key else None,
    )["id"])


def _dana_pays(conn, tid):
    """Two running schedules and one published agent paid by dana; plus things that don't count."""
    agent = _agent(conn, tid, payer="dana", key=True)
    _agent(conn, tid, name="Not published", payer="dana")
    SchedulesRepository(conn).create("dana", agent, "recurring", "One", cron="0 9 * * *")
    SchedulesRepository(conn).create("dana", agent, "recurring", "Two", cron="0 9 * * *")
    SchedulesRepository(conn).create("dana", agent, "recurring", "Off", cron="0 9 * * *", status="paused")
    mine = str(AgentsRepository(conn).create("dana", "Personal", "published", key=f"k-{uuid.uuid4().hex}")["id"])
    SchedulesRepository(conn).create("dana", mine, "recurring", "Personal", cron="0 9 * * *")
    return agent


def _connection(conn, tid, by="dana", provider="google_drive"):
    """A team connection ``by`` connected for the team."""
    return str(ConnectorSessionsRepository(conn).create(
        principal_id(tid), provider, connector_key=provider, auth_kind="oauth",
        account_label=f"{uuid.uuid4().hex[:6]}@x.io", connected_by=by,
    )["id"])


def _members(client, tid, user):
    with _as(user):
        resp = client.get(f"/api/teams/{tid}/members")
    assert resp.status_code == 200, resp.data
    return {m["user_id"]: m for m in _body(resp)["members"]}


class TestPaysFor:
    def test_admins_see_what_each_member_pays_for(self, client, db):
        tid = _team(db)
        _dana_pays(db, tid)
        members = _members(client, tid, "lena")
        assert members["dana"]["pays_for"] == {"schedules": 2, "outside_access": 1, "connections": 0}
        assert members["tomas"]["pays_for"] == {"schedules": 0, "outside_access": 0, "connections": 0}

    def test_a_viewer_does_not(self, client, db):
        tid = _team(db)
        _dana_pays(db, tid)
        members = _members(client, tid, "tomas")
        assert all("pays_for" not in m for m in members.values())

    def test_connections_they_connected_count(self, client, db):
        tid = _team(db)
        _connection(db, tid)
        _connection(db, tid, provider="github")
        _connection(db, tid, by="jonas")
        _connection(db, _team(db, name="Elsewhere"))
        members = _members(client, tid, "lena")
        assert members["dana"]["pays_for"] == {"schedules": 0, "outside_access": 0, "connections": 2}
        assert members["jonas"]["pays_for"]["connections"] == 1

    def test_counts_are_per_team(self, client, db):
        tid = _team(db)
        other = _team(db, name="Elsewhere")
        _dana_pays(db, other)
        assert _members(client, tid, "lena")["dana"]["pays_for"] == {"schedules": 0, "outside_access": 0, "connections": 0}


class TestRemovalNotice:
    def test_removal_notifies_the_other_admins_once_with_counts(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("lena"):
            assert client.delete(f"/api/teams/{tid}/members/dana").status_code == 200
        recipients = sorted(call.kwargs["user_id"] for call in notices.call_args_list)
        assert recipients == ["jonas"]  # lena did it; dana is out
        call = notices.call_args.kwargs
        assert call["kind"] == "payer_left"
        assert call["url"] == f"/teams/{tid}/usage"
        assert "dana@x.io" in call["body"] and "Operations" in call["body"]
        assert "2 schedules" in call["body"] and "1 agent" in call["body"]

    def test_a_self_leave_notifies_every_admin(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("dana"):
            assert client.delete(f"/api/teams/{tid}/members/dana").status_code == 200
        assert sorted(call.kwargs["user_id"] for call in notices.call_args_list) == ["jonas", "lena"]

    def test_nothing_when_nothing_pauses(self, client, db, notices):
        tid = _team(db)
        with _as("lena"):
            assert client.delete(f"/api/teams/{tid}/members/tomas").status_code == 200
        notices.assert_not_called()


    def test_removing_whoever_connected_an_account_counts_its_connections(self, client, db, notices):
        tid = _team(db)
        _connection(db, tid)
        with _as("lena"):
            assert client.delete(f"/api/teams/{tid}/members/dana").status_code == 200
        call = notices.call_args.kwargs
        assert call["kind"] == "payer_left"
        assert call["body"] == "dana@x.io left Operations: 1 connection is paused until someone takes over."


class TestDemotionNotice:
    def test_admin_to_editor_pauses_only_outside_access(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("lena"):
            assert client.put(f"/api/teams/{tid}/members/dana", json={"role": "editor"}).status_code == 200
        (call,) = notices.call_args_list
        body = call.kwargs["body"]
        assert call.kwargs["user_id"] == "jonas" and call.kwargs["kind"] == "payer_left"
        assert "1 agent" in body and "schedule" not in body

    def test_admin_to_viewer_pauses_both(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("lena"):
            assert client.put(f"/api/teams/{tid}/members/dana", json={"role": "viewer"}).status_code == 200
        body = notices.call_args.kwargs["body"]
        assert "2 schedules" in body and "1 agent" in body

    def test_admin_to_editor_pauses_their_connections(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        _connection(db, tid)
        _connection(db, tid, provider="github")
        with _as("lena"):
            assert client.put(f"/api/teams/{tid}/members/dana", json={"role": "editor"}).status_code == 200
        body = notices.call_args.kwargs["body"]
        assert body == (
            "dana@x.io is now an Editor in Operations: outside access on 1 agent and 2 connections are paused "
            "until someone takes over."
        )

    def test_admin_to_viewer_lists_all_three(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        _connection(db, tid)
        with _as("lena"):
            assert client.put(f"/api/teams/{tid}/members/dana", json={"role": "viewer"}).status_code == 200
        body = notices.call_args.kwargs["body"]
        assert "2 schedules, outside access on 1 agent and 1 connection are paused" in body

    def test_a_promotion_or_same_role_says_nothing(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("lena"):
            assert client.put(f"/api/teams/{tid}/members/tomas", json={"role": "admin"}).status_code == 200
            assert client.put(f"/api/teams/{tid}/members/dana", json={"role": "admin"}).status_code == 200
        notices.assert_not_called()

    def test_a_readd_with_a_lower_role_notifies(self, client, db, notices):
        tid = _team(db)
        _dana_pays(db, tid)
        with _as("lena"):
            resp = client.post(f"/api/teams/{tid}/members", json={"user_id": "dana", "role": "viewer"})
        assert resp.status_code == 200
        assert "2 schedules" in notices.call_args.kwargs["body"]

    def test_a_refused_change_says_nothing(self, client, db, notices):
        tid = _team(db)
        with _as("jonas"):
            resp = client.put(f"/api/teams/{tid}/members/lena", json={"role": "viewer"})
        assert resp.status_code in (400, 403)
        notices.assert_not_called()


class TestTeamDelete:
    def test_a_team_with_a_connection_names_it(self, client, db):
        tid = _team(db)
        _connection(db, tid)
        with _as("lena"):
            resp = client.delete(f"/api/teams/{tid}")
        assert resp.status_code == 409
        body = _body(resp)
        assert body["error"] == "team_not_empty"
        assert body["counts"] == {"connection": 1}
        assert "connections" in body["message"]


class TestKinds:
    def test_payer_left_is_a_known_admin_kind(self):
        from docsgpt.notifications.kinds import KIND_HEADINGS
        from docsgpt.workspaces.principal import ADMIN_NOTICE_KINDS

        assert "payer_left" in KIND_HEADINGS and "payer_left" in ADMIN_NOTICE_KINDS
