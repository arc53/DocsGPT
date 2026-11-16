"""``GET /api/teams/<team_id>/usage``: what a team workspace spent, for its Owner and Admins.

Driven through the real app.py chokepoint against real Postgres; only ``handle_auth`` / ``resolve_roles`` are
patched, and the modules' sessions are pointed at the per-test ``pg_conn``.
"""

from __future__ import annotations

import json
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.api.pat.tokens import expand_scopes
from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
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
            "docsgpt.api.user.teams.usage.db_readonly",
            "docsgpt.api.user.team_authz.db_readonly",
            "docsgpt.quotas.service.db_readonly",
        ):
            stack.enter_context(patch(target, _yield))
        yield pg_conn


@contextmanager
def _as(sub):
    with patch("docsgpt.app.handle_auth", return_value={"sub": sub}), patch(
        "docsgpt.app.resolve_roles", return_value=["user"]
    ):
        yield


def _body(resp):
    return json.loads(resp.data)


def _team(conn, name="Ops", owner="alice", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                    ("vera", "team_viewer"))):
    users = UsersRepository(conn)
    for user in (owner, *(u for u, _ in members)):
        users.upsert(user, email=f"{user}@x.io")
    team = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid


def _now():
    return datetime.now(timezone.utc)


def _spend(conn, user, team_id, tokens, *, kind="chat", agent_id=None, cost=0.0, request_id=None, when=None):
    TokenUsageRepository(conn).insert(
        user_id=user, prompt_tokens=tokens, team_id=team_id, run_kind=kind, agent_id=agent_id, cost=cost,
        request_id=request_id or uuid.uuid4().hex, timestamp=when or _now(),
    )


def _usage(client, tid, user="alice", period=None):
    query = f"?period={period}" if period else ""
    with _as(user):
        return client.get(f"/api/teams/{tid}/usage{query}")


class TestTotals:
    def test_totals_split_people_and_agents(self, client, db):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(principal_id(tid), "Carrier desk", "published")["id"])
        _spend(db, "eddie", tid, 100, kind="chat")  # a plain team chat, no agent
        _spend(db, "eddie", tid, 50, kind="chat", agent_id=agent, cost=0.5)
        _spend(db, "vera", tid, 30, kind="schedule", agent_id=agent, cost=0.25)
        _spend(db, "eddie", tid, 20, kind="drafter")
        resp = _usage(client, tid)
        assert resp.status_code == 200, resp.data
        body = _body(resp)
        assert body["success"] is True
        assert body["totals"] == {"tokens": 200, "cost": 0.75, "people": 2}
        assert body["split"] == {"chats": {"tokens": 170, "cost": 0.5}, "runs": {"tokens": 30, "cost": 0.25}}
        people = {row["user_id"]: row for row in body["by_person"]}
        assert people["eddie"] == {"user_id": "eddie", "label": "eddie@x.io", "role": "editor", "tokens": 170,
                                   "cost": 0.5}
        assert people["vera"]["role"] == "viewer"
        (row,) = body["by_agent"]
        assert row["agent_id"] == agent and row["name"] == "Carrier desk"
        assert row["tokens"] == 80 and row["people"] == 2 and row["requests"] >= 0
        assert row["limit_on"] is False and row["published"] is None
        assert row["moved_out"] is False

    @pytest.mark.parametrize("new_owner", ["adam", "other-team"])
    def test_an_agent_moved_out_shows_no_name_or_payer(self, client, db, new_owner):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(
            principal_id(tid), "Widget", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id="adam",
            limited_token_mode=True, token_limit=1000,
        )["id"])
        _spend(db, "adam", tid, 10, kind="published", agent_id=agent)
        owner = principal_id(_team(db, name="Elsewhere", owner="olga")) if new_owner == "other-team" else "adam"
        db.execute(text("UPDATE agents SET user_id = :o, name = 'Renamed since' WHERE id = CAST(:a AS uuid)"),
                   {"o": owner, "a": agent})

        (row,) = _body(_usage(client, tid))["by_agent"]

        # Who owns it now, its current name and its payer are not this team's to read.
        assert row["moved_out"] is True
        assert row["name"] is None and row["published"] is None and row["limit_on"] is False
        assert row["tokens"] == 10

    def test_period_names_the_window(self, client, db):
        tid = _team(db)
        body = _body(_usage(client, tid))
        start, end = window_bounds("month")
        assert body["period"] == {"kind": "month", "start": start.isoformat(), "end": end.isoformat(),
                                  "current": True}

    def test_a_departed_member_stays_with_a_null_role(self, client, db):
        tid = _team(db)
        _spend(db, "vera", tid, 40)
        TeamMembersRepository(db).change_membership(tid, "vera", None, actor="alice")
        (row,) = _body(_usage(client, tid))["by_person"]
        assert row["user_id"] == "vera" and row["role"] is None and row["tokens"] == 40

    def test_a_deleted_agent_drops_out_of_the_list_but_its_spend_stays(self, client, db):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(principal_id(tid), "Gone", "published")["id"])
        _spend(db, "eddie", tid, 60, agent_id=agent)
        AgentsRepository(db).delete(agent, principal_id(tid))
        body = _body(_usage(client, tid))
        assert body["by_agent"] == []
        assert body["totals"]["tokens"] == 60

    def test_published_agent_names_its_payer_and_limit(self, client, db):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(
            principal_id(tid), "Widget", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id="adam",
            limited_token_mode=True, token_limit=1000,
        )["id"])
        _spend(db, "adam", tid, 10, kind="published", agent_id=agent)
        (row,) = _body(_usage(client, tid))["by_agent"]
        assert row["limit_on"] is True
        assert row["published"] == {"paid_by": {"user_id": "adam", "label": "adam@x.io"}}


class TestScope:
    def test_personal_and_other_team_rows_never_count(self, client, db):
        tid = _team(db)
        other = _team(db, name="Elsewhere", owner="olga", members=(("eddie", "team_admin"),))
        _spend(db, "eddie", tid, 10)
        _spend(db, "eddie", None, 500)  # Personal
        _spend(db, "eddie", other, 700)  # another team
        body = _body(_usage(client, tid))
        assert body["totals"]["tokens"] == 10
        assert [row["tokens"] for row in body["by_person"]] == [10]

    def test_previous_period(self, client, db):
        tid = _team(db)
        start, _ = window_bounds("month")
        _spend(db, "eddie", tid, 70, when=start - timedelta(days=2))
        _spend(db, "eddie", tid, 5)
        current = _body(_usage(client, tid))
        previous = _body(_usage(client, tid, period="previous"))
        assert current["totals"]["tokens"] == 5
        assert previous["totals"]["tokens"] == 70
        prev_start, prev_end = window_bounds("month", start - timedelta(microseconds=1))
        assert previous["period"] == {"kind": "month", "start": prev_start.isoformat(),
                                      "end": prev_end.isoformat(), "current": False}

    def test_an_unknown_period_is_400(self, client, db):
        tid = _team(db)
        assert _usage(client, tid, period="forever").status_code == 400


class TestWho:
    @pytest.mark.parametrize("user", ["alice", "adam"])
    def test_owner_and_admins_read_it(self, client, db, user):
        tid = _team(db)
        assert _usage(client, tid, user).status_code == 200

    @pytest.mark.parametrize("user", ["eddie", "vera"])
    def test_below_admin_is_403(self, client, db, user):
        tid = _team(db)
        resp = _usage(client, tid, user)
        assert resp.status_code == 403
        assert _body(resp)["error"] == "workspace_role_required"

    def test_a_non_member_is_404(self, client, db):
        tid = _team(db)
        UsersRepository(db).upsert("olga")
        assert _usage(client, tid, "olga").status_code == 404

    def test_an_instance_admin_who_is_not_in_the_team_is_404(self, client, db):
        tid = _team(db)
        with patch("docsgpt.app.handle_auth", return_value={"sub": "root"}), patch(
            "docsgpt.app.resolve_roles", return_value=["admin", "user"]
        ):
            assert client.get(f"/api/teams/{tid}/usage").status_code == 404

    def test_a_token_is_refused(self, client, db):
        tid = _team(db)
        claims = {"sub": "alice", "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
                  "scopes": sorted(expand_scopes(["teams:read"])), "resource_filter": {}}
        with patch("docsgpt.app.handle_auth", return_value=claims):
            resp = client.get(f"/api/teams/{tid}/usage")
        assert resp.status_code == 403
        assert _body(resp)["error"] == "not_available_to_tokens"


class TestPaused:
    def test_lists_a_schedule_published_access_and_a_source_sync_with_reasons(self, client, db):
        tid = _team(db)
        principal = principal_id(tid)
        agent = str(AgentsRepository(db).create(
            principal, "Carrier desk", "published", key=f"k-{uuid.uuid4().hex}", access_payer_id="eddie",
        )["id"])
        quiet = str(AgentsRepository(db).create(principal, "Quiet", "published")["id"])
        # vera is a Viewer: her schedule has no payer in the team any more.
        schedule = str(SchedulesRepository(db).create(
            "vera", agent, "recurring", "Report", cron="0 9 * * *", name="Morning report",
        )["id"])
        # eddie's schedule runs: he is an Editor and has allowance.
        SchedulesRepository(db).create("eddie", quiet, "recurring", "Fine", cron="0 9 * * *")
        source = str(SourcesRepository(db).create(
            "Carrier docs", user_id=principal,
            metadata={"sync_paused": {"reason": "sync_no_payer", "since": "2026-11-01T00:00:00+00:00"}},
        )["id"])
        body = _body(_usage(client, tid))
        paused = {item["type"]: item for item in body["paused"]}
        assert set(paused) == {"schedule", "outside_access", "source_sync"}
        assert len(body["paused"]) == 3
        assert paused["schedule"]["id"] == schedule
        assert paused["schedule"]["name"] == "Morning report"
        assert paused["schedule"]["agent"] == {"id": agent, "name": "Carrier desk"}
        assert paused["schedule"]["paused_for"] == {"reason": "payer_left", "until": None, "left_team": False}
        assert paused["schedule"]["paid_by"] == {"user_id": "vera", "label": "vera@x.io"}
        assert paused["outside_access"]["agent"] == {"id": agent, "name": "Carrier desk"}
        assert paused["outside_access"]["access"] == ["api_key"]
        assert paused["outside_access"]["paused_for"] == {"reason": "payer_left", "until": None, "left_team": False}
        assert paused["outside_access"]["paid_by"] == {"user_id": "eddie", "label": "eddie@x.io"}
        assert paused["source_sync"]["id"] == source and paused["source_sync"]["name"] == "Carrier docs"
        assert paused["source_sync"]["paused_for"] == {"reason": "sync_no_payer",
                                                       "since": "2026-11-01T00:00:00+00:00"}

    def test_a_payer_out_of_allowance_is_listed_with_the_reset(self, client, db):
        tid = _team(db)
        agent = str(AgentsRepository(db).create(principal_id(tid), "Desk", "published")["id"])
        SchedulesRepository(db).create("eddie", agent, "recurring", "Go", cron="0 9 * * *")
        QuotaPoliciesRepository(db).upsert(scope="user", subject_id="eddie", token_limit=10)
        _spend(db, "eddie", None, 50)
        (item,) = _body(_usage(client, tid))["paused"]
        _, resets = window_bounds("month")
        assert item["paused_for"] == {"reason": "payer_out_of_allowance", "until": resets.isoformat()}

    def test_a_user_paused_schedule_and_other_teams_are_not_listed(self, client, db):
        tid = _team(db)
        other = _team(db, name="Elsewhere", owner="olga", members=())
        mine = str(AgentsRepository(db).create(principal_id(tid), "Desk", "published")["id"])
        theirs = str(AgentsRepository(db).create(principal_id(other), "Theirs", "published")["id"])
        SchedulesRepository(db).create("vera", mine, "recurring", "Off", cron="0 9 * * *", status="paused")
        SchedulesRepository(db).create("vera", theirs, "recurring", "Elsewhere", cron="0 9 * * *")
        assert _body(_usage(client, tid))["paused"] == []
