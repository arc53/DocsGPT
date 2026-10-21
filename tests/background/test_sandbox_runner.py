"""The sandbox runner's poll chain, against a real database and a fake sandbox backend."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from docsgpt.agents.tools.code_executor import PreparedRun
from docsgpt.background import jobs, sandbox_runner
from docsgpt.background.context import BackgroundContext
from docsgpt.sandbox.base import DetachedState, ExecResult
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository


class _Backend:
    def __init__(self, states):
        self.states = list(states)
        self.adopted = []
        self.released = []
        self.cancelled = []
        self.refreshed = 0
        self.closed = []

    def adopt(self, session_id, run):
        self.adopted.append(session_id)
        return {}

    def poll_detached(self, session_id, run, with_output=False):
        state = self.states.pop(0)
        if isinstance(state, Exception):
            raise state
        return state

    def refresh_activity(self, session_id):
        self.refreshed += 1

    def cancel_detached(self, session_id, run):
        self.cancelled.append(run)

    def release_adopted(self, session_id, run):
        self.released.append(session_id)

    def list_files(self, session_id):
        return []

    def close(self, session_id):
        self.closed.append(session_id)


@pytest.fixture()
def polls(monkeypatch):
    queued = []
    monkeypatch.setattr(sandbox_runner, "enqueue_poll", lambda job_id, countdown: queued.append((job_id, countdown)))
    return queued


@pytest.fixture()
def delivered(monkeypatch):
    out = []
    monkeypatch.setattr(jobs, "_deliver", out.append)
    return out


def _sandbox_job(conversation_id, message_id, *, keep_alive=True):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = True
    row, _ = jobs.create_job(
        context, tool_name="code_executor", action_name="run_code", journal_key="k", arguments={"code": "x"}
    )
    finish = PreparedRun(session_id="conv", code="print(1)", timeout=60.0, should_capture=False, keep_alive=keep_alive)
    external = {
        "session_id": "conv",
        "run": {"backend": "daytona", "sandbox_id": "sb", "cmd_id": "c", "process_session": "p"},
        "finish": finish.to_state(),
        "tool": {"config": {"conversation_id": conversation_id, "tool_id": "t1"}, "user_id": "u1"},
    }
    assert sandbox_runner.detach_job(row["id"], external) is True
    return row["id"]


def _get(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


class TestPollJob:
    def test_detach_moves_the_job_and_starts_polling(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        row = _get(bg_db, job_id)
        assert row["runner"] == "sandbox"
        assert row["lease_owner"] is None
        assert polls == [(job_id, sandbox_runner.FIRST_POLL_SECONDS)]

    def test_running_then_finished(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        backend = _Backend(
            [DetachedState(done=False), DetachedState(done=True, result=ExecResult(stdout="1\n"), output="1\n")]
        )
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)

        assert sandbox_runner.poll_job(job_id) == {"state": "running"}
        assert len(polls) == 2
        assert _get(bg_db, job_id)["external"]["polls"] == 1

        summary = sandbox_runner.poll_job(job_id)
        assert summary == {"state": "finished", "status": "completed"}
        row = _get(bg_db, job_id)
        assert row["status"] == "completed"
        payload = json.loads(row["result"]["text"])
        assert payload["status"] == "ok"
        assert payload["stdout_tail"] == "1\n"
        # The environment banner and session state belong to the turn that ran it, not to the wake.
        assert "environment" not in payload and "session" not in payload
        assert backend.refreshed == 2
        assert backend.released == ["conv"]
        assert [r["id"] for r in delivered] == [job_id]

    def test_a_failed_run_fails_the_job(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        failed = ExecResult(status="error", stdout="Traceback...\nValueError: x\n", error_name="ExecutionError",
                            error_value="Traceback...\nValueError: x\n", exit_code=1)
        backend = _Backend([DetachedState(done=True, result=failed)])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        assert sandbox_runner.poll_job(job_id)["status"] == "failed"
        row = _get(bg_db, job_id)
        assert row["status"] == "failed"
        assert json.loads(row["result"]["text"])["error"].startswith("ValueError")

    def test_a_timed_out_run_is_reported_as_a_background_run(self, bg_db, conversation, polls, delivered, monkeypatch):
        """The poller finishes a run that was handed off: its timeout must not invite a re-run."""
        job_id = _sandbox_job(*conversation)
        timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60s")
        backend = _Backend([DetachedState(done=True, result=timed_out)])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        sandbox_runner.poll_job(job_id)
        payload = json.loads(_get(bg_db, job_id)["result"]["text"])
        assert "only if the user asks" in payload["error"]
        assert "run it again with background=true" not in payload["error"]

    def test_persist_false_closes_the_session_after_the_run(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation, keep_alive=False)
        backend = _Backend([DetachedState(done=True, result=ExecResult(stdout=""))])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        sandbox_runner.poll_job(job_id)
        assert backend.closed == ["conv"]

    def test_cancel_stops_the_process(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        backend = _Backend([])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        with bg_db.begin() as conn:
            BackgroundJobsRepository(conn).request_cancel(job_id, "u1")
        assert sandbox_runner.poll_job(job_id) == {"state": "cancelled"}
        assert _get(bg_db, job_id)["status"] == "cancelled"
        assert len(backend.cancelled) == 1

    def test_failed_polls_retry_then_fail(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        monkeypatch.setattr(sandbox_runner, "MAX_POLL_FAILURES", 2)
        backend = _Backend([IOError("down"), IOError("down")])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        assert sandbox_runner.poll_job(job_id) == {"state": "retry"}
        assert sandbox_runner.poll_job(job_id) == {"state": "failed"}
        row = _get(bg_db, job_id)
        assert row["status"] == "failed"
        assert "lost contact" in row["error"]["message"]

    def test_a_finished_job_is_left_alone(self, bg_db, conversation, polls, delivered, monkeypatch):
        job_id = _sandbox_job(*conversation)
        with bg_db.begin() as conn:
            conn.execute(
                text("UPDATE background_jobs SET status = 'lost' WHERE id = CAST(:id AS uuid)"), {"id": job_id}
            )
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: pytest.fail("no backend needed"))
        assert sandbox_runner.poll_job(job_id) == {"state": "gone"}


def test_next_delay_grows_to_the_cap():
    delays = [sandbox_runner.next_delay(n) for n in range(10)]
    assert delays[0] == sandbox_runner.FIRST_POLL_SECONDS
    assert delays == sorted(delays)
    assert delays[-1] == sandbox_runner.MAX_POLL_SECONDS


def test_a_watched_run_applies_its_watch_each_poll(bg_db, conversation, polls, delivered, monkeypatch):
    job_id = _sandbox_job(*conversation)
    with bg_db.begin() as conn:
        conn.execute(
            text("UPDATE background_jobs SET watch = CAST(:w AS jsonb) WHERE id = CAST(:id AS uuid)"),
            {"w": json.dumps({"patterns": ["Error"]}), "id": job_id},
        )
    seen = []
    monkeypatch.setattr(
        "docsgpt.background.watch.observe_output", lambda row, output, size: seen.append((row["id"], output, size))
    )
    backend = _Backend([DetachedState(done=False, output="Error: x\n", output_size=9)])
    monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
    assert sandbox_runner.poll_job(job_id) == {"state": "running"}
    assert seen == [(job_id, "Error: x\n", 9)]
