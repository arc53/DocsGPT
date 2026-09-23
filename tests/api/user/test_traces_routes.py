"""Tests for ``GET /api/traces`` and the trace summaries on ``get_user_logs`` rows."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask

from docsgpt.storage.db.repositories.request_traces import RequestTracesRepository


@pytest.fixture
def app():
    return Flask(__name__)


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield_conn():
        yield conn

    with patch("docsgpt.api.user.analytics.routes.db_readonly", _yield_conn):
        yield


def _trace(pg_conn, **overrides):
    record = {
        "id": str(uuid.uuid4()),
        "request_id": "req-1",
        "user_id": "owner",
        "source": "stream",
        "name": "stream",
        "status": "ok",
        "started_at_ns": time.time_ns(),
        "duration_ms": 900,
        "span_count": 2,
        "summary": {"llm_calls": 1, "tool_calls": 1, "input_tokens": 50, "retrieval_ms": 12.5},
        "spans": [
            {
                "id": "s1",
                "parent_id": None,
                "kind": "retrieval",
                "name": "retrieval",
                "status": "ok",
                "offset_ms": 0,
                "duration_ms": 12.5,
                "attributes": {},
                "preview": {"query": "how do I deploy"},
            }
        ],
    }
    record.update(overrides)
    RequestTracesRepository(pg_conn).insert(record)
    return record


def _get(app, pg_conn, user, query):
    from docsgpt.api.user.analytics.routes import GetTraces

    with _patch_db(pg_conn), app.test_request_context("/api/traces", query_string=query):
        from flask import request

        request.decoded_token = {"sub": user} if user else None
        return GetTraces().get()


def _logs(app, pg_conn, user, body):
    from docsgpt.api.user.analytics.routes import GetUserLogs

    with _patch_db(pg_conn), app.test_request_context(
        "/api/get_user_logs", method="POST", json=body
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        return GetUserLogs().post()


class TestGetTraces:
    def test_requires_auth(self, app, pg_conn):
        assert _get(app, pg_conn, None, {"request_id": "x"}).status_code == 401

    def test_requires_exactly_one_ref(self, app, pg_conn):
        assert _get(app, pg_conn, "owner", {}).status_code == 400
        assert _get(app, pg_conn, "owner", {"request_id": "a", "id": "b"}).status_code == 400

    def test_returns_own_trace_with_spans(self, app, pg_conn):
        record = _trace(pg_conn)
        response = _get(app, pg_conn, "owner", {"request_id": "req-1"})
        assert response.status_code == 200
        (trace,) = response.json["traces"]
        assert trace["id"] == record["id"]
        assert trace["spans"][0]["preview"]["query"] == "how do I deploy"
        assert "_id" not in trace

    def test_other_users_get_nothing(self, app, pg_conn):
        _trace(pg_conn)
        response = _get(app, pg_conn, "intruder", {"request_id": "req-1"})
        assert response.json["traces"] == []

    def test_agent_owner_sees_shared_callers_traces(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create("owner", "a", "published", key="k1")
        _trace(pg_conn, user_id="caller", agent_id=str(agent["id"]))
        response = _get(
            app, pg_conn, "owner", {"request_id": "req-1", "api_key_id": str(agent["id"])}
        )
        assert len(response.json["traces"]) == 1

    def test_unowned_agent_scope_is_empty(self, app, pg_conn):
        from docsgpt.storage.db.repositories.agents import AgentsRepository

        agent = AgentsRepository(pg_conn).create("someone", "a", "published", key="k2")
        _trace(pg_conn, user_id="someone", agent_id=str(agent["id"]))
        response = _get(
            app, pg_conn, "owner", {"request_id": "req-1", "api_key_id": str(agent["id"])}
        )
        assert response.json["traces"] == []


class TestLogsTraceSummaries:
    def test_chat_row_gets_merged_summary_across_rounds(self, app, pg_conn):
        from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

        UserLogsRepository(pg_conn).insert(
            user_id="owner",
            endpoint="stream_answer",
            data={"action": "stream_answer", "question": "q", "request_id": "req-1"},
        )
        _trace(pg_conn, status="paused")
        _trace(pg_conn, started_at_ns=time.time_ns() + 1_000_000)
        response = _logs(app, pg_conn, "owner", {"event_type": "chat"})
        (row,) = response.json["logs"]
        assert row["request_id"] == "req-1"
        trace = row["trace"]
        assert trace["ref"] == {"field": "request_id", "value": "req-1"}
        assert trace["count"] == 2
        assert trace["duration_ms"] == 1800
        assert trace["status"] == "ok"
        assert trace["summary"]["llm_calls"] == 2
        assert trace["summary"]["retrieval_ms"] == 25.0

    def test_row_without_trace_has_no_summary(self, app, pg_conn):
        from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

        UserLogsRepository(pg_conn).insert(
            user_id="owner", endpoint="stream_answer", data={"question": "old row"}
        )
        (row,) = _logs(app, pg_conn, "owner", {}).json["logs"]
        assert "trace" not in row

    def test_webhook_row_links_by_activity_id(self, app, pg_conn):
        from docsgpt.storage.db.repositories.stack_logs import StackLogsRepository

        StackLogsRepository(pg_conn).insert(
            activity_id="act-1", endpoint="webhook", level="info", user_id="owner", query="{}"
        )
        _trace(pg_conn, request_id="task-1", source="webhook", activity_id="act-1")
        (row,) = _logs(app, pg_conn, "owner", {"event_type": "webhook"}).json["logs"]
        assert row["activity_id"] == "act-1"
        assert row["trace"]["ref"] == {"field": "activity_id", "value": "act-1"}

    def test_search_traces_are_listed(self, app, pg_conn):
        record = _trace(
            pg_conn,
            request_id=None,
            source="mcp",
            name="mcp",
            status="error",
            summary={"llm_calls": 0, "query": "how do I deploy"},
        )
        _trace(pg_conn, request_id=None, source="graph_extraction", name="graph_extraction Docs")
        search_rows = _logs(app, pg_conn, "owner", {"event_type": "search"}).json["logs"]
        assert len(search_rows) == 1
        row = search_rows[0]
        assert row["id"] == f"search-{record['id']}"
        assert row["question"] == "how do I deploy"
        assert row["level"] == "error"
        assert row["action"] == "mcp"
        assert row["trace"]["ref"] == {"field": "id", "value": record["id"]}
        graph_rows = _logs(app, pg_conn, "owner", {"event_type": "graph"}).json["logs"]
        assert len(graph_rows) == 1

    def test_search_traces_of_other_users_are_hidden(self, app, pg_conn):
        _trace(pg_conn, request_id=None, source="search", user_id="someone")
        assert _logs(app, pg_conn, "owner", {"event_type": "search"}).json["logs"] == []

    def test_unknown_event_type_is_rejected(self, app, pg_conn):
        assert _logs(app, pg_conn, "owner", {"event_type": "bogus"}).status_code == 400


class TestSummaryFailure:
    def test_page_survives_a_failed_trace_lookup(self, app, pg_conn):
        from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

        UserLogsRepository(pg_conn).insert(
            user_id="owner",
            endpoint="stream_answer",
            data={"question": "q", "request_id": "req-1"},
        )
        with patch(
            "docsgpt.api.user.analytics.routes.RequestTracesRepository.summaries_for_refs",
            side_effect=RuntimeError("statement timeout"),
        ):
            response = _logs(app, pg_conn, "owner", {})
        assert response.status_code == 200
        (row,) = response.json["logs"]
        assert "trace" not in row
