"""Activity and artifact lists by workspace (STEP1_PLAN D6, R2, R5; WP6).

Now, planned and history show one workspace: the header picks it, Personal shows
nothing of any team, and someone who left a team sees none of its things.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, request
from sqlalchemy import text

from docsgpt.activity.history import list_history
from docsgpt.activity.now import build_now
from docsgpt.activity.planned import build_planned
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.workspaces.context import WORKSPACE_HEADER, Workspace
from docsgpt.workspaces.principal import principal_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _team(conn, owner="alice", members=(("eddie", "team_editor"), ("vera", "team_viewer"))):
    team = TeamsRepository(conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", owner)
    tid = str(team["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    return tid, principal_id(tid)


def _ws(tid, role="viewer"):
    return Workspace(kind="team", team_id=tid, owner_id=principal_id(tid), role=role)


def _schedule(conn, user, agent_id, *, status="success", minutes_ago=10, name="Digest"):
    schedule = SchedulesRepository(conn).create(user, agent_id, "recurring", "digest", cron="0 15 * * *", name=name)
    runs = ScheduleRunsRepository(conn)
    when = _now() - timedelta(minutes=minutes_ago)
    run = runs.record_pending(str(schedule["id"]), user, agent_id, when)
    runs.update(str(run["id"]), {"status": status, "started_at": when, "finished_at": when + timedelta(seconds=5)})
    return str(schedule["id"]), str(run["id"])


def _running_chat(conn, user, team_id=None) -> str:
    repo = ConversationsRepository(conn)
    cid = str(repo.create(user, "Chat", team_id=team_id, visibility="listed")["id"])
    repo.reserve_message(cid, prompt="q", placeholder_response="...", request_id=str(uuid.uuid4()), status="streaming")
    return cid


class TestNow:
    def test_running_chats_split_by_workspace(self, pg_conn):
        tid, _ = _team(pg_conn)
        mine = _running_chat(pg_conn, "vera")
        ours = _running_chat(pg_conn, "vera", tid)
        personal = build_now(pg_conn, "vera")
        assert [r["conversation_id"] for r in personal["running"] if r["kind"] == "chat"] == [mine]
        team = build_now(pg_conn, "vera", workspace=_ws(tid))
        assert [r["conversation_id"] for r in team["running"] if r["kind"] == "chat"] == [ours]

    def test_failed_chats_split_by_workspace(self, pg_conn):
        tid, _ = _team(pg_conn)
        repo = ConversationsRepository(pg_conn)
        ours = str(repo.create("vera", "Chat", team_id=tid, visibility="listed")["id"])
        repo.append_message(ours, {"prompt": "q", "response": "", "status": "failed", "metadata": {}})
        pg_conn.execute(text("UPDATE conversations SET unread_at = now() WHERE id = CAST(:id AS uuid)"), {"id": ours})
        assert build_now(pg_conn, "vera")["failed_conversations"] == []
        assert build_now(pg_conn, "vera", workspace=_ws(tid))["failed_conversations"] == [ours]

    def test_schedules_on_a_team_agent_are_up_next_in_the_team_only(self, pg_conn):
        tid, principal = _team(pg_conn)
        aid = str(AgentsRepository(pg_conn).create(principal, "Team bot", "published")["id"])
        schedule = SchedulesRepository(pg_conn).create(
            "vera", aid, "once", "remind me", run_at=_now() + timedelta(hours=2), next_run_at=_now() + timedelta(hours=2)
        )
        sid = str(schedule["id"])
        assert all(item.get("schedule_id") != sid for item in build_now(pg_conn, "vera")["up_next"])
        team = build_now(pg_conn, "vera", workspace=_ws(tid))["up_next"]
        assert [item["schedule_id"] for item in team if item["kind"] == "schedule"] == [sid]


class TestHistory:
    def test_runs_on_a_team_agent_list_in_the_team_only(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = str(AgentsRepository(pg_conn).create(principal, "Team bot", "published")["id"])
        my_agent = str(AgentsRepository(pg_conn).create("vera", "My bot", "published")["id"])
        _, team_run = _schedule(pg_conn, "vera", team_agent)
        _, my_run = _schedule(pg_conn, "vera", my_agent)
        assert [r["id"] for r in list_history(pg_conn, "vera")["runs"]] == [my_run]
        team = list_history(pg_conn, "vera", team_id=tid)["runs"]
        assert [r["id"] for r in team] == [team_run]
        assert "ws_team" not in team[0]


class TestPlanned:
    def test_the_calendar_is_per_workspace(self, pg_conn):
        tid, principal = _team(pg_conn)
        team_agent = str(AgentsRepository(pg_conn).create(principal, "Team bot", "published")["id"])
        team_schedule, _ = _schedule(pg_conn, "vera", team_agent, minutes_ago=30)
        start, end = _now() - timedelta(days=1), _now() + timedelta(days=1)
        personal = build_planned(pg_conn, "vera", start, end)
        assert all(e.get("schedule_id") != team_schedule for e in personal["events"])
        team = build_planned(pg_conn, "vera", start, end, workspace=_ws(tid))
        assert any(e.get("schedule_id") == team_schedule for e in team["events"])


@pytest.fixture
def routes_conn(monkeypatch, pg_conn):
    @contextmanager
    def _yield():
        yield pg_conn

    for module in ("docsgpt.api.user.activity.routes", "docsgpt.api.user.artifacts.routes"):
        monkeypatch.setattr(f"{module}.db_readonly", _yield)
    return pg_conn


def _get(resource_cls, path, user, workspace=None, query=None):
    headers = {WORKSPACE_HEADER: workspace} if workspace is not None else {}
    with Flask(__name__).test_request_context(path, headers=headers, query_string=query or {}):
        request.decoded_token = {"sub": user}
        return resource_cls().get()


class TestRoutes:
    @pytest.mark.parametrize("path", ["now", "planned", "history"])
    def test_an_ex_member_gets_404_for_the_team(self, routes_conn, path):
        from docsgpt.api.user.activity import routes

        resource = {"now": routes.ActivityNow, "planned": routes.ActivityPlanned, "history": routes.ActivityHistory}[path]
        tid, _ = _team(routes_conn)
        _running_chat(routes_conn, "vera", tid)
        query = {"from": _now().isoformat(), "to": (_now() + timedelta(days=1)).isoformat()}
        assert _get(resource, f"/api/activity/{path}", "vera", tid, query).status_code == 200
        TeamMembersRepository(routes_conn).remove_member(tid, "vera")
        response = _get(resource, f"/api/activity/{path}", "vera", tid, query)
        assert response.status_code == 404
        assert response.get_json()["error"] == "workspace_not_found"

    def test_an_ex_members_team_chats_leave_their_personal_now(self, routes_conn):
        from docsgpt.api.user.activity.routes import ActivityNow

        tid, _ = _team(routes_conn)
        _running_chat(routes_conn, "vera", tid)
        TeamMembersRepository(routes_conn).remove_member(tid, "vera")
        body = _get(ActivityNow, "/api/activity/now", "vera").get_json()
        assert [r for r in body["running"] if r["kind"] == "chat"] == []

    def test_the_callers_artifacts_list_per_workspace(self, routes_conn):
        from docsgpt.api.user.artifacts.routes import ListArtifacts

        tid, _ = _team(routes_conn)
        repo = ConversationsRepository(routes_conn)
        mine = str(repo.create("vera", "Mine")["id"])
        ours = str(repo.create("vera", "Ours", team_id=tid)["id"])
        ids = {}
        for cid in (mine, ours):
            ids[cid] = str(routes_conn.execute(
                text(
                    "INSERT INTO artifacts (user_id, conversation_id, kind, title) "
                    "VALUES ('vera', CAST(:c AS uuid), 'document', 'Doc') RETURNING id"
                ),
                {"c": cid},
            ).scalar())
        personal = _get(ListArtifacts, "/api/artifacts", "vera").get_json()["artifacts"]
        assert [a["id"] for a in personal] == [ids[mine]]
        team = _get(ListArtifacts, "/api/artifacts", "vera", tid).get_json()["artifacts"]
        assert [a["id"] for a in team] == [ids[ours]]
        assert _get(ListArtifacts, "/api/artifacts", "eve", tid).status_code == 404
