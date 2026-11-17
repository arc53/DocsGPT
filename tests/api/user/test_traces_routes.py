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


class TestFailedChatTurns:
    def _failed_turn(self, pg_conn, *, with_trace):
        from docsgpt.storage.db.repositories.stack_logs import StackLogsRepository
        from docsgpt.storage.db.repositories.user_logs import UserLogsRepository

        StackLogsRepository(pg_conn).insert(
            activity_id="act-chat", endpoint="stream", level="error", user_id="owner", query="q"
        )
        UserLogsRepository(pg_conn).insert(
            user_id="owner",
            endpoint="stream_answer",
            data={
                "question": "q",
                "level": "error",
                "error": "RuntimeError: upstream down",
                "request_id": "req-f",
            },
        )
        if with_trace:
            _trace(pg_conn, request_id="req-f", activity_id="act-chat", status="error")

    def test_failed_turn_is_one_chat_row_not_also_a_system_row(self, app, pg_conn):
        self._failed_turn(pg_conn, with_trace=True)
        rows = _logs(app, pg_conn, "owner", {}).json["logs"]
        assert [r["event_type"] for r in rows] == ["chat"]
        assert rows[0]["level"] == "error"
        assert rows[0]["error"] == "RuntimeError: upstream down"
        assert rows[0]["trace"]["status"] == "error"

    def test_untraced_failures_keep_their_system_row(self, app, pg_conn):
        """Rows from before traces (or with tracing off) have nothing to dedupe against."""
        self._failed_turn(pg_conn, with_trace=False)
        rows = _logs(app, pg_conn, "owner", {}).json["logs"]
        assert sorted(r["event_type"] for r in rows) == ["chat", "system"]


class TestGetTracesExMember:
    """A trace of a team's chat, agent or workflow run is the team's: an ex-member who kept its id reads nothing."""

    MEMBER = "tr-vera"

    def _team(self, pg_conn) -> str:
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        team = TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "tr-alice")
        tid = str(team["id"])
        TeamMembersRepository(pg_conn).add_member(tid, "tr-alice", role="team_admin")
        TeamMembersRepository(pg_conn).add_member(tid, self.MEMBER, role="team_editor")
        return tid

    def _link(self, pg_conn, kind: str, owner: str, team_id) -> dict:
        """The trace columns that tie a trace to ``owner``'s workspace through ``kind``."""
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository
        from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
        from docsgpt.storage.db.repositories.workflows import WorkflowsRepository

        if kind == "agent":
            agent = AgentsRepository(pg_conn).create(owner, "bot", "published", key=f"k-{uuid.uuid4()}")
            return {"agent_id": str(agent["id"])}
        if kind == "conversation":
            chat = ConversationsRepository(pg_conn).create(self.MEMBER, "chat", team_id=team_id)
            return {"conversation_id": str(chat["id"])}
        workflow = WorkflowsRepository(pg_conn).create(owner, "flow")
        run = WorkflowRunsRepository(pg_conn).create(str(workflow["id"]), self.MEMBER, "completed", inputs={})
        return {"workflow_run_id": str(run["id"])}

    @pytest.mark.parametrize("kind", ["agent", "conversation", "workflow_run"])
    def test_leaving_the_team_hides_its_trace_and_rejoining_shows_it(self, app, pg_conn, kind):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.workspaces.principal import principal_id

        tid = self._team(pg_conn)
        record = _trace(pg_conn, user_id=self.MEMBER, request_id="req-team",
                        **self._link(pg_conn, kind, principal_id(tid), tid))

        def _read() -> list:
            response = _get(app, pg_conn, self.MEMBER, {"id": record["id"]})
            assert response.status_code == 200
            return response.json["traces"]

        assert [t["id"] for t in _read()] == [record["id"]]
        TeamMembersRepository(pg_conn).remove_member(tid, self.MEMBER)
        assert _read() == []
        assert _get(app, pg_conn, self.MEMBER, {"request_id": "req-team"}).json["traces"] == []
        if kind == "agent":
            scoped = _get(app, pg_conn, self.MEMBER, {"id": record["id"], "api_key_id": record["agent_id"]})
            assert scoped.status_code == 403 or scoped.json["traces"] == []
        TeamMembersRepository(pg_conn).add_member(tid, self.MEMBER, role="team_viewer")
        assert [t["id"] for t in _read()] == [record["id"]]

    @pytest.mark.parametrize("kind", ["agent", "conversation", "workflow_run"])
    def test_a_personal_trace_stays_after_leaving_a_team(self, app, pg_conn, kind):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository

        tid = self._team(pg_conn)
        record = _trace(pg_conn, user_id=self.MEMBER, **self._link(pg_conn, kind, self.MEMBER, None))
        TeamMembersRepository(pg_conn).remove_member(tid, self.MEMBER)

        assert [t["id"] for t in _get(app, pg_conn, self.MEMBER, {"id": record["id"]}).json["traces"]] == [
            record["id"]
        ]


class TestChatTracesFollowTheChat:
    """A trace tied to a chat follows that chat's workspace, whoever owns the agent it ran."""

    def _team_agent(self, pg_conn, member=None):
        from docsgpt.storage.db.repositories.agents import AgentsRepository
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository
        from docsgpt.workspaces.principal import principal_id

        tid = str(TeamsRepository(pg_conn).create("Ops", f"ops-{uuid.uuid4().hex[:6]}", "tc-alice")["id"])
        TeamMembersRepository(pg_conn).add_member(tid, "tc-alice", role="team_admin")
        if member:
            TeamMembersRepository(pg_conn).add_member(tid, member, role="team_editor")
        agent = AgentsRepository(pg_conn).create(principal_id(tid), "bot", "published", key=f"k-{uuid.uuid4()}")
        return tid, str(agent["id"])

    def _chat_trace(self, pg_conn, user, agent_id, team_id):
        from docsgpt.storage.db.repositories.conversations import ConversationsRepository

        chat = ConversationsRepository(pg_conn).create(user, "chat", agent_id=agent_id, team_id=team_id)
        return _trace(pg_conn, user_id=user, agent_id=agent_id, conversation_id=str(chat["id"]))

    def _ids(self, app, pg_conn, user, record):
        return [t["id"] for t in _get(app, pg_conn, user, {"id": record["id"]}).json["traces"]]

    def test_an_outsiders_own_chat_with_a_team_agent_keeps_its_trace(self, app, pg_conn):
        _, agent_id = self._team_agent(pg_conn)
        record = self._chat_trace(pg_conn, "tc-outsider", agent_id, None)

        assert self._ids(app, pg_conn, "tc-outsider", record) == [record["id"]]

    def test_a_chat_in_a_team_it_is_shared_with_keeps_its_trace(self, app, pg_conn):
        from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
        from docsgpt.storage.db.repositories.teams import TeamsRepository

        tid, agent_id = self._team_agent(pg_conn)
        other = str(TeamsRepository(pg_conn).create("Sales", f"s-{uuid.uuid4().hex[:6]}", "tc-sam")["id"])
        TeamMembersRepository(pg_conn).add_member(other, "tc-dana", role="team_viewer")
        TeamItemSharesRepository(pg_conn).share(tid, other, "agent", agent_id, "tc-alice")
        record = self._chat_trace(pg_conn, "tc-dana", agent_id, other)

        assert self._ids(app, pg_conn, "tc-dana", record) == [record["id"]]
        TeamMembersRepository(pg_conn).remove_member(other, "tc-dana")
        assert self._ids(app, pg_conn, "tc-dana", record) == []

    def test_a_members_team_chat_trace_still_closes_on_leaving(self, app, pg_conn):
        from docsgpt.storage.db.repositories.team_members import TeamMembersRepository

        tid, agent_id = self._team_agent(pg_conn, member="tc-vera")
        record = self._chat_trace(pg_conn, "tc-vera", agent_id, tid)

        assert self._ids(app, pg_conn, "tc-vera", record) == [record["id"]]
        TeamMembersRepository(pg_conn).remove_member(tid, "tc-vera")
        assert self._ids(app, pg_conn, "tc-vera", record) == []
