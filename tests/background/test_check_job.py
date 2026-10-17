"""check_job and the job routes, against a real database."""

from __future__ import annotations

import threading

import pytest
from flask import Flask

from docsgpt.agents.tools.check_job import CheckJobTool, add_check_job_tool
from docsgpt.background import jobs, sandbox_runner
from docsgpt.background.context import BackgroundContext
from docsgpt.background.results import LOST_NOTE
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversation_wakes import ConversationWakesRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(jobs, "_deliver", lambda row: None)
    monkeypatch.setattr("docsgpt.background.service.publish_job_updated", lambda row: None)


def _job(conversation_id, message_id, key="k", user_id="u1", **kwargs):
    context = BackgroundContext(user_id=user_id, conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = kwargs.pop("auto_resume", True)
    row, _ = jobs.create_job(
        context, tool_name="read_webpage", action_name="read", journal_key=key, arguments={}, **kwargs
    )
    return row


def _tool(conversation_id, user_id="u1"):
    return CheckJobTool({"conversation_id": conversation_id, "tool_id": "check_job"}, user_id)


def _get(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


class TestCheckJob:
    def test_needs_a_conversation(self):
        assert CheckJobTool({}, "u1").execute_action("check_job")["status"] == "error"

    def test_lists_only_this_conversations_jobs(self, bg_db, conversation):
        conversation_id, message_id = conversation
        mine = _job(conversation_id, message_id, key="a")
        with bg_db.begin() as conn:
            other = str(ConversationsRepository(conn).create("u1", "other")["id"])
        _job(other, None, key="b")
        listed = _tool(conversation_id).execute_action("check_job")["jobs"]
        assert [j["job_id"] for j in listed] == [mine["id"]]
        assert listed[0]["status"] == "working"
        assert listed[0]["result_delivered"] is False

    def test_another_conversations_job_is_not_found(self, bg_db, conversation):
        conversation_id, message_id = conversation
        with bg_db.begin() as conn:
            other = str(ConversationsRepository(conn).create("u1", "other")["id"])
        job = _job(other, None)
        out = _tool(conversation_id).execute_action("check_job", job_id=job["id"])
        assert out["status"] == "error"

    def test_running_job_and_the_stop_polling_note(self, bg_db, conversation):
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        tool = _tool(conversation_id)
        first = tool.execute_action("check_job", job_id=job["id"])
        assert first["status"] == "running"
        # With auto-resume on, a retry hint reads as an invitation to poll.
        assert "retry_after_s" not in first
        assert "not an error" in first["note"]
        for _ in range(9):
            last = tool.execute_action("check_job", job_id=job["id"])
        assert last["note"].startswith("Stop polling")

    def test_finished_job_is_claimed_once(self, bg_db, conversation):
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        with bg_db.begin() as conn:
            ConversationWakesRepository(conn).enqueue(
                user_id="u1", conversation_id=conversation_id, source="job", ref_id=job["id"],
                dedupe_key=f"job:{job['id']}:final",
            )
        jobs.finalize(job["id"], status="completed", result={"text": "the page", "status": "completed"})
        tool = _tool(conversation_id)
        out = tool.execute_action("check_job", job_id=job["id"])
        assert out["status"] == "completed"
        assert out["result"] == "the page"
        assert "note" not in out
        assert _get(bg_db, job["id"])["delivery_state"] == "claimed_by_poll"
        with bg_db.connect() as conn:
            wake = ConversationWakesRepository(conn).claim_batch(conversation_id)
        assert wake == []
        again = tool.execute_action("check_job", job_id=job["id"])
        assert "already delivered" in again["note"]

    def test_waits_for_a_job_that_finishes(self, bg_db, conversation):
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        timer = threading.Timer(
            0.3, lambda: jobs.finalize(job["id"], status="completed", result={"text": "ok", "status": "completed"})
        )
        timer.start()
        out = _tool(conversation_id).execute_action("check_job", job_id=job["id"], wait_seconds=5)
        assert out["status"] == "completed"

    def test_a_poll_only_job_still_says_when_to_look_again(self, bg_db, conversation):
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id, auto_resume=False)
        assert _tool(conversation_id).execute_action("check_job", job_id=job["id"])["retry_after_s"] == 30

    def test_a_job_started_in_this_turn_is_never_waited_on(self, bg_db, conversation):
        """Waiting right after a hand-off only holds the turn: the result resumes the conversation anyway."""
        import time

        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        tool = CheckJobTool({"conversation_id": conversation_id, "message_id": message_id}, "u1")
        started = time.monotonic()
        out = tool.execute_action("check_job", job_id=job["id"], wait_seconds=30)
        assert time.monotonic() - started < 5
        assert out["status"] == "running"
        assert "started in this turn" in out["note"] and "end your turn" in out["note"]

    def test_the_wait_description_discourages_waiting(self):
        params = CheckJobTool().get_actions_metadata()[0]["parameters"]["properties"]
        assert "never wait on a job you just started" in params["wait_seconds"]["description"]

    def test_wait_is_clamped(self):
        assert CheckJobTool._wait_seconds(999) == 30
        assert CheckJobTool._wait_seconds("x") == 0
        assert CheckJobTool._wait_seconds(-3) == 0

    def test_lost_job_reads_as_failed(self, bg_db, conversation):
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        jobs.finalize(job["id"], status="lost", error={"type": "Lost", "message": LOST_NOTE})
        out = _tool(conversation_id).execute_action("check_job", job_id=job["id"])
        assert out["status"] == "failed"
        assert out["note"] == LOST_NOTE

    def test_cancel(self, bg_db, conversation, monkeypatch):
        polls = []
        monkeypatch.setattr(sandbox_runner, "enqueue_poll", lambda job_id, countdown: polls.append(job_id))
        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id, runner="sandbox")
        out = _tool(conversation_id).execute_action("check_job", job_id=job["id"], action="cancel")
        assert out["cancel_requested"] is True
        assert _get(bg_db, job["id"])["cancel_requested_at"] is not None
        assert polls == [job["id"]]
        jobs.finalize(job["id"], status="cancelled")
        done = _tool(conversation_id).execute_action("check_job", job_id=job["id"], action="cancel")
        assert "already finished" in done["note"]

    def test_cancel_needs_a_job_id(self, bg_db, conversation):
        conversation_id, _ = conversation
        assert _tool(conversation_id).execute_action("check_job", action="cancel")["status"] == "error"


class TestInjection:
    def test_added_once_and_never_over_a_client_tool(self):
        tools = {}
        assert add_check_job_tool(tools) is True
        assert tools["check_job"]["actions"][0]["name"] == "check_job"
        assert add_check_job_tool(tools) is True
        clashing = {"ct0": {"name": "x", "client_side": True, "actions": [{"name": "check_job"}]}}
        assert add_check_job_tool(clashing) is False
        assert "check_job" not in clashing

    def test_a_config_row_with_its_action_off_is_replaced(self):
        """An older default-tool row (check_job toggled off) can't leave hand-offs without the tool."""
        tools = {
            "6b1d-check": {"id": "6b1d-check", "name": "check_job",
                           "actions": [{"name": "check_job", "active": False}]},
        }
        assert add_check_job_tool(tools) is True
        assert list(tools) == ["check_job"]
        assert all(a["active"] for a in tools["check_job"]["actions"])

    def test_a_turn_with_a_tool_that_can_hand_off_gets_it(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent(**agent_base_params)
        agent._llm_supports_tools = lambda: True
        slow = {"name": "read_webpage", "actions": [{"name": "read_webpage", "active": True, "parameters": {}}]}
        tools = {"t1": dict(slow)}
        agent._prepare_tools(tools)
        assert "check_job" not in tools
        agent.tool_executor.background = BackgroundContext(user_id="u", conversation_id="c")
        agent._prepare_tools(tools)
        assert "check_job" in tools
        assert any(t["function"]["name"] == "check_job" for t in agent.tools)

    def test_no_tool_that_can_hand_off_means_no_check_job(
        self, agent_base_params, mock_llm_creator, mock_llm_handler_creator
    ):
        from docsgpt.agents.classic_agent import ClassicAgent

        agent = ClassicAgent(**agent_base_params)
        agent._llm_supports_tools = lambda: True
        agent.tool_executor.background = BackgroundContext(user_id="u", conversation_id="c")
        only_inline = {
            "m": {"name": "monitor", "actions": [{"name": "monitor_create", "active": True, "parameters": {}}]},
            "c": {"name": "x", "client_side": True, "actions": [{"name": "x", "active": True, "parameters": {}}]},
        }
        agent._prepare_tools(only_inline)
        assert "check_job" not in only_inline
        agent._prepare_tools({})
        assert not any(t["function"]["name"] == "check_job" for t in agent.tools)


class TestRoutes:
    @pytest.fixture
    def app(self):
        return Flask(__name__)

    def _call(self, app, resource, method, path, user="u1", **kwargs):
        with app.test_request_context(path, method=method.upper()):
            from flask import request

            request.decoded_token = {"sub": user} if user else None
            return getattr(resource(), method)(**kwargs)

    def test_list_get_cancel(self, app, bg_db, conversation, monkeypatch):
        from docsgpt.api.user.background_jobs.routes import BackgroundJob, BackgroundJobs, CancelBackgroundJob

        conversation_id, message_id = conversation
        job = _job(conversation_id, message_id)
        assert self._call(app, BackgroundJobs, "get", "/api/background_jobs", user=None).status_code == 401
        assert self._call(app, BackgroundJobs, "get", "/api/background_jobs").status_code == 400
        listed = self._call(app, BackgroundJobs, "get", f"/api/background_jobs?conversation_id={conversation_id}")
        assert [j["job_id"] for j in listed.get_json()["jobs"]] == [job["id"]]

        one = self._call(app, BackgroundJob, "get", f"/api/background_jobs/{job['id']}", job_id=job["id"])
        assert one.get_json()["status"] == "working"
        assert "result" not in one.get_json()
        assert self._call(
            app, BackgroundJob, "get", "/x", user="someone-else", job_id=job["id"]
        ).status_code == 404

        cancelled = self._call(app, CancelBackgroundJob, "post", "/x", job_id=job["id"])
        assert cancelled.get_json()["cancel_requested"] is True
        jobs.finalize(job["id"], status="completed", result={"text": "x" * 5000, "status": "completed"})
        done = self._call(app, BackgroundJob, "get", "/x", job_id=job["id"]).get_json()
        assert done["status"] == "cancelled"
        assert len(done["result"]) <= 2000


class TestRouteFailures:
    def test_database_errors_answer_500(self, monkeypatch):
        from flask import Flask, request

        from docsgpt.api.user.background_jobs import routes

        app = Flask(__name__)
        monkeypatch.setattr(routes, "db_readonly", lambda: (_ for _ in ()).throw(RuntimeError("db")))
        monkeypatch.setattr(routes, "cancel_job", lambda *a: (_ for _ in ()).throw(RuntimeError("db")))
        with app.test_request_context("/api/background_jobs?conversation_id=00000000-0000-0000-0000-000000000000"):
            request.decoded_token = {"sub": "u1"}
            assert routes.BackgroundJobs().get().status_code == 500
            assert routes.BackgroundJob().get("j").status_code == 500
            assert routes.CancelBackgroundJob().post("j").status_code == 500
        with app.test_request_context("/x"):
            request.decoded_token = None
            assert routes.BackgroundJob().get("j").status_code == 401
            assert routes.CancelBackgroundJob().post("j").status_code == 401

    def test_cancel_unknown_job_is_404(self, bg_db):
        from flask import Flask, request

        from docsgpt.api.user.background_jobs import routes

        app = Flask(__name__)
        with app.test_request_context("/x"):
            request.decoded_token = {"sub": "u1"}
            assert routes.CancelBackgroundJob().post("00000000-0000-0000-0000-000000000000").status_code == 404
