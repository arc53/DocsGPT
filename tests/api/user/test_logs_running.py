"""Runs that are still going, in the Logs timeline (``/api/get_user_logs``).

A run sits at its start time: listed while it runs (``running: true``), then
replaced by its finished row. Chats, scheduled runs and workflow runs come
from their own tables; webhook runs from their Redis marker, on page 1.
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.schedule_runs import ScheduleRunsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture
def markers():
    """Webhook run markers ``list_runs`` returns, per owner."""
    by_owner: dict[str, list[dict]] = {}
    with patch(
        "docsgpt.api.user.analytics.routes.list_runs",
        lambda user_id: by_owner.get(user_id, []),
    ):
        yield by_owner


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _post(app, conn, user: str, body: dict | None = None):
    from docsgpt.api.user.analytics.routes import GetUserLogs

    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.analytics.routes.db_readonly", _yield), app.test_request_context(
        "/api/get_user_logs", method="POST", json=body or {}
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        response = GetUserLogs().post()
    assert response.status_code == 200
    return response.json["logs"]


def _agent(conn, owner: str = "owner", **kw) -> str:
    return str(AgentsRepository(conn).create(owner, "Support bot", "published", key=f"k-{uuid.uuid4()}", **kw)["id"])


def _answer(
    conn, user: str, status: str = "streaming", *, agent_id: str | None = None,
    visibility: str = "listed", shared: bool = False, heartbeat_age: int = 5, prompt: str = "Where is my order?",
) -> str:
    repo = ConversationsRepository(conn)
    conv = repo.create(user, "Order status", agent_id=agent_id, visibility=visibility, is_shared_usage=shared)
    row = repo.reserve_message(str(conv["id"]), prompt=prompt, placeholder_response="", status=status)
    conn.execute(
        text(
            "UPDATE conversation_messages SET message_metadata = jsonb_build_object("
            "'last_heartbeat_at', to_jsonb(now() - make_interval(secs => :age))) "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"age": heartbeat_age, "id": str(row["id"])},
    )
    return str(row["id"])


def _running(logs: list[dict]) -> list[dict]:
    return [log for log in logs if log.get("running")]


class TestRunningChats:
    def test_an_api_answer_shows_in_its_agents_logs(self, app, pg_conn, markers):
        agent = _agent(pg_conn)
        message = _answer(pg_conn, "owner", agent_id=agent, visibility="hidden")
        logs = _post(app, pg_conn, "owner", {"api_key_id": agent})
        rows = _running(logs)
        assert len(rows) == 1
        row = rows[0]
        assert row["event_type"] == "chat"
        assert row["origin"] == "api"
        assert row["message_id"] == message
        assert row["question"] == "Where is my order?"
        assert row["status"] == "streaming"
        assert row["started_at"] == row["timestamp"]

    def test_a_shared_callers_answer_shows_to_the_owner(self, app, pg_conn, markers):
        agent = _agent(pg_conn)
        _answer(pg_conn, "caller", agent_id=agent, visibility="hidden", shared=True)
        rows = _running(_post(app, pg_conn, "owner", {"api_key_id": agent}))
        assert [row["origin"] for row in rows] == ["shared"]

    def test_user_wide_logs_list_the_users_own_answers(self, app, pg_conn, markers):
        _answer(pg_conn, "owner")
        _answer(pg_conn, "someone-else")
        rows = _running(_post(app, pg_conn, "owner"))
        assert [row["origin"] for row in rows] == ["chat"]

    def test_finished_and_stale_answers_are_not_running(self, app, pg_conn, markers):
        _answer(pg_conn, "owner", "complete")
        _answer(pg_conn, "owner", heartbeat_age=600)
        assert _running(_post(app, pg_conn, "owner")) == []

    def test_filters_apply(self, app, pg_conn, markers):
        _answer(pg_conn, "owner", prompt="Refund for order 4411")
        assert len(_running(_post(app, pg_conn, "owner", {"event_type": "chat"}))) == 1
        assert _running(_post(app, pg_conn, "owner", {"event_type": "schedule"})) == []
        assert _running(_post(app, pg_conn, "owner", {"level": "error"})) == []
        assert len(_running(_post(app, pg_conn, "owner", {"search": "refund"}))) == 1
        assert _running(_post(app, pg_conn, "owner", {"search": "invoice"})) == []


class TestRunningScheduledRuns:
    def _run(self, conn, user: str, status: str, started: dt.datetime, finished: dt.datetime | None = None,
             name: str = "Daily digest") -> str:
        schedule = SchedulesRepository(conn).create(user, None, "once", "digest", run_at=started, name=name)
        run = ScheduleRunsRepository(conn).record_pending(str(schedule["id"]), user, None, started)
        ScheduleRunsRepository(conn).update(
            str(run["id"]), {"status": status, "started_at": started, "finished_at": finished}
        )
        return str(run["id"])

    def test_a_running_run_is_listed(self, app, pg_conn, markers):
        self._run(pg_conn, "owner", "running", _now())
        rows = _running(_post(app, pg_conn, "owner", {"event_type": "schedule"}))
        assert len(rows) == 1
        assert rows[0]["status"] == "running"
        assert rows[0]["question"] == "Daily digest"

    def test_runs_sit_at_their_start_time(self, app, pg_conn, markers):
        start = _now() - dt.timedelta(hours=1)
        self._run(pg_conn, "owner", "success", start, start + dt.timedelta(minutes=30), name="long")
        self._run(pg_conn, "owner", "success", start + dt.timedelta(minutes=10),
                  start + dt.timedelta(minutes=15), name="short")
        logs = _post(app, pg_conn, "owner", {"event_type": "schedule"})
        # Ordered by start, so a run doesn't move when it finishes.
        assert [log["question"] for log in logs] == ["short", "long"]


class TestRunningWorkflowRuns:
    def test_a_running_run_carries_its_step(self, app, pg_conn, markers):
        wf = WorkflowsRepository(pg_conn).create("owner", "Renewal flow")
        run = WorkflowRunsRepository(pg_conn).create(str(wf["id"]), "owner", "running", started_at=_now())
        progress = {"done": 1, "total": 3, "current": {"node_id": "b", "title": "Draft reply", "type": "agent"}}
        WorkflowRunsRepository(pg_conn).set_progress(str(run["id"]), "owner", progress)
        rows = _running(_post(app, pg_conn, "owner", {"event_type": "workflow"}))
        assert len(rows) == 1
        assert rows[0]["workflow_progress"] == progress
        assert rows[0]["started_at"] == rows[0]["timestamp"]


class TestRunningWebhooks:
    def _marker(self, agent_id: str, *, age: int = 30, summary: str | None = "New ticket #88") -> dict:
        return {
            "kind": "webhook",
            "id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "agent_name": "Support bot",
            "summary": summary,
            "started_at": _now().timestamp() - age,
        }

    def test_a_running_webhook_run_is_on_page_one(self, app, pg_conn, markers):
        agent = _agent(pg_conn)
        markers["owner"] = [self._marker(agent), self._marker(str(uuid.uuid4()))]
        rows = _running(_post(app, pg_conn, "owner", {"api_key_id": agent}))
        assert len(rows) == 1
        assert rows[0]["event_type"] == "webhook"
        assert rows[0]["question"] == "New ticket #88"
        assert rows[0]["agent_id"] == agent
        assert _running(_post(app, pg_conn, "owner", {"api_key_id": agent, "page": 2})) == []

    def test_user_wide_logs_list_every_agents_runs(self, app, pg_conn, markers):
        markers["owner"] = [self._marker(str(uuid.uuid4())), self._marker(str(uuid.uuid4()))]
        assert len(_running(_post(app, pg_conn, "owner"))) == 2

    def test_filters_apply(self, app, pg_conn, markers):
        markers["owner"] = [self._marker(str(uuid.uuid4()))]
        assert _running(_post(app, pg_conn, "owner", {"event_type": "chat"})) == []
        assert _running(_post(app, pg_conn, "owner", {"level": "error"})) == []
        assert _running(_post(app, pg_conn, "owner", {"search": "ticket"})) != []
        assert _running(_post(app, pg_conn, "owner", {"search": "invoice"})) == []

    def test_sits_among_finished_rows_by_start_time(self, app, pg_conn, markers):
        started = _now() - dt.timedelta(minutes=10)
        TestRunningScheduledRuns()._run(pg_conn, "owner", "success", started, started, name="digest")
        markers["owner"] = [
            self._marker(str(uuid.uuid4()), age=60, summary="newer"),
            self._marker(str(uuid.uuid4()), age=1200, summary="older"),
        ]
        logs = _post(app, pg_conn, "owner")
        assert [log["question"] for log in logs] == ["newer", "digest", "older"]
