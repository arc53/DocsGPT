"""A webhook's signing secret is stored only encrypted in ``trigger_links``, never anywhere else.

The secret used to be in the ``monitor_create`` tool result (and in the
``example_curl`` it returned), so it reached the model, the conversation, the
tool-call journal, both activity logs and the request trace in plain text.
The model now gets a placeholder; here the create runs through the real
executor and every place a turn persists its tool result is written, then
every table is searched for the secret.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from docsgpt import tracing
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tools.monitor import MonitorTool
from docsgpt.core.settings import settings
from docsgpt.llm.handlers.base import ToolCall
from docsgpt.monitors import links, service
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.user_logs import UserLogsRepository


def _run(gen):
    events = []
    while True:
        try:
            events.append(next(gen))
        except StopIteration as stop:
            return events, stop.value


def _every_row(engine):
    """``{table: all its rows as text}`` for every table in the database."""
    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        ]
        return {
            table: "\n".join(row[0] for row in conn.execute(text(f'SELECT t::text FROM "{table}" t')))
            for table in tables
        }


@pytest.mark.parametrize("scheme", ["github", "standard_webhooks", "hmac_sha256"])
def test_the_secret_is_only_in_the_encrypted_link(mon_db, conversation_id, events, monkeypatch, scheme):
    # Loading a tool imports every tool module; the app's own import order avoids their import cycle.
    import docsgpt.app  # noqa: F401

    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com")
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)

    executor = ToolExecutor(user="u1", decoded_token={"sub": "u1"})
    executor.conversation_id = conversation_id
    tools = {
        "monitor": {
            "id": "monitor",
            "name": "monitor",
            "config": {},
            "actions": [{**a, "active": True} for a in MonitorTool().get_actions_metadata()],
        }
    }
    executor.prepare_tools_for_llm(tools)
    arguments = {
        "description": "Production deploy finished",
        "source": {"type": "webhook", "signature": scheme},
        "on_match": "tell me how the deploy went",
    }
    call = ToolCall(id="call-1", name="monitor_create", arguments=json.dumps(arguments))

    trace = tracing.start_trace(source="chat", user_id="u1", conversation_id=conversation_id)
    with tracing.activate(trace):
        streamed, (result, _call_id) = _run(executor.execute(tools, call, "OpenAILLM"))

    created = json.loads(result)
    assert created["secret"] == "{{link_secret:" + created["secret_ref"] + "}}"
    # What a turn persists from here: the message, both activity logs and the trace.
    with mon_db.begin() as conn:
        ConversationsRepository(conn).append_message(
            conversation_id,
            {"prompt": "tell me when the deploy finishes", "response": created["next"],
             "tool_calls": executor.tool_calls},
        )
        UserLogsRepository(conn).insert(
            user_id="u1", endpoint="stream", data={"tool_calls": executor.tool_calls, "streamed": streamed}
        )
    from docsgpt.logging import _log_activity_to_db

    _log_activity_to_db(
        "stream", "activity-1", "u1", None, "q",
        [{"component": "tool_executor", "data": {"tool_calls": executor.tool_calls}}], "info",
    )
    from docsgpt.tracing.sink import flush

    future = flush(trace)
    if future is not None:
        future.result(timeout=30)

    revealed = service.reveal_secret(created["monitor_id"], "u1")
    assert revealed is not None
    secret = revealed["secret"]

    rows = _every_row(mon_db)
    for table in ("tool_call_attempts", "conversation_messages", "user_logs", "stack_logs", "request_traces"):
        assert rows[table], f"{table} has no row, so the check below proves nothing"
    leaked = [table for table, dump in rows.items() if secret in dump]
    assert leaked == []
    with mon_db.connect() as conn:
        sealed = conn.execute(text("SELECT secret_encrypted FROM trigger_links")).scalar()
    assert links.open_secret(sealed, "u1") == secret


def test_a_secret_filled_into_approved_calls_is_only_in_the_encrypted_link(
    mon_db, conversation_id, events, monkeypatch
):
    """The reference reaches a tool as the real value, and nothing a turn or a job persists keeps that value.

    An approved MCP-style call gets the secret and echoes it; a background device job's command is given it
    and prints it. The message, both activity logs, the trace, the journal, the job row and its audit trail
    are all written, then every table is searched.
    """
    import docsgpt.app  # noqa: F401
    from docsgpt.background import device_runner, jobs
    from docsgpt.background.context import BackgroundContext
    from docsgpt.devices.broker import DeviceBroker
    from docsgpt.storage.db.repositories.devices import DevicesRepository
    from tests.devices.conftest import FakeRedis

    monkeypatch.setattr(settings, "PUBLIC_API_BASE_URL", "https://docs.example.com")
    monkeypatch.setattr(settings, "TRACES_ENABLED", True)
    monkeypatch.setattr(settings, "TRACES_CAPTURE_CONTENT", True)
    created = service.create(
        service.Caller(user_id="u1", conversation_id=conversation_id),
        {"description": "Pushes", "source": {"type": "webhook", "signature": "github"}, "on_match": "tell me"},
    )
    reference = created["secret"]
    secret = service.reveal_secret(created["monitor_id"], "u1")["secret"]

    class _Echo:
        def execute_action(self, action_name, **kwargs):
            return f"hook created with secret {kwargs['config']['secret']}"

    executor = ToolExecutor(user="u1", decoded_token={"sub": "u1"})
    executor.conversation_id = conversation_id
    tools = {
        "t1": {
            "id": "00000000-0000-0000-0000-0000000000e1",
            "name": "mcp_tool",
            "config": {},
            "actions": [
                {
                    "name": "create_repository_webhook",
                    "active": True,
                    "parameters": {"type": "object", "properties": {"config": {"type": "object", "filled_by_llm": True}}},
                }
            ],
        }
    }
    executor._name_to_tool = {"create_repository_webhook": ("t1", "create_repository_webhook")}
    monkeypatch.setattr(executor, "_get_or_load_tool", lambda *a, **k: _Echo())
    executor.approved_call_ids.add("call-2")
    call = ToolCall(
        id="call-2",
        name="create_repository_webhook",
        arguments=json.dumps({"config": {"url": created["url"], "secret": reference}}),
    )
    trace = tracing.start_trace(source="chat", user_id="u1", conversation_id=conversation_id)
    with tracing.activate(trace):
        streamed, (result, _call_id) = _run(executor.execute(tools, call, "OpenAILLM"))
    assert result == f"hook created with secret {reference}"

    with mon_db.begin() as conn:
        ConversationsRepository(conn).append_message(
            conversation_id,
            {"prompt": "set up the hook yourself", "response": "done", "tool_calls": executor.tool_calls},
        )
        UserLogsRepository(conn).insert(
            user_id="u1", endpoint="stream", data={"tool_calls": executor.tool_calls, "streamed": streamed}
        )
    from docsgpt.logging import _log_activity_to_db

    _log_activity_to_db(
        "stream", "activity-2", "u1", None, "q",
        [{"component": "tool_executor", "data": {"tool_calls": executor.tool_calls}}], "info",
    )
    from docsgpt.tracing.sink import flush

    future = flush(trace)
    if future is not None:
        future.result(timeout=30)

    # A background device job whose command was given the secret, and printed it.
    fake = FakeRedis()
    monkeypatch.setattr("docsgpt.devices.broker.get_redis_instance", lambda: fake)
    broker = DeviceBroker()
    monkeypatch.setattr(device_runner, "_broker", lambda: broker)
    monkeypatch.setattr(device_runner, "enqueue_poll", lambda *a: None)
    monkeypatch.setattr(jobs, "_deliver", lambda row: None)
    with mon_db.begin() as conn:
        DevicesRepository(conn).create("dev_p", "u1", "laptop", machine_pubkey_fingerprint="fp", token_hash="th")
        message = ConversationsRepository(conn).append_message(conversation_id, {"prompt": "p", "response": "r"})
    context = BackgroundContext(user_id="u1", conversation_id=conversation_id, origin_message_id=str(message["id"]))
    context._auto_resume = True
    job, _ = jobs.create_job(
        context, tool_name="remote_device", action_name="run_command", journal_key="m:c9",
        arguments={"command": f"register --secret {reference}"},
    )
    broker.dispatch_invocation("dev_p", "u1", {"invocation_id": "inv_p", "action": "run_command"})
    device_runner.detach_job(str(job["id"]), {
        "invocation_id": "inv_p", "device_id": "dev_p", "device_name": "laptop", "timeout_ms": 60_000,
        "dispatched_at": 0, "secret_refs": [created["secret_ref"]],
    })
    broker.submit_ack("inv_p", "accepted")
    broker.submit_output_chunk("inv_p", {"stream": "stdout", "chunk": f"registered with {secret}\n"})
    device_runner.poll_job(str(job["id"]))
    broker.submit_output_chunk("inv_p", {"stream": "stderr", "chunk": f"key={secret}\n"})
    broker.submit_output_chunk("inv_p", {"stream": "control", "exit_code": 0})
    assert device_runner.poll_job(str(job["id"]))["status"] == "completed"

    rows = _every_row(mon_db)
    for table in ("tool_call_attempts", "conversation_messages", "user_logs", "stack_logs", "request_traces",
                  "background_jobs", "auth_events"):
        assert rows[table], f"{table} has no row, so the check below proves nothing"
    assert reference in rows["background_jobs"]
    leaked = [table for table, dump in rows.items() if secret in dump]
    assert leaked == []
