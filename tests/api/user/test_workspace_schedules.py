"""Schedules on a team's agents (STEP1_PLAN WP4a, D9).

A schedule on a team agent is stored under the person who set it, who pays for its runs; the run still acts as
the team's principal. Editors and up manage the team agent's schedules, the list is per workspace, and a run goes
ahead only while its setter still holds ``manage_schedules`` on the agent.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER
from docsgpt.workspaces.principal import principal_id

OWNER, ADMIN, EDITOR, VIEWER, STRANGER = "sc-alice", "sc-adam", "sc-eddie", "sc-vera", "sc-stan"


@pytest.fixture
def app():
    return Flask(__name__)


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

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method.lower())(*args)


def _team(conn) -> tuple[str, str]:
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", OWNER)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, OWNER, role="team_admin")
    for user, role in ((ADMIN, "team_admin"), (EDITOR, "team_editor"), (VIEWER, "team_viewer")):
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _agent(conn, owner) -> str:
    return str(AgentsRepository(conn).create(owner, "Bot", "published", agent_type="classic")["id"])


def _schedule(conn, user, agent_id) -> dict:
    return SchedulesRepository(conn).create(
        user_id=user, agent_id=agent_id, trigger_type="recurring", instruction="hi", cron="0 * * * *",
        next_run_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _create(app, conn, user, agent_id):
    from docsgpt.api.user.schedules.routes import AgentSchedules

    return _call(app, conn, AgentSchedules, "post", f"/api/agents/{agent_id}/schedules", user,
                 json={"instruction": "Report", "cron": "0 9 * * *"}, args=(agent_id,))


class TestCreate:
    def test_an_editors_schedule_is_stored_under_them(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        resp = _create(app, pg_conn, EDITOR, agent_id)
        assert resp.status_code == 201, resp.get_json()
        row = SchedulesRepository(pg_conn).get_internal(resp.get_json()["schedule"]["id"])
        assert row["user_id"] == EDITOR
        assert row["agent_id"] is not None

    def test_a_viewer_may_not_schedule_a_team_agent(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        assert _create(app, pg_conn, VIEWER, agent_id).status_code == 403

    def test_a_non_member_gets_404(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        assert _create(app, pg_conn, STRANGER, agent_id).status_code == 404

    def test_a_personal_agents_schedule_still_goes_under_its_owner(self, app, pg_conn):
        agent_id = _agent(pg_conn, OWNER)
        resp = _create(app, pg_conn, OWNER, agent_id)
        assert SchedulesRepository(pg_conn).get_internal(resp.get_json()["schedule"]["id"])["user_id"] == OWNER


class TestManage:
    def test_another_editor_sees_and_pauses_a_team_agents_schedule(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import AgentSchedules, ScheduleResource

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        sched = _schedule(pg_conn, EDITOR, agent_id)
        listed = _call(app, pg_conn, AgentSchedules, "get", f"/api/agents/{agent_id}/schedules", ADMIN,
                       args=(agent_id,))
        assert [s["id"] for s in listed.get_json()["schedules"]] == [str(sched["id"])]
        resp = _call(app, pg_conn, ScheduleResource, "patch", f"/api/schedules/{sched['id']}", ADMIN,
                     json={"action": "pause"}, args=(str(sched["id"]),))
        assert resp.status_code == 200, resp.get_json()
        row = SchedulesRepository(pg_conn).get_internal(str(sched["id"]))
        assert row["status"] == "paused"
        # The setter still pays: managing it changes nothing about who it belongs to.
        assert row["user_id"] == EDITOR

    def test_a_viewer_cant_reach_someone_elses_team_schedule(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import ScheduleResource

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        sched = _schedule(pg_conn, EDITOR, agent_id)
        resp = _call(app, pg_conn, ScheduleResource, "get", f"/api/schedules/{sched['id']}", VIEWER,
                     args=(str(sched["id"]),))
        assert resp.status_code == 403

    def test_a_non_member_cant_reach_a_team_schedule(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import ScheduleResource

        tid, principal = _team(pg_conn)
        agent_id = _agent(pg_conn, principal)
        sched = _schedule(pg_conn, EDITOR, agent_id)
        resp = _call(app, pg_conn, ScheduleResource, "delete", f"/api/schedules/{sched['id']}", STRANGER,
                     args=(str(sched["id"]),))
        assert resp.status_code == 404
        assert SchedulesRepository(pg_conn).get_internal(str(sched["id"])) is not None


class TestListPerWorkspace:
    def _list(self, app, conn, user, team=None):
        from docsgpt.api.user.schedules.routes import UserSchedules

        resp = _call(app, conn, UserSchedules, "get", "/api/schedules", user, team=team)
        assert resp.status_code == 200, resp.get_json()
        return resp.get_json()

    def test_a_team_lists_its_agents_schedules_and_personal_does_not(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        own_agent = _agent(pg_conn, EDITOR)
        team_sched = _schedule(pg_conn, EDITOR, team_agent)
        own_sched = _schedule(pg_conn, EDITOR, own_agent)
        admins = _schedule(pg_conn, ADMIN, team_agent)

        personal = self._list(app, pg_conn, EDITOR)
        assert [s["id"] for s in personal["schedules"]] == [str(own_sched["id"])]
        assert personal["workspace"] == {"kind": "personal", "team_id": None, "role": "owner"}

        team = self._list(app, pg_conn, EDITOR, tid)
        assert {s["id"] for s in team["schedules"]} == {str(team_sched["id"]), str(admins["id"])}
        assert team["workspace"] == {"kind": "team", "team_id": tid, "role": "editor"}
        paid_by = {s["id"]: s["paid_by"]["user_id"] for s in team["schedules"]}
        assert paid_by == {str(team_sched["id"]): EDITOR, str(admins["id"]): ADMIN}

    def test_a_viewer_lists_only_their_own_team_schedules(self, app, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = _agent(pg_conn, principal)
        _schedule(pg_conn, EDITOR, team_agent)
        mine = _schedule(pg_conn, VIEWER, team_agent)
        assert [s["id"] for s in self._list(app, pg_conn, VIEWER, tid)["schedules"]] == [str(mine["id"])]

    def test_another_teams_header_is_404(self, app, pg_conn):
        from docsgpt.api.user.schedules.routes import UserSchedules

        tid, _principal = _team(pg_conn)
        resp = _call(app, pg_conn, UserSchedules, "get", "/api/schedules", STRANGER, team=tid)
        assert resp.status_code == 404


@pytest.fixture
def patched_engine(pg_engine, monkeypatch):
    monkeypatch.setattr("docsgpt.api.user.scheduler_worker.get_engine", lambda: pg_engine)
    monkeypatch.setattr(
        "docsgpt.api.user.scheduler_worker.settings",
        type("S", (), {
            "POSTGRES_URI": str(pg_engine.url),
            "SCHEDULE_AUTOPAUSE_FAILURES": 0,
            "SCHEDULE_NOTIFY_RECURRING_FAILURES": False,
        })(),
    )
    monkeypatch.setattr("docsgpt.api.user.scheduler_worker.publish_user_event", lambda *a, **k: "1-0")
    monkeypatch.setattr("docsgpt.notifications.notify.notify_user", lambda **kw: None)
    yield pg_engine


_OK = {
    "answer": "done", "tool_calls": [], "sources": [], "thought": "", "prompt_tokens": 1,
    "generated_tokens": 1, "denied": [], "error_type": None, "model_id": "fake",
}


@pytest.mark.fresh_db
class TestRunsNeedTheSettersRole:
    def _pending(self, conn, setter):
        tid, principal = _team(conn)
        agent_id = _agent(conn, principal)
        sched = _schedule(conn, setter, agent_id)
        run = ScheduleRunsRepository(conn).record_pending(
            str(sched["id"]), setter, agent_id, datetime.now(timezone.utc),
        )
        return tid, run

    def _run(self, pg_engine, run):
        from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body

        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=_OK) as headless:
            result = execute_scheduled_run_body(str(run["id"]), "celery-ws")
        return result, headless

    def test_an_editors_schedule_runs(self, pg_engine, patched_engine):
        with pg_engine.begin() as conn:
            _tid, run = self._pending(conn, EDITOR)
        result, headless = self._run(pg_engine, run)
        assert result["status"] == "success", result
        headless.assert_called_once()

    def test_a_setter_demoted_to_viewer_stops_running(self, pg_engine, patched_engine):
        with pg_engine.begin() as conn:
            tid, run = self._pending(conn, EDITOR)
            conn.execute(
                text("UPDATE team_members SET role = 'team_viewer' WHERE team_id = CAST(:t AS uuid) AND user_id = :u"),
                {"t": tid, "u": EDITOR},
            )
        result, headless = self._run(pg_engine, run)
        headless.assert_not_called()
        assert result["status"] == "failed"

    def test_a_setter_who_left_stops_running(self, pg_engine, patched_engine):
        with pg_engine.begin() as conn:
            tid, run = self._pending(conn, EDITOR)
            conn.execute(
                text("DELETE FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = :u"),
                {"t": tid, "u": EDITOR},
            )
        result, headless = self._run(pg_engine, run)
        headless.assert_not_called()
        assert result["status"] == "failed"

    def test_a_schedule_stored_under_the_principal_never_runs(self, pg_engine, patched_engine):
        with pg_engine.begin() as conn:
            tid, principal = _team(conn)
            agent_id = _agent(conn, principal)
            sched = _schedule(conn, principal, agent_id)
            run = ScheduleRunsRepository(conn).record_pending(
                str(sched["id"]), principal, agent_id, datetime.now(timezone.utc),
            )
        result, headless = self._run(pg_engine, run)
        headless.assert_not_called()
        assert result["status"] == "failed"


@pytest.mark.fresh_db
class TestSkippedForAnInactiveAccount:
    def test_the_skip_names_owner_inactive_in_error_type(self, pg_engine, patched_engine):
        from docsgpt.api.user.scheduler_worker import execute_scheduled_run_body
        from docsgpt.storage.db.repositories.users import UsersRepository

        with pg_engine.begin() as conn:
            agent_id = _agent(conn, OWNER)
            sched = _schedule(conn, OWNER, agent_id)
            run = ScheduleRunsRepository(conn).record_pending(
                str(sched["id"]), OWNER, agent_id, datetime.now(timezone.utc),
            )
            UsersRepository(conn).upsert(OWNER)
            conn.execute(text("UPDATE users SET active = false WHERE user_id = :u"), {"u": OWNER})
        with patch("docsgpt.api.user.scheduler_worker.run_agent_headless", return_value=_OK):
            result = execute_scheduled_run_body(str(run["id"]), "celery-ws")
        assert result["status"] == "skipped"
        with pg_engine.connect() as conn:
            row = ScheduleRunsRepository(conn).get_internal(str(run["id"]))
        assert row["error_type"] == "owner_inactive"
        assert row["error"] == "owner_inactive"
