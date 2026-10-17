"""The tool-result guardrail on background work: job results and wake data, before they are stored."""

from __future__ import annotations

import json
import threading

import pytest
from sqlalchemy import text

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.background import guard, jobs, sandbox_runner, wake
from docsgpt.background.context import BackgroundContext
from docsgpt.guardrails.types import TOOL_RESULT_BLOCKED_NOTE
from docsgpt.sandbox.base import DetachedState, ExecResult
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository

from .test_executor_handoff import _TOOLS, _call, _drain, _executor, _job_for, _SlowTool, _wait_for
from .test_sandbox_runner import _Backend, _sandbox_job

SECRET = "AKIAIOSFODNN7EXAMPLE"

_BLOCK_RAVEN = {"check": "denylist", "stage": "tool_result", "action": "block", "settings": {"terms": ["raven"]}}
_REDACT_SECRETS = {"check": "secrets", "stage": "tool_result", "action": "redact"}


def _guardrails(*controls):
    return {"enabled": True, "mode": "scan_all", "controls": list(controls)}


@pytest.fixture()
def block_floor(monkeypatch):
    """An instance floor that withholds any tool result naming "raven"."""
    monkeypatch.setattr("docsgpt.core.settings.settings.GUARDRAILS_FLOOR", _guardrails(_BLOCK_RAVEN))


@pytest.fixture()
def redact_floor(monkeypatch):
    """An instance floor that masks credentials in tool results."""
    monkeypatch.setattr("docsgpt.core.settings.settings.GUARDRAILS_FLOOR", _guardrails(_REDACT_SECRETS))


@pytest.fixture()
def no_delivery(monkeypatch):
    delivered = []
    monkeypatch.setattr(jobs, "_deliver", delivered.append)
    return delivered


@pytest.fixture()
def scheduled(monkeypatch):
    calls = []
    monkeypatch.setattr(wake, "schedule_continuation", lambda cid, countdown=2.0, attempt=0: calls.append(cid))
    return calls


def _context(conversation_id, message_id, agent_id=None):
    context = BackgroundContext(
        user_id="u1", conversation_id=conversation_id, origin_message_id=message_id, agent_id=agent_id
    )
    context._auto_resume = True
    return context


def _new_job(conversation_id, message_id, *, agent_id=None, tool_name="read_webpage", action_name="read"):
    row, _ = jobs.create_job(
        _context(conversation_id, message_id, agent_id),
        tool_name=tool_name,
        action_name=action_name,
        journal_key=f"{message_id}:c1",
        arguments={},
    )
    return row


def _get(engine, job_id):
    with engine.connect() as conn:
        return BackgroundJobsRepository(conn).get(job_id)


def _events(engine):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT message_id, stage, check_name FROM guardrail_events")).fetchall()
    return [dict(r._mapping) for r in rows]


def _wakes(engine, conversation_id):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM conversation_wakes WHERE conversation_id = CAST(:c AS uuid) ORDER BY created_at"),
            {"c": conversation_id},
        ).fetchall()
    return [dict(r._mapping) for r in rows]


def _agent(engine, guardrails, default_model_id=None):
    with engine.begin() as conn:
        row = AgentsRepository(conn).create(
            "u1", "a", "published", config={"guardrails": guardrails}, default_model_id=default_model_id
        )
    return str(row["id"])


class TestJobResults:
    def test_the_continuing_thread_stores_the_withheld_note(
        self, bg_db, conversation, monkeypatch, block_floor, no_delivery
    ):
        monkeypatch.setattr("docsgpt.core.settings.settings.BACKGROUND_YIELD_SECONDS", 1)
        conversation_id, message_id = conversation
        gate = threading.Event()
        tool = _SlowTool(0, gate)
        executor = _executor(conversation_id, message_id, tool, monkeypatch)
        result, _ = _drain(executor.execute(_TOOLS, _call({"url": "raven"}), "OpenAILLM"))[1]
        assert result["status"] == "running"
        gate.set()
        finished = _wait_for(lambda: (j := _job_for(bg_db, conversation_id)) and j["status"] != "working" and j)
        assert finished["status"] == "completed"
        assert finished["result"]["text"] == TOOL_RESULT_BLOCKED_NOTE
        with bg_db.connect() as conn:
            journal = conn.execute(
                text("SELECT result FROM tool_call_attempts WHERE call_id = :k"), {"k": f"{message_id}:c1"}
            ).scalar()
        assert "raven" not in json.dumps(journal)
        # Recorded against the turn that started the job, as a foreground scan is.
        assert {(str(e["message_id"]), e["stage"], e["check_name"]) for e in _events(bg_db)} == {
            (message_id, "tool_result", "denylist")
        }

    def test_the_celery_runner_stores_the_withheld_note(
        self, bg_db, conversation, monkeypatch, block_floor, no_delivery
    ):
        from docsgpt.background import celery_runner

        conversation_id, message_id = conversation
        queued = []
        monkeypatch.setattr(celery_runner, "enqueue", lambda job_id, payload: queued.append((job_id, payload)) or True)
        tool = _SlowTool(0)
        executor = _executor(conversation_id, message_id, tool, monkeypatch)
        _drain(executor.execute(_TOOLS, _call({"url": "raven", "background": True}), "OpenAILLM"))
        job_id, payload = queued[0]
        monkeypatch.setattr(ToolExecutor, "get_tools", lambda self: _TOOLS)
        monkeypatch.setattr(ToolExecutor, "_get_or_load_tool", lambda self, *a, **k: tool)
        assert celery_runner.run_job(job_id, payload)["state"] == "finished"
        assert _get(bg_db, job_id)["result"]["text"] == TOOL_RESULT_BLOCKED_NOTE

    def test_the_sandbox_poller_guards_the_result_and_the_output(
        self, bg_db, conversation, monkeypatch, block_floor, no_delivery
    ):
        monkeypatch.setattr(sandbox_runner, "enqueue_poll", lambda job_id, countdown: None)
        job_id = _sandbox_job(*conversation)
        backend = _Backend([DetachedState(done=True, result=ExecResult(stdout="the raven\n"), output="the raven\n")])
        monkeypatch.setattr(sandbox_runner, "_poll_backend", lambda: backend)
        assert sandbox_runner.poll_job(job_id)["state"] == "finished"
        row = _get(bg_db, job_id)
        assert row["result"]["text"] == TOOL_RESULT_BLOCKED_NOTE
        assert row["output_tail"] == TOOL_RESULT_BLOCKED_NOTE
        # The continuation reads the stored result: the note, never the output.
        assert "raven" not in json.dumps(wake.job_event(row))

    def test_a_redaction_keeps_the_rest_of_the_result(self, bg_db, conversation, redact_floor, no_delivery):
        row = _new_job(*conversation)
        done = jobs.complete_from_tool(
            row["id"], tool=object(), action_name="read", parameters={}, value=f"key {SECRET} works"
        )
        assert SECRET not in done["result"]["text"]
        assert done["result"]["text"].endswith("works")
        assert done["status"] == "completed"

    def test_the_jobs_agent_brings_its_own_guardrails(self, bg_db, conversation, no_delivery):
        from docsgpt.core.model_utils import get_default_model_id

        # A judge check would run on the agent's own model.
        agent_id = _agent(bg_db, _guardrails(_BLOCK_RAVEN), default_model_id=get_default_model_id())
        row = _new_job(*conversation, agent_id=agent_id)
        done = jobs.complete_from_tool(row["id"], tool=object(), action_name="read", parameters={}, value="raven")
        assert done["result"]["text"] == TOOL_RESULT_BLOCKED_NOTE

    def test_no_active_guardrails_leave_the_result_alone(self, bg_db, conversation, no_delivery):
        row = _new_job(*conversation)
        done = jobs.complete_from_tool(row["id"], tool=object(), action_name="read", parameters={}, value="raven")
        assert done["result"]["text"] == "raven"

    def test_a_failing_guardrail_lets_the_result_through(
        self, bg_db, conversation, monkeypatch, block_floor, no_delivery
    ):
        def boom(self, value, stage, controls=None):
            raise RuntimeError("scanner down")

        monkeypatch.setattr("docsgpt.guardrails.engine.GuardrailEngine.evaluate", boom)
        row = _new_job(*conversation)
        done = jobs.complete_from_tool(row["id"], tool=object(), action_name="read", parameters={}, value="raven")
        assert done["result"]["text"] == "raven"

    def test_a_job_that_already_ended_is_not_scanned(self, bg_db, conversation, monkeypatch, block_floor, no_delivery):
        row = _new_job(*conversation)
        jobs.finalize(row["id"], status="cancelled")
        scanned = []
        monkeypatch.setattr(guard, "guard_job_texts", lambda *a: scanned.append(a) or a[1:])
        assert jobs.finalize(row["id"], status="completed", result={"text": "raven", "status": "completed"}) is None
        assert scanned == []

    def test_an_unreadable_job_keeps_its_result(self, bg_db, conversation, monkeypatch, block_floor):
        def broken():
            raise RuntimeError("db down")

        monkeypatch.setattr(jobs, "db_readonly", broken)
        result, tail = jobs._guard_final("00000000-0000-0000-0000-000000000000", {"text": "raven"}, None)
        assert result == {"text": "raven"} and tail is None


class TestWakePayloads:
    def test_a_monitor_payload_that_trips_a_block_is_withheld(self, bg_db, conversation, block_floor, scheduled):
        conversation_id, _ = conversation
        wake.wake_conversation(
            user_id="u1",
            conversation_id=conversation_id,
            source="monitor",
            ref_id="m1",
            title="Page changed",
            body="b",
            payload={"excerpt": "a raven appeared"},
            dedupe_key="monitor:m1:1",
        )
        [row] = _wakes(bg_db, conversation_id)
        assert row["payload"] == {"withheld": TOOL_RESULT_BLOCKED_NOTE}
        assert "raven" not in wake.render_events([row])

    def test_a_redacted_payload_keeps_its_shape(self, bg_db, conversation, redact_floor, scheduled):
        conversation_id, _ = conversation
        wake.wake_conversation(
            user_id="u1",
            conversation_id=conversation_id,
            source="trigger",
            ref_id="l1",
            title="Webhook received",
            body="b",
            payload={"body": {"token": SECRET, "status": "ok"}},
            dedupe_key="trigger:l1:1",
        )
        [row] = _wakes(bg_db, conversation_id)
        assert row["payload"]["body"]["status"] == "ok"
        assert SECRET not in json.dumps(row["payload"])

    def test_a_watch_wake_is_scanned_but_a_stored_result_is_not_rescanned(
        self, bg_db, conversation, block_floor, scheduled
    ):
        conversation_id, _ = conversation
        common = {"user_id": "u1", "conversation_id": conversation_id, "source": "job", "ref_id": "j1", "body": "b"}
        wake.wake_conversation(**common, title="output matched", payload={"line": "raven"}, dedupe_key="job:j1:w")
        wake.wake_conversation(
            **common, title="finished", payload={"result": "raven"}, dedupe_key="job:j1:final", guarded=True
        )
        watch_row, final_row = _wakes(bg_db, conversation_id)
        assert watch_row["payload"] == {"withheld": TOOL_RESULT_BLOCKED_NOTE}
        assert final_row["payload"] == {"result": "raven"}

    def test_the_conversations_agent_decides(self, bg_db, scheduled):
        agent_id = _agent(bg_db, _guardrails(_BLOCK_RAVEN))
        with bg_db.begin() as conn:
            conversation_id = str(ConversationsRepository(conn).create("u1", "chat", agent_id=agent_id)["id"])
        wake.wake_conversation(
            user_id="u1",
            conversation_id=conversation_id,
            source="approval",
            ref_id="l1",
            title="Approval received",
            body="b",
            payload={"decision": "approve", "comment": "raven"},
            dedupe_key="approval:l1",
        )
        assert _wakes(bg_db, conversation_id)[0]["payload"] == {"withheld": TOOL_RESULT_BLOCKED_NOTE}

    def test_a_clean_payload_is_queued_as_it_came(self, bg_db, conversation, block_floor, scheduled):
        conversation_id, _ = conversation
        wake.wake_conversation(
            user_id="u1",
            conversation_id=conversation_id,
            source="monitor",
            ref_id="m1",
            title="t",
            body="b",
            payload={"excerpt": "a crow"},
            dedupe_key="monitor:m1:3",
        )
        assert _wakes(bg_db, conversation_id)[0]["payload"] == {"excerpt": "a crow"}

    def test_no_active_guardrails_leave_the_payload_alone(self, bg_db, conversation, scheduled):
        conversation_id, _ = conversation
        wake.wake_conversation(
            user_id="u1",
            conversation_id=conversation_id,
            source="monitor",
            ref_id="m1",
            title="t",
            body="b",
            payload={"excerpt": "raven"},
            dedupe_key="monitor:m1:2",
        )
        assert _wakes(bg_db, conversation_id)[0]["payload"] == {"excerpt": "raven"}


class TestGuardHelpers:
    def test_scrubbed_text_that_is_no_longer_json_is_kept_as_data(self, monkeypatch):
        monkeypatch.setattr(guard, "conversation_agent", lambda cid: None)
        monkeypatch.setattr(guard, "engine_for", lambda **kw: object())
        monkeypatch.setattr(guard, "scan", lambda engine, value, **kw: "not json [REDACTED]")
        out = guard.guard_payload(user_id="u1", conversation_id="c", source="monitor", payload={"a": "b"})
        assert out == {"data": "not json [REDACTED]"}

    def test_scrubbed_json_that_is_not_an_object_is_kept_as_data(self, monkeypatch):
        monkeypatch.setattr(guard, "conversation_agent", lambda cid: None)
        monkeypatch.setattr(guard, "engine_for", lambda **kw: object())
        monkeypatch.setattr(guard, "scan", lambda engine, value, **kw: "[1]")
        out = guard.guard_payload(user_id="u1", conversation_id="c", source="monitor", payload={"a": "b"})
        assert out == {"data": "[1]"}

    def test_a_failing_lookup_lets_the_payload_through(self, monkeypatch):
        def broken(cid):
            raise RuntimeError("db down")

        monkeypatch.setattr(guard, "conversation_agent", broken)
        assert guard.guard_payload(user_id="u1", conversation_id="c", source="monitor", payload={"a": 1}) == {"a": 1}

    def test_an_empty_payload_is_not_scanned(self):
        assert guard.guard_payload(user_id="u1", conversation_id="c", source="monitor", payload=None) is None

    def test_a_failing_engine_build_lets_job_texts_through(self, monkeypatch):
        def broken(**kw):
            raise RuntimeError("no config")

        monkeypatch.setattr(guard, "engine_for", broken)
        assert guard.guard_job_texts({"id": "j"}, "raven", None) == ("raven", None)

    def test_nothing_to_scan_builds_no_engine(self, monkeypatch):
        monkeypatch.setattr(guard, "engine_for", lambda **kw: pytest.fail("built an engine"))
        assert guard.guard_job_texts({"id": "j"}, None, "") == (None, "")

    def test_a_failing_audit_write_keeps_the_verdict(self, monkeypatch):
        class _Recorder:
            def flush(self, message_id=None):
                raise RuntimeError("db down")

        class _Decision:
            blocked = True
            redacted = False

        class _Engine:
            context = type("C", (), {})()
            recorder = _Recorder()

            def evaluate(self, value, stage):
                return _Decision()

        assert guard.scan(_Engine(), "raven", tool_name="t", action_name="a") == TOOL_RESULT_BLOCKED_NOTE

    def test_ids_are_looked_up_only_when_given(self):
        assert guard.conversation_agent(None) is None
        assert guard._agent_row(None) is None
