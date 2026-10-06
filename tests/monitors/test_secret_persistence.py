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
    assert created["secret"] == links.SECRET_PLACEHOLDER
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
