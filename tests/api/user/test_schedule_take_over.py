"""Take over a schedule on a team agent, and the payer fields every schedule read carries.

An Editor and up of the team may make themselves the payer of a teammate's schedule: it then runs under them,
forgets the old setter's chat (a team chat is private), and starts its failure count afresh. A personal agent's
schedule is its setter's own and can't be taken over. Every schedule read says who pays (``paid_by``), why it is
paused for that payer (``paused_for``) and whether the reader may take it over (``can_take_over``).
"""

from __future__ import annotations

import json as jsonlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.quota_policies import QuotaPoliciesRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

OWNER, ADMIN, EDITOR, EDITOR2, VIEWER, STRANGER = (
    "to-alice", "to-adam", "to-eddie", "to-erin", "to-vera", "to-stan",
)


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _quota_reads_the_test_connection(request, monkeypatch):
    """Allowance checks read the test's own (uncommitted) rows."""
    if "pg_conn" not in request.fixturenames:
        return
    conn = request.getfixturevalue("pg_conn")

    @contextmanager
    def _readonly():
        yield conn

    monkeypatch.setattr("docsgpt.quotas.service.db_readonly", _readonly)
    monkeypatch.setattr(settings, "QUOTA_PERIOD", "month", raising=False)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.schedules.routes.db_session", _yield), patch(
        "docsgpt.api.user.schedules.routes.db_readonly", _yield,
    ):
        yield


def _call(app, conn, resource_cls, method, path, user, *, json=None, args=(), team=None):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    if team is not None:
        kwargs["headers"] = {WORKSPACE_HEADER: team}
    with _patch_db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return getattr(resource_cls(), method.lower())(*args)


def _take_over(app, conn, schedule_id, user):
    from docsgpt.api.user.schedules.routes import ScheduleTakeOver

    return _call(app, conn, ScheduleTakeOver, "post", f"/api/schedules/{schedule_id}/take_over", user,
                 args=(str(schedule_id),))


def _team(conn) -> tuple[str, str]:
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (EDITOR2, "team_editor"),
                       (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _agent(conn, owner) -> str:
    return str(AgentsRepository(conn).create(owner, "Bot", "published", agent_type="classic")["id"])


def _schedule(conn, user, agent_id, **fields) -> dict:
    return SchedulesRepository(conn).create(
        user_id=user, agent_id=agent_id, trigger_type="recurring", instruction="hi", cron="0 * * * *",
        next_run_at=datetime.now(timezone.utc) + timedelta(hours=1), **fields,
    )


def _team_schedule(conn, setter=EDITOR, **fields):
    tid, principal = _team(conn)
    agent_id = _agent(conn, principal)
    return tid, agent_id, _schedule(conn, principal if setter == "principal" else setter, agent_id, **fields)


def _audits(conn, schedule_id):
    rows = conn.execute(
        text(
            "SELECT actor_id, metadata FROM auth_events WHERE event = 'team.schedule_taken_over' "
            "AND metadata->>'schedule_id' = :s"
        ),
        {"s": str(schedule_id)},
    ).fetchall()
    return [(r.actor_id, r.metadata) for r in rows]


def _set_role(conn, team_id, user_id, role):
    conn.execute(
        text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"), {"t": team_id, "u": user_id}
    )
    if role:
        TeamMembersRepository(conn).add_member(team_id, user_id, role=role)


def _out_of_allowance(conn, user_id):
    QuotaPoliciesRepository(conn).upsert(scope="user", subject_id=user_id, token_limit=100)
    TokenUsageRepository(conn).insert(user_id=user_id, api_key="k", prompt_tokens=150,
                                      timestamp=datetime.now(timezone.utc))


class TestTakeOver:
    def test_an_editor_takes_over_a_teammates_schedule(self, app, pg_conn):
        tid, agent_id, _ = _team_schedule(pg_conn)
        chat = ConversationsRepository(pg_conn).create(EDITOR, "Setup chat", team_id=tid)
        sched = _schedule(pg_conn, EDITOR, agent_id, origin_conversation_id=str(chat["id"]))
        SchedulesRepository(pg_conn).bump_failure_count(str(sched["id"]))

        resp = _take_over(app, pg_conn, sched["id"], EDITOR2)

        assert resp.status_code == 200, resp.get_json()
        body = resp.get_json()
        assert body["success"] is True
        assert body["changed"] is True
        row = SchedulesRepository(pg_conn).get_internal(str(sched["id"]))
        assert row["user_id"] == EDITOR2
        assert row["origin_conversation_id"] is None
        assert row["consecutive_failure_count"] == 0
        assert row["status"] == "active"
        assert _audits(pg_conn, sched["id"]) == [(EDITOR2, {
            "team_id": tid, "schedule_id": str(sched["id"]), "agent_id": agent_id, "from": EDITOR, "to": EDITOR2,
        })]
        # The schedule in the list's shape, now paid by the caller.
        schedule = body["schedule"]
        assert schedule["id"] == str(sched["id"])
        assert schedule["agent_name"] == "Bot"
        assert schedule["paid_by"]["user_id"] == EDITOR2
        assert schedule["paused_for"] is None
        assert schedule["can_take_over"] is False
        assert schedule["origin_conversation_id"] is None

    def test_a_user_paused_schedule_stays_paused(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)
        SchedulesRepository(pg_conn).update(str(sched["id"]), EDITOR, {"status": "paused", "next_run_at": None})

        assert _take_over(app, pg_conn, sched["id"], ADMIN).status_code == 200

        assert SchedulesRepository(pg_conn).get_internal(str(sched["id"]))["status"] == "paused"

    def test_a_schedule_nobody_pays_for_can_be_taken_over(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn, setter="principal")

        resp = _take_over(app, pg_conn, sched["id"], EDITOR)

        assert resp.status_code == 200, resp.get_json()
        assert SchedulesRepository(pg_conn).get_internal(str(sched["id"]))["user_id"] == EDITOR

    def test_its_pending_runs_move_to_the_taker_and_its_history_stays_listed(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import ScheduleRunList

        _tid, agent_id, sched = _team_schedule(pg_conn)
        runs = ScheduleRunsRepository(pg_conn)
        done = runs.record_skipped(str(sched["id"]), EDITOR, agent_id, datetime.now(timezone.utc) - timedelta(hours=1),
                                   error_type="payer_left", error="payer_left")
        pending = runs.record_pending(str(sched["id"]), EDITOR, agent_id, datetime.now(timezone.utc))

        assert _take_over(app, pg_conn, sched["id"], ADMIN).status_code == 200

        assert runs.get_internal(str(pending["id"]))["user_id"] == ADMIN
        # The finished run keeps who it billed.
        assert runs.get_internal(str(done["id"]))["user_id"] == EDITOR
        listed = _call(app, pg_conn, ScheduleRunList, "get", f"/api/schedules/{sched['id']}/runs", ADMIN,
                       args=(str(sched["id"]),)).get_json()["runs"]
        assert {r["id"] for r in listed} == {str(done["id"]), str(pending["id"])}

    def test_a_repeat_call_changes_nothing(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)
        assert _take_over(app, pg_conn, sched["id"], ADMIN).get_json()["changed"] is True

        resp = _take_over(app, pg_conn, sched["id"], ADMIN)

        assert resp.status_code == 200
        assert resp.get_json()["changed"] is False
        assert len(_audits(pg_conn, sched["id"])) == 1

    def test_the_payer_calling_it_changes_nothing(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)

        resp = _take_over(app, pg_conn, sched["id"], EDITOR)

        assert resp.get_json()["changed"] is False
        assert _audits(pg_conn, sched["id"]) == []

    def test_a_viewer_is_refused(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)

        resp = _take_over(app, pg_conn, sched["id"], VIEWER)

        assert resp.status_code == 403
        assert resp.get_json()["error"] == "workspace_role_required"
        assert SchedulesRepository(pg_conn).get_internal(str(sched["id"]))["user_id"] == EDITOR

    def test_a_setter_now_a_viewer_cant_keep_it_by_taking_it_over(self, app, pg_conn):
        tid, _agent_id, sched = _team_schedule(pg_conn)
        _set_role(pg_conn, tid, EDITOR, "team_viewer")

        assert _take_over(app, pg_conn, sched["id"], EDITOR).status_code == 403

    def test_a_non_member_gets_404(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)

        resp = _take_over(app, pg_conn, sched["id"], STRANGER)

        assert resp.status_code == 404
        assert resp.get_json()["error"] == "schedule_not_found"

    def test_an_unknown_schedule_gets_404(self, app, pg_conn):
        resp = _take_over(app, pg_conn, str(uuid.uuid4()), ADMIN)

        assert resp.status_code == 404
        assert resp.get_json()["error"] == "schedule_not_found"

    def test_no_caller_is_401(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)

        assert _take_over(app, pg_conn, sched["id"], None).status_code == 401

    def test_a_personal_agents_schedule_is_refused(self, app, pg_conn):
        agent_id = _agent(pg_conn, OWNER)
        sched = _schedule(pg_conn, OWNER, agent_id)

        resp = _take_over(app, pg_conn, sched["id"], OWNER)

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "take_over_team_only"

    def test_an_agentless_schedule_is_refused(self, app, pg_conn):
        sched = _schedule(pg_conn, OWNER, None)

        resp = _take_over(app, pg_conn, sched["id"], OWNER)

        assert resp.status_code == 409
        assert resp.get_json()["error"] == "take_over_team_only"

    def test_someone_elses_personal_schedule_stays_hidden(self, app, pg_conn):
        agent_id = _agent(pg_conn, OWNER)
        sched = _schedule(pg_conn, OWNER, agent_id)

        assert _take_over(app, pg_conn, sched["id"], STRANGER).status_code == 404

    def test_a_taker_at_the_schedule_cap_is_refused(self, app, pg_conn, monkeypatch):
        monkeypatch.setattr(settings, "SCHEDULE_MAX_PER_USER", 1, raising=False)
        _tid, agent_id, sched = _team_schedule(pg_conn)
        _schedule(pg_conn, ADMIN, agent_id)

        resp = _take_over(app, pg_conn, sched["id"], ADMIN)

        assert resp.status_code == 429
        assert resp.get_json()["error"] == "max_schedules"
        assert SchedulesRepository(pg_conn).get_internal(str(sched["id"]))["user_id"] == EDITOR

    def test_a_taker_out_of_allowance_may_take_it_over_and_sees_their_own_pause(self, app, pg_conn):
        _tid, _agent_id, sched = _team_schedule(pg_conn)
        _out_of_allowance(pg_conn, ADMIN)

        resp = _take_over(app, pg_conn, sched["id"], ADMIN)

        assert resp.status_code == 200
        assert resp.get_json()["schedule"]["paused_for"]["reason"] == "payer_out_of_allowance"


class TestTokens:
    def test_a_personal_access_token_is_refused(self):
        from docsgpt.api.pat.tokens import SCOPES, expand_scopes
        from docsgpt.app import app as flask_app

        claims = {
            "sub": ADMIN, "auth_method": "pat", "pat_id": "t1", "pat_name": "ci",
            "scopes": sorted(expand_scopes(list(SCOPES))), "resource_filter": {},
        }
        with patch("docsgpt.app.handle_auth", return_value=claims):
            resp = flask_app.test_client().post(f"/api/schedules/{uuid.uuid4()}/take_over")

        assert resp.status_code == 403
        assert jsonlib.loads(resp.data)["error"] == "not_available_to_tokens"


@pytest.mark.fresh_db
class TestRunInFlight:
    def test_a_run_in_flight_keeps_its_payer(self, pg_engine, monkeypatch):
        from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body

        monkeypatch.setattr("docsgpt.api.user.scheduler_worker.get_engine", lambda: pg_engine)
        monkeypatch.setattr("docsgpt.api.user.scheduler_worker.publish_user_event", lambda *a, **k: "1-0")
        monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: None)
        with pg_engine.begin() as conn:
            _tid, agent_id, sched = _team_schedule(conn)
            run = ScheduleRunsRepository(conn).record_pending(str(sched["id"]), EDITOR, agent_id,
                                                              datetime.now(timezone.utc))
        captured = {}

        def _run_while_taken_over(agent_config, query, **kwargs):
            captured.update(kwargs)
            with pg_engine.begin() as conn:
                _take_over(Flask(__name__), conn, sched["id"], ADMIN)
            return {"answer": "ok", "tool_calls": [], "sources": [], "thought": "", "generated_tokens": 1}

        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", _run_while_taken_over):
            assert execute_scheduled_run_body(str(run["id"]), "celery-to")["status"] == "success"

        assert captured["payer"] == EDITOR
        with pg_engine.connect() as conn:
            assert ScheduleRunsRepository(conn).get_internal(str(run["id"]))["user_id"] == EDITOR
            assert SchedulesRepository(conn).get_internal(str(sched["id"]))["user_id"] == ADMIN


class TestPayloads:
    def _reads(self, app, conn, tid, agent_id, schedule_id, user):
        from docsgpt.api.user.schedules.routes import AgentSchedules, ScheduleResource, UserSchedules

        listed = _call(app, conn, UserSchedules, "get", "/api/schedules", user, team=tid).get_json()["schedules"]
        by_agent = _call(app, conn, AgentSchedules, "get", f"/api/agents/{agent_id}/schedules", user,
                         args=(agent_id,)).get_json()["schedules"]
        one = _call(app, conn, ScheduleResource, "get", f"/api/schedules/{schedule_id}", user,
                    args=(str(schedule_id),)).get_json()["schedule"]
        return [
            next(s for s in listed if s["id"] == str(schedule_id)),
            next(s for s in by_agent if s["id"] == str(schedule_id)),
            one,
        ]

    def test_a_schedule_that_runs_is_not_paused_and_an_admin_may_take_it_over(self, app, pg_conn):
        tid, agent_id, sched = _team_schedule(pg_conn)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], ADMIN):
            assert read["paused_for"] is None
            assert read["can_take_over"] is True
            assert read["paid_by"]["user_id"] == EDITOR

    def test_the_payer_cant_take_over_their_own(self, app, pg_conn):
        tid, agent_id, sched = _team_schedule(pg_conn)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], EDITOR):
            assert read["can_take_over"] is False

    def test_a_setter_who_left_reads_as_payer_left_since_its_first_skip(self, app, pg_conn):
        tid, agent_id, sched = _team_schedule(pg_conn)
        first_skip = datetime(2026, 11, 20, 9, tzinfo=timezone.utc)
        ScheduleRunsRepository(pg_conn).record_skipped(
            str(sched["id"]), EDITOR, agent_id, first_skip, error_type="payer_left", error="payer_left",
        )
        _set_role(pg_conn, tid, EDITOR, None)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], ADMIN):
            assert read["paused_for"]["reason"] == "payer_left"
            assert read["paused_for"]["until"] is None
            assert datetime.fromisoformat(read["paused_for"]["since"]) == first_skip
            assert read["can_take_over"] is True

    def test_a_pause_with_no_skip_yet_has_no_since(self, app, pg_conn):
        tid, agent_id, sched = _team_schedule(pg_conn)
        _set_role(pg_conn, tid, EDITOR, None)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], ADMIN):
            assert read["paused_for"]["since"] is None

    def test_a_schedule_a_person_paused_reports_no_payer_pause(self, app, pg_conn):
        # As the team's Usage tab and the payer's quota read it: it isn't running, so nothing pauses it for its payer.
        tid, agent_id, sched = _team_schedule(pg_conn)
        SchedulesRepository(pg_conn).update(str(sched["id"]), EDITOR, {"status": "paused", "next_run_at": None})
        _set_role(pg_conn, tid, EDITOR, None)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], ADMIN):
            assert read["status"] == "paused"
            assert read["paused_for"] is None
            assert read["can_take_over"] is True

    def test_an_out_of_allowance_payer_reads_until_the_reset(self, app, pg_conn):
        tid, agent_id, sched = _team_schedule(pg_conn)
        _out_of_allowance(pg_conn, EDITOR)

        for read in self._reads(app, pg_conn, tid, agent_id, sched["id"], EDITOR):
            assert read["paused_for"]["reason"] == "payer_out_of_allowance"
            assert read["paused_for"]["until"]

    def test_a_viewer_may_not_take_over(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import UserSchedules

        tid, agent_id, sched = _team_schedule(pg_conn)
        _schedule(pg_conn, VIEWER, agent_id)

        listed = _call(app, pg_conn, UserSchedules, "get", "/api/schedules", VIEWER, team=tid).get_json()["schedules"]

        assert listed and all(s["can_take_over"] is False for s in listed)

    def test_a_personal_agents_schedule_is_never_taken_over(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import ScheduleResource

        agent_id = _agent(pg_conn, OWNER)
        sched = _schedule(pg_conn, OWNER, agent_id)

        one = _call(app, pg_conn, ScheduleResource, "get", f"/api/schedules/{sched['id']}", OWNER,
                    args=(str(sched["id"]),)).get_json()["schedule"]

        assert one["can_take_over"] is False
        assert one["paused_for"] is None
        assert one["paid_by"] is not None

    def test_a_list_checks_each_payers_allowance_once(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import UserSchedules
        from docsgpt.quotas.service import QuotaService

        tid, agent_id, _ = _team_schedule(pg_conn)
        _schedule(pg_conn, EDITOR, agent_id)
        _schedule(pg_conn, EDITOR, agent_id)
        _schedule(pg_conn, ADMIN, agent_id)
        checked: list[str] = []
        real = QuotaService.check

        def _counting(user_id, bucket="direct", now=None):
            checked.append(user_id)
            return real(user_id, bucket, now)

        with patch("docsgpt.quotas.pause.QuotaService.check", side_effect=_counting):
            listed = _call(app, pg_conn, UserSchedules, "get", "/api/schedules", ADMIN, team=tid)

        assert len(listed.get_json()["schedules"]) == 4
        assert sorted(checked) == [ADMIN, EDITOR]
