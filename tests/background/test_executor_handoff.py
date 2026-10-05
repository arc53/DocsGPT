"""ToolExecutor with a background context: a slow call becomes a job, a fast one is unchanged."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.background import jobs, pool
from docsgpt.background.context import BackgroundContext
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository

_TOOL_ROW_ID = "00000000-0000-0000-0000-0000000000aa"
_TOOLS = {
    "t1": {
        "id": _TOOL_ROW_ID,
        "name": "read_webpage",
        "config": {},
        "actions": [
            {
                "name": "read",
                "description": "Read",
                "parameters": {"properties": {"url": {"type": "string", "filled_by_llm": True}}},
            }
        ],
    }
}


class _SlowTool:
    def __init__(self, delay: float, gate: threading.Event = None):
        self.delay = delay
        self.gate = gate
        self.calls = []

    def execute_action(self, action_name, **kwargs):
        self.calls.append(kwargs)
        if self.gate is not None:
            self.gate.wait(10)
        else:
            time.sleep(self.delay)
        return f"page for {kwargs.get('url')}"


def _call(arguments, call_id="c1"):
    call = Mock()
    call.name = "read"
    call.id = call_id
    call.arguments = json.dumps(arguments)
    call.thought_signature = None
    return call


def _drain(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as exc:
            return events, exc.value


def _executor(conversation_id, message_id, tool, monkeypatch):
    executor = ToolExecutor(user="u1")
    executor.conversation_id = conversation_id
    executor.message_id = message_id
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=message_id)
    context._auto_resume = True
    executor.background = context
    executor._name_to_tool = {"read": ("t1", "read")}
    monkeypatch.setattr(executor, "_get_or_load_tool", lambda *a, **k: tool)
    return executor


@pytest.fixture()
def no_delivery(monkeypatch):
    delivered = []
    monkeypatch.setattr(jobs, "_deliver", delivered.append)
    return delivered


@pytest.fixture()
def fast_yield(monkeypatch):
    monkeypatch.setattr("docsgpt.core.settings.settings.BACKGROUND_YIELD_SECONDS", 1)


def _job_for(engine, conversation_id):
    with engine.connect() as conn:
        rows = BackgroundJobsRepository(conn).list_for_conversation(conversation_id, "u1")
    return rows[0] if rows else None


def _wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    return None


class TestExecutorHandOff:
    def test_fast_call_is_unchanged(self, bg_db, conversation, monkeypatch, fast_yield, no_delivery):
        conversation_id, message_id = conversation
        tool = _SlowTool(0)
        executor = _executor(conversation_id, message_id, tool, monkeypatch)
        events, (result, call_id) = _drain(executor.execute(_TOOLS, _call({"url": "a"}), "OpenAILLM"))
        assert result == "page for a"
        assert call_id == "c1"
        assert executor.tool_calls[-1]["status"] == "completed"
        assert "job_id" not in executor.tool_calls[-1]
        assert _job_for(bg_db, conversation_id) is None

    def test_slow_call_becomes_a_job_and_finishes_in_the_background(
        self, bg_db, conversation, monkeypatch, fast_yield, no_delivery
    ):
        conversation_id, message_id = conversation
        gate = threading.Event()
        tool = _SlowTool(0, gate)
        executor = _executor(conversation_id, message_id, tool, monkeypatch)
        started = time.monotonic()
        events, (result, _call_id) = _drain(
            executor.execute(_TOOLS, _call({"url": "b", "background": False}), "OpenAILLM")
        )
        assert time.monotonic() - started < 5
        assert result["status"] == "running"
        job_id = result["job_id"]
        entry = executor.tool_calls[-1]
        assert entry["status"] == "pending"
        assert entry["job_id"] == job_id
        assert executor.get_truncated_tool_calls()[-1]["job_id"] == job_id
        assert events[-1]["data"]["job_id"] == job_id
        # Controls never reach the tool.
        assert tool.calls == [{"url": "b"}]
        # The tool instance is no longer cached for the next call.
        assert executor._loaded_tools == {}

        job = _job_for(bg_db, conversation_id)
        assert job["id"] == job_id
        assert job["status"] == "working"
        assert job["tool_call_id"] == f"{message_id}:c1"
        assert job_id in pool.held()
        with bg_db.connect() as conn:
            journal = conn.execute(
                text("SELECT status FROM tool_call_attempts WHERE call_id = :k"), {"k": f"{message_id}:c1"}
            ).scalar()
        assert journal == "proposed"

        gate.set()
        finished = _wait_for(lambda: (j := _job_for(bg_db, conversation_id)) and j["status"] != "working" and j)
        assert finished["status"] == "completed"
        assert finished["result"]["text"] == "page for b"
        assert job_id not in pool.held()
        assert [row["id"] for row in no_delivery] == [job_id]
        with bg_db.connect() as conn:
            journal = conn.execute(
                text("SELECT status FROM tool_call_attempts WHERE call_id = :k"), {"k": f"{message_id}:c1"}
            ).scalar()
        assert journal == "confirmed"

    def test_explicit_background_hands_off_without_waiting(
        self, bg_db, conversation, monkeypatch, no_delivery
    ):
        conversation_id, message_id = conversation
        gate = threading.Event()
        executor = _executor(conversation_id, message_id, _SlowTool(0, gate), monkeypatch)
        started = time.monotonic()
        _events, (result, _) = _drain(executor.execute(_TOOLS, _call({"url": "c", "background": True}), "OpenAILLM"))
        assert time.monotonic() - started < 1
        assert result["status"] == "running"
        gate.set()
        assert _wait_for(lambda: (j := _job_for(bg_db, conversation_id)) and j["status"] == "completed")

    def test_without_a_context_controls_are_not_stripped(self, bg_db, conversation, monkeypatch):
        conversation_id, message_id = conversation
        tool = _SlowTool(0)
        executor = _executor(conversation_id, message_id, tool, monkeypatch)
        executor.background = None
        _drain(executor.execute(_TOOLS, _call({"url": "d"}), "OpenAILLM"))
        assert tool.calls == [{"url": "d"}]
