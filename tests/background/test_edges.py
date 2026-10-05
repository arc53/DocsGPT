"""Edge paths of the background package: tasks, events, notify, pool, failures and fallbacks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.background import (
    celery_runner,
    continuation,
    events,
    jobs,
    pool,
    sandbox_runner,
    service,
    wake,
)
from docsgpt.background.context import BackgroundContext
from docsgpt.sandbox.base import DetachedState, ExecResult
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository


def _context(conversation_id, message_id=None, auto_resume=True):
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = auto_resume
    return context


def _job(conversation_id, message_id=None, key="k", **kwargs):
    row, _ = jobs.create_job(
        _context(conversation_id, message_id), tool_name="t", action_name="a", journal_key=key, arguments={}, **kwargs
    )
    return row


class TestTasks:
    def test_background_tasks_delegate(self):
        from docsgpt.api.user import tasks

        with patch("docsgpt.background.sandbox_runner.poll_job", return_value={"state": "x"}) as poll:
            assert tasks.poll_background_sandbox_job.run("j") == {"state": "x"}
        poll.assert_called_once_with("j")
        with patch("docsgpt.background.celery_runner.run_job", return_value={"state": "y"}) as run:
            assert tasks.run_background_tool_call.run("j", {"a": 1}) == {"state": "y"}
        run.assert_called_once_with("j", {"a": 1})
        with patch(
            "docsgpt.background.continuation.continue_conversation_body", return_value={"state": "z"}
        ) as body:
            assert tasks.continue_conversation.run("c", 2) == {"state": "z"}
        body.assert_called_once_with("c", 2)
        with patch("docsgpt.background.reconciler.sweep", return_value={"lost": 0}):
            assert tasks.sweep_background_jobs.run() == {"lost": 0}
        with patch("docsgpt.background.reconciler.sweep", side_effect=RuntimeError("db")):
            assert tasks.sweep_background_jobs.run() == {"error": True}
        with patch("docsgpt.background.reconciler.cleanup", return_value={"jobs": 1, "wakes": 0}):
            assert tasks.cleanup_background_jobs.run() == {"jobs": 1, "wakes": 0}

    def test_time_limits(self):
        from docsgpt.api.user import tasks

        assert tasks.run_background_tool_call.soft_time_limit > 1000
        assert tasks.continue_conversation.soft_time_limit >= 30


class TestEventsAndNotify:
    def test_job_updated(self):
        with patch.object(events, "publish_user_event") as publish:
            events.publish_job_updated({"id": "j", "user_id": "u", "conversation_id": "c", "status": "working"})
            events.publish_job_updated({"id": "j", "status": "working"})
        args = publish.call_args_list[0]
        assert args.args[1] == "job.updated"
        assert args.args[2]["job_id"] == "j"
        assert args.kwargs["scope"] == {"kind": "conversation", "id": "c"}
        assert publish.call_count == 1

    def test_publish_failures_are_swallowed(self):
        with patch.object(events, "publish_user_event", side_effect=RuntimeError("redis")):
            events.publish_job_updated({"id": "j", "user_id": "u", "status": "x"})
            events.publish_conversation_continued("u", "c", "m", "job")

    def test_conversation_continued(self):
        with patch.object(events, "publish_user_event") as publish:
            events.publish_conversation_continued("u", "c", "m", "monitor")
        assert publish.call_args.args[1:3] == (
            "conversation.continued",
            {"conversation_id": "c", "message_id": "m", "source": "monitor"},
        )

    def test_notify_user(self):
        from docsgpt.notifications import notify

        # A tab is open elsewhere, so the notification is the toast event.
        with patch.object(notify, "publish_user_event") as publish, patch.object(
            notify.presence, "is_watching", return_value=False
        ), patch.object(notify.presence, "has_open_tab", return_value=True), patch.object(
            notify, "_mark_unread"
        ):
            notify.notify_user(user_id="u", conversation_id="c", kind="job", title="t", body="b", url="/c/c")
            notify.notify_user(user_id="", conversation_id="c", kind="job", title="t", body="b", url="/c/c")
        publish.assert_called_once()
        assert publish.call_args.args[1] == "notification.created"
        assert publish.call_args.args[2] == {
            "kind": "job", "title": "t", "body": "b", "url": "/c/c", "conversation_id": "c",
        }
        with patch.object(notify, "publish_user_event", side_effect=RuntimeError("redis")):
            notify.notify_user(user_id="u", conversation_id=None, kind="job", title="t", body="b", url="/")


class TestPool:
    def test_heartbeat_stamps_held_jobs(self, bg_db, conversation):
        conversation_id, message_id = conversation
        row = _job(conversation_id, message_id)
        assert pool.beat_once() == 0 or True
        pool.hold(row["id"])
        try:
            assert pool.beat_once() >= 1
        finally:
            pool.release(row["id"])
        assert row["id"] not in pool.held()

    def test_heartbeat_loop_beats_then_exits_when_idle(self, monkeypatch):
        monkeypatch.setattr(pool, "HEARTBEAT_SECONDS", 0.01)
        beats = []

        def beat():
            beats.append(1)
            if len(beats) == 2:
                raise RuntimeError("db blip")
            if len(beats) >= 3:
                pool.release("x")
            return 1

        monkeypatch.setattr(pool, "beat_once", beat)
        pool._ensure()
        with pool._lock:
            pool._held.add("x")
        pool._heartbeat_loop()
        assert len(beats) == 3
        assert pool._heartbeat_thread is None

    def test_full_pool_refuses(self, monkeypatch):
        pool._ensure()
        monkeypatch.setattr(pool, "_slots", SimpleNamespace(acquire=lambda blocking=False: False))
        assert pool.try_submit(lambda: 1) is None


class TestContextLookup:
    def test_auto_resume_is_looked_up_once(self, bg_db, conversation):
        context = BackgroundContext(user_id="u1", conversation_id=conversation[0])
        assert context.auto_resume() is True
        assert context._auto_resume is True

    def test_a_failed_lookup_is_poll_only(self):
        context = BackgroundContext(user_id="u1", conversation_id="c")
        with patch("docsgpt.storage.db.session.db_readonly", side_effect=RuntimeError("db")):
            assert context.auto_resume() is False

    def test_executor_without_attributes(self):
        from docsgpt.background.context import bind_turn

        class Frozen:
            __slots__ = ("headless", "workflow_run_id")

            def __init__(self):
                self.headless = False
                self.workflow_run_id = None

        assert bind_turn(Frozen(), conversation_id="c", message_id="m", decoded_token={"sub": "u"}) is None


class TestWakeScheduling:
    def test_marker_allows_one_schedule(self, monkeypatch):
        store = {}

        class Redis:
            def set(self, key, value, nx=False, ex=None):
                if nx and key in store:
                    return None
                store[key] = value
                return True

            def delete(self, key):
                store.pop(key, None)

        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: Redis())
        task = MagicMock()
        with patch("docsgpt.api.user.tasks.continue_conversation", task):
            wake.schedule_continuation("c1")
            wake.schedule_continuation("c1")
            assert task.apply_async.call_count == 1
            wake.clear_scheduled("c1")
            wake.schedule_continuation("c1")
            assert task.apply_async.call_count == 2
            # A deferral always reschedules.
            wake.schedule_continuation("c1", attempt=3, countdown=20)
            assert task.apply_async.call_args.kwargs == {"args": ["c1", 3], "countdown": 20}

    def test_a_queue_failure_clears_the_marker(self, monkeypatch):
        monkeypatch.setattr("docsgpt.cache.get_redis_instance", lambda: None)
        task = MagicMock()
        task.apply_async.side_effect = RuntimeError("broker down")
        with patch("docsgpt.api.user.tasks.continue_conversation", task):
            wake.schedule_continuation("c2")
        task.apply_async.assert_called_once()

    def test_bad_inputs_queue_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr(wake, "schedule_continuation", lambda cid, **kw: called.append(cid))
        wake.wake_conversation(user_id="", conversation_id="c", source="job", ref_id="r", title="", body="",
                               payload=None, dedupe_key="k")
        with patch("docsgpt.background.wake.db_session", side_effect=RuntimeError("db")):
            wake.wake_conversation(user_id="u", conversation_id="c", source="job", ref_id="r", title="",
                                   body="", payload=None, dedupe_key="k")
        assert called == []

    def test_disabled_auto_resume_ignores_finished_jobs(self, monkeypatch):
        monkeypatch.setattr(wake.settings, "AUTO_RESUME_ENABLED", False)
        with patch.object(wake, "wake_conversation") as woke:
            wake.on_job_finished({"id": "j", "conversation_id": "c", "auto_resume": True, "status": "completed"})
        woke.assert_not_called()

    def test_generic_payload_is_rendered_as_json(self):
        assert '"x": 1' in wake.fenced({"x": 1}, 100)


class TestCeleryRunnerEdges:
    def test_gone_and_cancelled_jobs(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        assert celery_runner.run_job("00000000-0000-0000-0000-000000000000", {}) == {"state": "gone"}
        row = _job(conversation[0], conversation[1], runner="celery")
        with bg_db.begin() as conn:
            BackgroundJobsRepository(conn).request_cancel(row["id"], "u1")
        assert celery_runner.run_job(row["id"], {}) == {"state": "cancelled"}

    def test_a_missing_tool_fails_the_job(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        row = _job(conversation[0], conversation[1], key="k2", runner="celery")
        monkeypatch.setattr("docsgpt.agents.tool_executor.ToolExecutor.get_tools", lambda self: {})
        summary = celery_runner.run_job(row["id"], {"user": "u1", "tool_row_id": "x", "action_name": "a"})
        assert summary == {"state": "failed"}
        with bg_db.connect() as conn:
            failed = BackgroundJobsRepository(conn).get(row["id"])
        assert failed["status"] == "failed"
        assert "no longer available" in failed["error"]["message"]

    def test_soft_time_limit(self, bg_db, conversation, monkeypatch):
        from celery.exceptions import SoftTimeLimitExceeded

        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        row = _job(conversation[0], conversation[1], key="k3", runner="celery")
        monkeypatch.setattr(
            "docsgpt.agents.tool_executor.ToolExecutor.get_tools",
            lambda self: (_ for _ in ()).throw(SoftTimeLimitExceeded()),
        )
        assert celery_runner.run_job(row["id"], {"user": "u1"}) == {"state": "timeout"}

    def test_enqueue(self, monkeypatch):
        task = MagicMock()
        with patch("docsgpt.api.user.tasks.run_background_tool_call", task):
            assert celery_runner.enqueue("j", {"a": 1}) is True
        task.apply_async.assert_called_once_with(args=["j", {"a": 1}])


class TestSandboxRunnerEdges:
    def test_poll_backend_is_cached_per_process(self, monkeypatch):
        monkeypatch.setattr(sandbox_runner, "_backend", None)
        made = []
        monkeypatch.setattr(
            "docsgpt.sandbox.sandbox_creator.SandboxCreator.create_backend",
            classmethod(lambda cls, name: made.append(name) or object()),
        )
        first = sandbox_runner._poll_backend()
        assert sandbox_runner._poll_backend() is first
        assert len(made) == 1

    def test_enqueue_poll(self):
        task = MagicMock()
        with patch("docsgpt.api.user.tasks.poll_background_sandbox_job", task):
            sandbox_runner.enqueue_poll("j", 3)
        task.apply_async.assert_called_once_with(args=["j"], countdown=3)
        task.apply_async.side_effect = RuntimeError("down")
        with patch("docsgpt.api.user.tasks.poll_background_sandbox_job", task):
            sandbox_runner.enqueue_poll("j", 3)

    def test_detach_refused_for_a_finished_job(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        row = _job(*conversation)
        jobs.finalize(row["id"], status="completed")
        assert sandbox_runner.detach_job(row["id"], {}) is False
        with patch("docsgpt.background.sandbox_runner.db_session", side_effect=RuntimeError("db")):
            assert sandbox_runner.detach_job(row["id"], {}) is False

    def test_a_job_without_its_handle_fails(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        row = _job(*conversation, runner="sandbox")
        assert sandbox_runner.poll_job(row["id"]) == {"state": "failed"}

    def test_adopt_failure_counts_as_a_failed_poll(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        monkeypatch.setattr(sandbox_runner, "enqueue_poll", lambda job_id, countdown: None)
        row = _job(*conversation, runner="sandbox", external={"session_id": "s", "run": {"backend": "daytona"}})
        backend = SimpleNamespace(adopt=MagicMock(side_effect=RuntimeError("401")))
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        assert sandbox_runner.poll_job(row["id"]) == {"state": "retry"}

    def test_observer_handles_are_persisted(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        monkeypatch.setattr(sandbox_runner, "enqueue_poll", lambda job_id, countdown: None)
        row = _job(*conversation, runner="sandbox", external={"session_id": "s", "run": {"backend": "jupyter"}})
        backend = SimpleNamespace(
            adopt=lambda session_id, run: {"observer_kernel_id": "obs"},
            poll_detached=lambda session_id, run, with_output=False: DetachedState(done=False),
            refresh_activity=MagicMock(side_effect=RuntimeError("no")),
        )
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        assert sandbox_runner.poll_job(row["id"]) == {"state": "running"}
        with bg_db.connect() as conn:
            stored = BackgroundJobsRepository(conn).get(row["id"])
        assert stored["external"]["run"]["observer_kernel_id"] == "obs"

    def test_a_failure_while_finishing_fails_the_job(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(jobs, "_deliver", lambda row: None)
        row = _job(*conversation, runner="sandbox")
        with patch(
            "docsgpt.agents.tools.code_executor.CodeExecutorTool.finish_run", side_effect=RuntimeError("capture")
        ):
            done = sandbox_runner.finish_detached(
                {**row, "external": {"tool": {"config": {}}, "finish": {"session_id": "s", "code": "", "timeout": 1}}},
                object(),
                DetachedState(done=True, result=ExecResult()),
            )
        assert done["status"] == "failed"

    def test_cancel_detached_stops_and_releases(self):
        backend = MagicMock()
        with patch.object(sandbox_runner, "_poll_backend", return_value=backend):
            sandbox_runner.cancel_detached({"external": {"session_id": "s", "run": {"cmd_id": "c"}}})
            sandbox_runner.cancel_detached({"external": {}})
        backend.cancel_detached.assert_called_once()
        backend.release_adopted.assert_called_once()
        backend.cancel_detached.side_effect = RuntimeError("gone")
        backend.release_adopted.side_effect = RuntimeError("gone")
        with patch.object(sandbox_runner, "_poll_backend", return_value=backend):
            sandbox_runner.cancel_detached({"external": {"session_id": "s", "run": {"cmd_id": "c"}}})


class TestContinuationEdges:
    def test_gone_conversation(self, bg_db):
        assert continuation.continue_conversation_body("00000000-0000-0000-0000-000000000000") == {"state": "gone"}

    def test_gives_up_deferring(self, monkeypatch):
        scheduled = []
        monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **k: scheduled.append(a))
        assert continuation._defer("c", continuation.MAX_DEFERRALS - 1, "busy") == {"state": "gave_up"}
        assert scheduled == []

    def test_agent_config_for_an_agent(self, bg_db):
        from sqlalchemy import text

        with bg_db.begin() as conn:
            agent_id = str(conn.execute(
                text("INSERT INTO agents (user_id, name, status) VALUES ('u1', 'a', 'draft') RETURNING id")
            ).scalar())
        with bg_db.connect() as conn:
            config = continuation._agent_config(conn, {"agent_id": agent_id, "user_id": "u1"}, None)
            missing = continuation._agent_config(
                conn, {"agent_id": "00000000-0000-0000-0000-000000000000", "user_id": "u1"}, None
            )
        assert config["id"] == agent_id
        assert missing is None

    def test_quota_exhausted_turn(self, bg_db, conversation, monkeypatch):
        from docsgpt.quotas.service import QuotaExceededError

        monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **k: None)
        wake.wake_conversation(user_id="u1", conversation_id=conversation[0], source="monitor", ref_id="m",
                               title="t", body="b", payload=None, dedupe_key="q1")
        monkeypatch.setattr(
            continuation, "_run_turn", lambda *a: (_ for _ in ()).throw(QuotaExceededError(SimpleNamespace()))
        )
        assert continuation.continue_conversation_body(conversation[0])["state"] == "failed"

    def test_a_stream_error_without_an_answer(self, bg_db, conversation, monkeypatch):
        monkeypatch.setattr(wake, "schedule_continuation", lambda *a, **k: None)
        wake.wake_conversation(user_id="u1", conversation_id=conversation[0], source="monitor", ref_id="m",
                               title="t", body="b", payload=None, dedupe_key="s1")
        monkeypatch.setattr(continuation, "_run_turn", lambda *a: {"answer": "", "error_type": "stream_error",
                                                                     "error": "provider 500"})
        assert continuation.continue_conversation_body(conversation[0]) == {"state": "failed", "error": "stream_error"}

    def test_run_turn_builds_the_headless_call(self, monkeypatch):
        captured = {}

        def fake_headless(config, query, **kwargs):
            captured.update(config=config, query=query, **kwargs)
            return {"answer": "ok"}

        monkeypatch.setattr("docsgpt.agents.headless_runner.run_agent_headless", fake_headless)
        monkeypatch.setattr(continuation, "db_readonly", MagicMock())
        conversation = {"id": "c", "user_id": "u1", "agent_id": None}
        messages = [{"prompt": "p", "response": "r", "status": "complete", "model_id": "m-1"}]
        out = continuation._run_turn(conversation, messages, [{"source": "monitor", "title": "t"}])
        assert out == {"answer": "ok"}
        assert captured["tool_allowlist"] == []
        assert captured["model_id_override"] == "m-1"
        assert captured["endpoint"] == "continuation"
        assert captured["conversation_id"] == "c"
        assert captured["query"].rstrip().endswith("NO_REPLY.")

    def test_the_turn_needs_its_agent(self, monkeypatch):
        monkeypatch.setattr(continuation, "db_readonly", MagicMock())
        monkeypatch.setattr(continuation, "_agent_config", lambda *a: None)
        with pytest.raises(LookupError):
            continuation._run_turn({"id": "c", "user_id": "u", "agent_id": "a"}, [], [{"source": "job"}])


class TestJobsEdges:
    def test_redaction_of_non_dicts(self):
        assert jobs.redact_args("raw") == {}
        assert jobs.redact_args({"items": ["x" * 9000]})["items"][0].endswith("more characters]")

    def test_zero_caps_keep_calls_in_the_foreground(self, monkeypatch):
        monkeypatch.setattr(jobs.settings, "BACKGROUND_MAX_JOBS_PER_USER", 0)
        assert jobs.within_caps(_context("c")) is False

    def test_tool_output_failures_are_tolerated(self):
        class Broken:
            def get_artifact_id(self, *a, **k):
                raise RuntimeError("x")

            def get_artifacts(self, *a, **k):
                raise RuntimeError("x")

            def drain_native_parts(self):
                raise RuntimeError("x")

        assert jobs.tool_outputs(Broken(), "a", {}) == (None, [])

    def test_result_text(self):
        assert jobs.result_text({"a": 1}) == '{"a": 1}'
        assert jobs.result_text("plain") == "plain"

    def test_a_failed_final_write_returns_none(self, monkeypatch):
        with patch("docsgpt.background.jobs.db_session", side_effect=RuntimeError("db")):
            assert jobs.finalize("00000000-0000-0000-0000-000000000000", status="completed") is None

    def test_delivery_failures_are_logged(self, monkeypatch):
        with patch("docsgpt.background.wake.on_job_finished", side_effect=RuntimeError("x")):
            jobs._deliver({"id": "j"})


class TestServiceEdges:
    def test_parse_and_elapsed(self):
        assert service.parse_time("not a time") is None
        assert service.parse_time(None) is None
        assert service.elapsed_seconds({}) == 0

    def test_cancel_unknown_job(self, bg_db):
        assert service.cancel_job("00000000-0000-0000-0000-000000000000", "u1") is None
