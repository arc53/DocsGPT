"""The Logs timeline (``/api/get_user_logs``) of someone who left a team leaves out that team's rows.

A member's own rows in a team (chat answers, answers still being written, scheduled runs, workflow runs, request
errors and searches on the team's agents) list while they are in it. After they leave they read as gone, as their
team chats and runs do elsewhere; their Personal rows stay, and re-adding them brings the team's back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.request_traces import RequestTracesRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.stack_logs import StackLogsRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_logs import UserLogsRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.principal import principal_id

MEMBER = "lx-vera"


@pytest.fixture(autouse=True)
def _no_webhook_markers():
    with patch("docsgpt.api.user.analytics.routes.list_runs", lambda user_id: []):
        yield


def _logs(conn, user: str = MEMBER) -> list[dict]:
    from docsgpt.api.user.analytics.routes import GetUserLogs

    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.analytics.routes.db_readonly", _yield), Flask(__name__).test_request_context(
        "/api/get_user_logs", method="POST", json={"page_size": 100}
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        response = GetUserLogs().post()
    assert response.status_code == 200
    return response.json["logs"]


def _workspace_rows(conn, owner: str, tag: str) -> None:
    """One row of each kind for ``MEMBER`` in the workspace ``owner`` owns things in, named after ``tag``."""
    now = dt.datetime.now(dt.timezone.utc)
    team_id = owner[len("__team__"):] if owner.startswith("__team__") else None
    agent_id = str(AgentsRepository(conn).create(owner, f"{tag} bot", "published", key=f"k-{uuid.uuid4()}")["id"])
    conversations = ConversationsRepository(conn)
    chat = conversations.create(MEMBER, f"{tag} chat", agent_id=agent_id, team_id=team_id)
    message = conversations.append_message(str(chat["id"]), {"prompt": f"{tag} asked", "response": "ok"})
    UserLogsRepository(conn).insert(user_id=MEMBER, endpoint="stream", data={
        "question": f"{tag} answered", "conversation_id": str(chat["id"]), "message_id": str(message["id"]),
        "agent_id": agent_id, "action": "stream_answer", "level": "info",
    })
    conversations.reserve_message(str(chat["id"]), prompt=f"{tag} running", placeholder_response="",
                                  status="streaming")
    StackLogsRepository(conn).insert(activity_id=str(uuid.uuid4()), endpoint="stream", level="error",
                                     user_id=MEMBER, agent_id=agent_id, query=f"{tag} failed", stacks=[])
    schedule = SchedulesRepository(conn).create(user_id=MEMBER, agent_id=agent_id, trigger_type="recurring",
                                                instruction="hi", cron="0 * * * *", name=f"{tag} schedule")
    ScheduleRunsRepository(conn).record_skipped(str(schedule["id"]), MEMBER, agent_id, now,
                                                error_type="payer_left", error="payer_left")
    workflow = WorkflowsRepository(conn).create(owner, f"{tag} workflow")
    WorkflowRunsRepository(conn).create(str(workflow["id"]), MEMBER, "completed", inputs={"query": f"{tag} flow"})
    RequestTracesRepository(conn).insert({
        "id": str(uuid.uuid4()), "user_id": MEMBER, "agent_id": agent_id, "source": "search",
        "summary": {"query": f"{tag} search"}, "started_at": now.isoformat(),
    })


def test_an_ex_member_loses_the_teams_rows_and_keeps_their_own(pg_conn):
    team = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "lx-alice")
    tid = str(team["id"])
    TeamMembersRepository(pg_conn).add_member(tid, "lx-alice", role="team_admin")
    TeamMembersRepository(pg_conn).add_member(tid, MEMBER, role="team_editor")
    # Being in another team must not keep the first team's rows.
    other = TeamsRepository(pg_conn).create("Other", f"oth-{uuid.uuid4().hex[:6]}", "lx-zoe")
    TeamMembersRepository(pg_conn).add_member(str(other["id"]), MEMBER, role="team_viewer")
    _workspace_rows(pg_conn, principal_id(tid), "Team")
    _workspace_rows(pg_conn, MEMBER, "Mine")

    member = _logs(pg_conn)
    kinds = {log["event_type"] for log in member}
    assert {"chat", "system", "schedule", "workflow", "search"} <= kinds
    assert len(member) == 2 * 6

    TeamMembersRepository(pg_conn).remove_member(tid, MEMBER)

    left = _logs(pg_conn)
    assert len(left) == 6
    assert not any("Team" in str(log) for log in left), [log for log in left if "Team" in str(log)]

    TeamMembersRepository(pg_conn).add_member(tid, MEMBER, role="team_viewer")
    assert len(_logs(pg_conn)) == 2 * 6
