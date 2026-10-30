"""Chat rows in the Logs timeline carry their conversation, passthrough values and feedback.

``/api/get_user_logs`` filters by them too: conversation, passthrough key and
value, feedback and a date range.
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from flask import Flask
from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.user_logs import UserLogsRepository


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _no_webhook_markers():
    with patch("docsgpt.api.user.analytics.routes.list_runs", lambda user_id: []):
        yield


def _call(app, conn, user: str, body: dict):
    from docsgpt.api.user.analytics.routes import GetUserLogs

    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.user.analytics.routes.db_readonly", _yield), app.test_request_context(
        "/api/get_user_logs", method="POST", json=body
    ):
        from flask import request

        request.decoded_token = {"sub": user}
        return GetUserLogs().post()


def _logs(app, conn, user: str, body: dict | None = None) -> list[dict]:
    response = _call(app, conn, user, body or {})
    assert response.status_code == 200, response.json
    return response.json["logs"]


def _agent(conn, owner: str = "owner") -> dict:
    return AgentsRepository(conn).create(owner, "Support bot", "published", key=f"k-{uuid.uuid4()}")


def _turn(
    conn,
    agent: dict,
    question: str,
    *,
    passthrough: dict | None = None,
    feedback: str | None = None,
    store_conversation_id: bool = True,
    at: dt.datetime | None = None,
    conversation_id: str | None = None,
) -> str:
    """One finished widget turn: its message and its Logs row. Returns the conversation id."""
    repo = ConversationsRepository(conn)
    if conversation_id is None:
        conversation_id = str(
            repo.create(
                agent["user_id"],
                question,
                agent_id=str(agent["id"]),
                api_key=agent["key"],
                visibility="hidden",
                passthrough=passthrough,
            )["id"]
        )
    message = repo.reserve_message(conversation_id, prompt=question, placeholder_response="", status="complete")
    if feedback:
        repo.set_feedback(conversation_id, message["position"], {"text": feedback, "timestamp": "2026-10-01T00:00:00"})
    data = {
        "action": "stream_answer",
        "level": "info",
        "user": agent["user_id"],
        "api_key": agent["key"],
        "agent_id": str(agent["id"]),
        "question": question,
        "response": "answer",
        "message_id": str(message["id"]),
    }
    if store_conversation_id:
        data["conversation_id"] = conversation_id
    if passthrough:
        data["passthrough"] = passthrough
    UserLogsRepository(conn).insert(user_id=agent["user_id"], endpoint="stream_answer", data=data, timestamp=at)
    return conversation_id


def _questions(logs: list[dict]) -> list[str]:
    return sorted(row["question"] for row in logs)


class TestChatRowFields:
    def test_a_row_carries_its_conversation_values_and_feedback(self, app, pg_conn):
        agent = _agent(pg_conn)
        conversation_id = _turn(pg_conn, agent, "Reset my password", passthrough={"user_id": "emp-42"}, feedback="dislike")

        (row,) = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"])})
        assert row["conversation_id"] == conversation_id
        assert row["passthrough"] == {"user_id": "emp-42"}
        assert row["feedback"]["text"] == "dislike"

    def test_an_older_row_gets_its_conversation_from_its_message(self, app, pg_conn):
        agent = _agent(pg_conn)
        conversation_id = _turn(pg_conn, agent, "Old turn", store_conversation_id=False)

        (row,) = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"])})
        assert row["conversation_id"] == conversation_id
        assert "feedback" not in row

    def test_a_running_answer_carries_the_conversations_values(self, app, pg_conn):
        agent = _agent(pg_conn)
        repo = ConversationsRepository(pg_conn)
        conv = repo.create("owner", "Live", agent_id=str(agent["id"]), visibility="hidden", passthrough={"user_id": "emp-7"})
        repo.reserve_message(str(conv["id"]), prompt="Still answering", placeholder_response="", status="streaming")

        (row,) = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"])})
        assert row["running"] is True
        assert row["passthrough"] == {"user_id": "emp-7"}


class TestFilters:
    def test_by_passthrough_value(self, app, pg_conn):
        agent = _agent(pg_conn)
        _turn(pg_conn, agent, "From 42", passthrough={"user_id": "emp-42"})
        _turn(pg_conn, agent, "From 7", passthrough={"user_id": "emp-7"})
        _turn(pg_conn, agent, "Anonymous")

        logs = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"]), "passthrough": {"user_id": "emp-42"}})
        assert _questions(logs) == ["From 42"]

    def test_passthrough_values_compare_as_text(self, app, pg_conn):
        agent = _agent(pg_conn)
        _turn(pg_conn, agent, "Numeric id", passthrough={"user_id": 42, "beta": True})

        assert _questions(_logs(app, pg_conn, "owner", {"passthrough": {"user_id": "42"}})) == ["Numeric id"]
        assert _questions(_logs(app, pg_conn, "owner", {"passthrough": {"user_id": 42, "beta": True}})) == [
            "Numeric id"
        ]
        assert _logs(app, pg_conn, "owner", {"passthrough": {"beta": "false"}}) == []

    def test_by_conversation(self, app, pg_conn):
        agent = _agent(pg_conn)
        conversation_id = _turn(pg_conn, agent, "First")
        _turn(pg_conn, agent, "Second", conversation_id=conversation_id, store_conversation_id=False)
        _turn(pg_conn, agent, "Elsewhere")

        logs = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"]), "conversation_id": conversation_id})
        assert _questions(logs) == ["First", "Second"]

    def test_by_feedback(self, app, pg_conn):
        agent = _agent(pg_conn)
        _turn(pg_conn, agent, "Liked", feedback="like")
        _turn(pg_conn, agent, "Disliked", feedback="dislike")
        _turn(pg_conn, agent, "Unrated")

        logs = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"]), "feedback": "dislike"})
        assert _questions(logs) == ["Disliked"]

    def test_by_date_range(self, app, pg_conn):
        agent = _agent(pg_conn)
        now = dt.datetime.now(dt.timezone.utc)
        _turn(pg_conn, agent, "Last week", at=now - dt.timedelta(days=7))
        _turn(pg_conn, agent, "Yesterday", at=now - dt.timedelta(days=1))
        _turn(pg_conn, agent, "Now", at=now)

        logs = _logs(
            app,
            pg_conn,
            "owner",
            {
                "api_key_id": str(agent["id"]),
                "date_from": (now - dt.timedelta(days=2)).isoformat(),
                "date_to": (now - dt.timedelta(hours=1)).isoformat(),
            },
        )
        assert _questions(logs) == ["Yesterday"]

    def test_row_filters_leave_out_events_without_that_field(self, app, pg_conn):
        agent = _agent(pg_conn)
        _turn(pg_conn, agent, "Chat", passthrough={"user_id": "emp-42"})
        pg_conn.execute(
            text(
                "INSERT INTO stack_logs (activity_id, endpoint, level, user_id, agent_id, query) "
                "VALUES ('a1', 'stream', 'error', 'owner', CAST(:agent AS uuid), 'boom')"
            ),
            {"agent": str(agent["id"])},
        )

        assert len(_logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"])})) == 2
        logs = _logs(app, pg_conn, "owner", {"api_key_id": str(agent["id"]), "passthrough": {"user_id": "emp-42"}})
        assert [row["event_type"] for row in logs] == ["chat"]

    @pytest.mark.parametrize(
        "body",
        [
            {"conversation_id": "not-a-uuid"},
            {"feedback": "meh"},
            {"passthrough": ["user_id"]},
            {"passthrough": {"user_id": {"nested": 1}}},
            {"passthrough": {f"k{i}": "v" for i in range(9)}},
            {"date_from": "yesterday"},
        ],
    )
    def test_bad_filters_are_rejected(self, app, pg_conn, body):
        response = _call(app, pg_conn, "owner", body)
        assert response.status_code == 400
        assert response.json["success"] is False
