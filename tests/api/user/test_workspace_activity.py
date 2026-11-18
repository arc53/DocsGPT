"""Activity and artifact lists by workspace.

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


class TestWorkflowRunsListWhereTheyWereStarted:
    """A workflow run lists in the workspace of the chat that started it, while its runner may read it.

    A team's workflow agent shared into another team runs in that team's chats: its runs are that team's, as
    the run-access check lets its members read them; a run that names no chat stays with the workflow's team.
    """

    def _setup(self, conn):
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        owner, owner_principal = _team(conn)
        workflow = str(WorkflowsRepository(conn).create(owner_principal, "flow")["id"])
        agent = str(AgentsRepository(conn).create(
            owner_principal, "Flow", "published", key=f"k-{uuid.uuid4()}", workflow_id=workflow,
            agent_type="workflow",
        )["id"])
        receiving = str(TeamsRepository(conn).create("Sales", f"s-{uuid.uuid4().hex[:6]}", "sam")["id"])
        TeamMembersRepository(conn).add_member(receiving, "sam", role="team_admin")
        TeamMembersRepository(conn).add_member(receiving, "dana", role="team_viewer")
        TeamItemSharesRepository(conn).share(owner, receiving, "agent", agent, "alice")
        return owner, receiving, workflow, agent

    def _chat_message(self, conn, user, team_id, *, running=False) -> str:
        repo = ConversationsRepository(conn)
        cid = str(repo.create(user, "Chat", team_id=team_id, visibility="listed")["id"])
        status = "streaming" if running else "complete"
        message = repo.reserve_message(
            cid, prompt="q", placeholder_response="...", request_id=str(uuid.uuid4()), status=status,
        )
        return str(message["id"])

    def _run(self, conn, workflow, agent, user, *, started_by=None, status="completed") -> str:
        from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository

        inputs = {"query": "q", "agent_id": agent}
        if started_by:
            inputs["started_by"] = started_by
        ended = None if status == "running" else _now()
        return str(WorkflowRunsRepository(conn).create(
            workflow, user, status, inputs=inputs, started_at=_now() - timedelta(minutes=1), ended_at=ended,
        )["id"])

    @staticmethod
    def _history(conn, user, team_id=None) -> list:
        return [r["id"] for r in list_history(conn, user, team_id=team_id, kind="workflow")["runs"]]

    def test_a_run_from_a_receiving_teams_chat_lists_in_that_team(self, pg_conn):
        owner, receiving, workflow, agent = self._setup(pg_conn)
        run = self._run(pg_conn, workflow, agent, "dana", started_by=self._chat_message(pg_conn, "dana", receiving))

        assert self._history(pg_conn, "dana", receiving) == [run]
        assert self._history(pg_conn, "dana") == []
        assert self._history(pg_conn, "dana", owner) == []

    def test_a_running_one_folds_into_its_chat_in_that_team(self, pg_conn):
        _, receiving, workflow, agent = self._setup(pg_conn)
        message = self._chat_message(pg_conn, "dana", receiving, running=True)
        self._run(pg_conn, workflow, agent, "dana", started_by=message, status="running")

        running = build_now(pg_conn, "dana", workspace=_ws(receiving))["running"]

        assert [(r["kind"], r.get("workflow")) for r in running] == [("chat", True)]
        assert build_now(pg_conn, "dana")["running"] == []

    def test_it_leaves_the_team_when_the_share_is_revoked(self, pg_conn):
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository

        _, receiving, workflow, agent = self._setup(pg_conn)
        message = self._chat_message(pg_conn, "dana", receiving, running=True)
        self._run(pg_conn, workflow, agent, "dana", started_by=self._chat_message(pg_conn, "dana", receiving))
        self._run(pg_conn, workflow, agent, "dana", started_by=message, status="running")
        TeamItemSharesRepository(pg_conn).revoke(receiving, "agent", agent)

        assert self._history(pg_conn, "dana", receiving) == []
        running = build_now(pg_conn, "dana", workspace=_ws(receiving))["running"]
        assert [r["kind"] for r in running] == ["chat"] and not running[0].get("workflow")

    def test_the_owning_teams_own_runs_stay_in_it(self, pg_conn):
        owner, _, workflow, agent = self._setup(pg_conn)
        from_chat = self._run(pg_conn, workflow, agent, "eddie", started_by=self._chat_message(pg_conn, "eddie", owner))
        unnamed = self._run(pg_conn, workflow, agent, "eddie")

        assert sorted(self._history(pg_conn, "eddie", owner)) == sorted([from_chat, unnamed])
        assert self._history(pg_conn, "eddie") == []

    def test_someone_outside_both_teams_never_sees_it(self, pg_conn):
        _, _, workflow, agent = self._setup(pg_conn)
        # A public link's chat lives in the chatter's Personal; the run check refuses them, so Activity does too.
        self._run(pg_conn, workflow, agent, "pat", started_by=self._chat_message(pg_conn, "pat", None))

        assert self._history(pg_conn, "pat") == []
        assert build_now(pg_conn, "pat")["running"] == []
