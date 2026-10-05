"""Tests for RequestTracesRepository against a real Postgres instance."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import text

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.request_traces import RequestTracesRepository


def _record(**overrides):
    base = {
        "id": str(uuid.uuid4()),
        "request_id": "req-1",
        "message_id": None,
        "conversation_id": None,
        "activity_id": None,
        "workflow_run_id": None,
        "user_id": "u1",
        "agent_id": None,
        "source": "stream",
        "name": "stream",
        "status": "ok",
        "started_at_ns": time.time_ns(),
        "duration_ms": 1234,
        "span_count": 1,
        "dropped_spans": 0,
        "summary": {"llm_calls": 1},
        "spans": [
            {
                "id": "s1",
                "parent_id": None,
                "kind": "llm",
                "name": "chat m",
                "status": "ok",
                "offset_ms": 1.0,
                "duration_ms": 10.0,
                "attributes": {"gen_ai.request.model": "m"},
            }
        ],
        "otel_trace_id": None,
    }
    base.update(overrides)
    return base


def _message(pg_conn, user_id="u1"):
    convs = ConversationsRepository(pg_conn)
    conv = convs.create(user_id, "t")
    msg = convs.reserve_message(
        str(conv["id"]), prompt="q", placeholder_response="..."
    )
    return str(conv["id"]), str(msg["id"])


class TestInsert:
    def test_round_trip(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        record = _record()
        assert repo.insert(record) is True
        rows = repo.list_by_ref("request_id", "req-1", user_id="u1")
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == record["id"]
        assert row["duration_ms"] == 1234
        assert row["summary"] == {"llm_calls": 1}
        assert row["spans"][0]["attributes"]["gen_ai.request.model"] == "m"

    def test_strips_nul_bytes(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        record = _record(
            spans=[{"id": "s", "name": "a\x00b", "preview": {"result": "x\x00y"}}]
        )
        assert repo.insert(record)
        row = repo.list_by_ref("id", record["id"], user_id="u1")[0]
        assert row["spans"][0]["name"] == "ab"
        assert row["spans"][0]["preview"]["result"] == "xy"

    def test_non_uuid_link_ids_become_null(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        record = _record(agent_id="not-a-uuid", conversation_id="nope")
        assert repo.insert(record)
        row = repo.list_by_ref("id", record["id"], user_id="u1")[0]
        assert row["agent_id"] is None
        assert row["conversation_id"] is None

    def test_missing_message_drops_row_and_keeps_transaction_usable(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        assert repo.insert(_record(message_id=str(uuid.uuid4()))) is False
        # The savepoint rolled back; the outer transaction still works.
        assert repo.insert(_record(request_id="req-after")) is True

    def test_duplicate_id_is_ignored(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        record = _record()
        assert repo.insert(record) is True
        assert repo.insert(record) is False


class TestScoping:
    def test_other_users_cannot_read(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        repo.insert(_record())
        assert repo.list_by_ref("request_id", "req-1", user_id="u2") == []

    def test_agent_scope_returns_agent_traces_from_any_user(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        agent_id = str(uuid.uuid4())
        repo.insert(_record(user_id="someone-else", agent_id=agent_id))
        rows = repo.list_by_ref("request_id", "req-1", user_id="owner", agent_id=agent_id)
        assert len(rows) == 1

    def test_unknown_field_and_bad_uuid_return_empty(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        repo.insert(_record())
        assert repo.list_by_ref("user_id", "u1", user_id="u1") == []
        assert repo.list_by_ref("message_id", "not-uuid", user_id="u1") == []
        assert repo.list_by_ref("request_id", "req-1", user_id=None) == []


class TestMessageLink:
    def test_rounds_for_a_message_are_ordered(self, pg_conn):
        conv_id, msg_id = _message(pg_conn)
        repo = RequestTracesRepository(pg_conn)
        first = _record(message_id=msg_id, status="paused", started_at_ns=time.time_ns())
        second = _record(message_id=msg_id, started_at_ns=time.time_ns() + 1_000_000)
        repo.insert(second)
        repo.insert(first)
        rows = repo.list_by_ref("message_id", msg_id, user_id="u1")
        assert [r["id"] for r in rows] == [first["id"], second["id"]]

    def test_deleting_the_conversation_cascades(self, pg_conn):
        conv_id, msg_id = _message(pg_conn)
        repo = RequestTracesRepository(pg_conn)
        repo.insert(_record(message_id=msg_id, conversation_id=conv_id))
        ConversationsRepository(pg_conn).delete(conv_id, "u1")
        count = pg_conn.execute(text("SELECT count(*) FROM request_traces")).scalar()
        assert count == 0


class TestConversationDeletion:
    """Every trace of a conversation goes with it, not only message-linked ones."""

    def test_trace_without_message_is_deleted_with_its_conversation(self, pg_conn):
        conv_id, _msg_id = _message(pg_conn)
        repo = RequestTracesRepository(pg_conn)
        # e.g. a scheduled run in this conversation, or a stateless /v1 round.
        repo.insert(_record(conversation_id=conv_id, source="schedule"))
        repo.insert(_record(request_id="other"))  # another conversation's trace
        ConversationsRepository(pg_conn).delete(conv_id, "u1")
        remaining = pg_conn.execute(text("SELECT request_id FROM request_traces")).scalars().all()
        assert remaining == ["other"]

    def test_delete_all_for_user_removes_their_conversation_traces(self, pg_conn):
        conv_id, _msg_id = _message(pg_conn)
        repo = RequestTracesRepository(pg_conn)
        repo.insert(_record(conversation_id=conv_id))
        ConversationsRepository(pg_conn).delete_all_for_user("u1")
        assert pg_conn.execute(text("SELECT count(*) FROM request_traces")).scalar() == 0


class TestSummaries:
    def test_summaries_grouped_by_field_and_id(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        a = _record(request_id="r-a")
        b = _record(request_id="r-b", activity_id="act-1")
        repo.insert(a)
        repo.insert(b)
        out = repo.summaries_for_refs(
            {"request_id": ["r-a", "r-b", "r-missing"], "activity_id": ["act-1"]},
            user_id="u1",
        )
        assert set(out["request_id"]) == {"r-a", "r-b"}
        assert out["activity_id"]["act-1"][0]["id"] == b["id"]
        assert "spans" not in out["request_id"]["r-a"][0]

    def test_summaries_are_scoped(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        repo.insert(_record(request_id="r-a"))
        assert repo.summaries_for_refs({"request_id": ["r-a"]}, user_id="u2") == {}


class TestPurge:
    def test_purge_older_than(self, pg_conn):
        repo = RequestTracesRepository(pg_conn)
        old = _record(request_id="old")
        repo.insert(old)
        repo.insert(_record(request_id="new"))
        pg_conn.execute(
            text(
                "UPDATE request_traces SET created_at = now() - interval '40 days' "
                "WHERE request_id = 'old'"
            )
        )
        assert repo.purge_older_than(30) == 1
        assert repo.list_by_ref("request_id", "old", user_id="u1") == []
        assert len(repo.list_by_ref("request_id", "new", user_id="u1")) == 1
