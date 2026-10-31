"""A workflow agent gets a way to run outside its builder only with a finished graph.

A draft's inline graph save checks the shape only, so its stored graph may be
unfinished. A webhook URL, a schedule, the scheduler tool and the public link
each let something run the agent's current graph without its builder, so they
refuse a workflow agent whose stored graph fails the full validation. Once
one of them exists (a public link included), later graph saves are checked in
full. Real repositories on ``pg_conn``.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.schedules import SchedulesRepository

from tests.api.user.agents.test_workflow_inline_graph import (
    _create,
    _graph,
    _invalid_graph,
    _json,
    _stored_graph,
    _update,
)
from tests.api.user.test_resource_sponsors import OWNER, _patch_db, _row, _share_agent, _status

_EXTRA_DB_MODULES = (
    "docsgpt.api.user.agents.webhooks",
    "docsgpt.api.user.agents.sharing",
    "docsgpt.api.user.schedules.routes",
    "docsgpt.agents.tools.scheduler",
)


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _db(conn):
    @contextmanager
    def _yield():
        yield conn

    with ExitStack() as stack:
        stack.enter_context(_patch_db(conn))
        for mod_name in _EXTRA_DB_MODULES:
            for attr in ("db_session", "db_readonly"):
                stack.enter_context(patch(f"{mod_name}.{attr}", _yield))
        yield


def _call(app, conn, resource_cls, method, path, *, json=None, args=(), user=OWNER):
    kwargs = {"method": method.upper()}
    if json is not None:
        kwargs["json"] = json
    with _db(conn), app.test_request_context(path, **kwargs):
        from flask import request

        request.decoded_token = {"sub": user}
        return getattr(resource_cls(), method)(*args)


def _draft(app, conn, graph):
    resp = _create(app, conn, {"name": "Flow", "agent_type": "workflow", "status": "draft", "workflow_graph": graph})
    assert _status(resp) == 201, _json(resp)
    return _json(resp)["id"], _json(resp)["workflow_id"]


def _webhook(app, conn, agent_id):
    from docsgpt.api.user.agents.webhooks import AgentWebhook

    return _call(app, conn, AgentWebhook, "get", f"/api/agent_webhook?id={agent_id}")


def _share(app, conn, agent_id, shared=True):
    from docsgpt.api.user.agents.sharing import ShareAgent

    return _call(app, conn, ShareAgent, "put", "/api/share_agent", json={"id": agent_id, "shared": shared})


def _schedule(app, conn, agent_id, trigger_type="recurring"):
    from docsgpt.api.user.schedules.routes import AgentSchedules

    body = {"instruction": "Run", "trigger_type": trigger_type}
    if trigger_type == "once":
        body["run_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    else:
        body["cron"] = "0 9 * * *"
    return _call(app, conn, AgentSchedules, "post", f"/api/agents/{agent_id}/schedules", json=body, args=(agent_id,))


def _refused(resp):
    body = _json(resp)
    return _status(resp) == 400 and body["message"] == "Workflow validation failed" and body["errors"]


class TestTriggersNeedAFinishedGraph:
    def test_a_webhook_url_is_refused(self, app, pg_conn):
        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        resp = _webhook(app, pg_conn, agent_id)
        assert _refused(resp), _json(resp)
        assert not _row(pg_conn, agent_id)["incoming_webhook_token"]

    def test_a_webhook_url_minted_before_is_still_shown(self, app, pg_conn):
        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        AgentsRepository(pg_conn).update(agent_id, OWNER, {"incoming_webhook_token": "tok"})
        resp = _webhook(app, pg_conn, agent_id)
        assert _status(resp) == 200, _json(resp)
        assert _json(resp)["webhook_url"].endswith("/tok")

    @pytest.mark.parametrize("trigger_type", ["recurring", "once"])
    def test_a_schedule_is_refused(self, app, pg_conn, trigger_type):
        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        resp = _schedule(app, pg_conn, agent_id, trigger_type)
        assert _refused(resp), _json(resp)
        assert SchedulesRepository(pg_conn).list_for_agent(agent_id, OWNER) == []

    def test_resuming_or_running_a_schedule_is_refused(self, app, pg_conn):
        """A schedule made before this check: resuming it or running it now runs the graph too."""
        from docsgpt.api.user.schedules.routes import ScheduleResource, ScheduleRunNow

        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        created = SchedulesRepository(pg_conn).create(
            OWNER, agent_id, "recurring", "Run", cron="0 9 * * *", status="paused",
        )
        sid = str(created["id"])
        resumed = _call(
            app, pg_conn, ScheduleResource, "patch", f"/api/schedules/{sid}", json={"action": "resume"}, args=(sid,),
        )
        assert _refused(resumed), _json(resumed)
        assert SchedulesRepository(pg_conn).get_internal(sid)["status"] == "paused"
        with patch("docsgpt.api.user.tasks.execute_scheduled_run") as task:
            ran = _call(app, pg_conn, ScheduleRunNow, "post", f"/api/schedules/{sid}/run", args=(sid,))
        assert _refused(ran), _json(ran)
        task.apply_async.assert_not_called()

    def test_the_scheduler_tool_refuses(self, app, pg_conn):
        import docsgpt.api.user.tools.mcp  # noqa: F401  (stable ToolManager import order)
        from docsgpt.agents.tools.scheduler import SchedulerTool

        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        tool = SchedulerTool(tool_config={"agent_id": agent_id}, user_id=OWNER)
        with _db(pg_conn):
            out = tool.execute_action("schedule_task", instruction="Run", delay="1h")
        assert out.startswith("Error:") and "workflow" in out.lower()
        assert SchedulesRepository(pg_conn).list_for_agent(agent_id, OWNER) == []

    def test_a_public_link_is_refused(self, app, pg_conn):
        agent_id, _ = _draft(app, pg_conn, _invalid_graph())
        resp = _share(app, pg_conn, agent_id)
        assert _refused(resp), _json(resp)
        assert not _row(pg_conn, agent_id)["shared"]
        # Turning a link off is never refused.
        assert _status(_share(app, pg_conn, agent_id, shared=False)) == 200

    def test_a_finished_draft_gets_every_trigger(self, app, pg_conn):
        agent_id, _ = _draft(app, pg_conn, _graph())
        assert _status(_webhook(app, pg_conn, agent_id)) == 200
        assert _status(_schedule(app, pg_conn, agent_id)) == 201
        assert _status(_share(app, pg_conn, agent_id)) == 200

    def test_a_workflow_agent_without_a_workflow_gets_no_trigger(self, app, pg_conn):
        resp = _create(app, pg_conn, {"name": "Empty", "agent_type": "workflow", "status": "draft"})
        agent_id = _json(resp)["id"]
        assert _refused(_webhook(app, pg_conn, agent_id))
        assert _refused(_share(app, pg_conn, agent_id))

    def test_a_classic_draft_is_not_checked(self, app, pg_conn):
        resp = _create(app, pg_conn, {"name": "A", "description": "d", "status": "draft"})
        agent_id = _json(resp)["id"]
        assert _status(_webhook(app, pg_conn, agent_id)) == 200
        assert _status(_share(app, pg_conn, agent_id)) == 200


class TestSharedDrafts:
    def test_a_draft_with_a_public_link_needs_a_finished_graph(self, app, pg_conn):
        """Anyone with the link runs the draft through chat, so its graph saves are checked in full."""
        agent_id, wid = _draft(app, pg_conn, _graph())
        assert _status(_share(app, pg_conn, agent_id)) == 200
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _invalid_graph()})
        assert _refused(resp), _json(resp)
        assert _stored_graph(pg_conn, wid)[0]["current_graph_version"] == 1

    def test_a_draft_shared_with_a_team_still_saves_an_unfinished_graph(self, app, pg_conn):
        """Teammates build the draft together; a team grant is not a public run path."""
        agent_id, _ = _draft(app, pg_conn, _graph())
        _share_agent(pg_conn, agent_id)
        resp = _update(app, pg_conn, agent_id, {"workflow_graph": _invalid_graph()})
        assert _status(resp) == 200, _json(resp)
