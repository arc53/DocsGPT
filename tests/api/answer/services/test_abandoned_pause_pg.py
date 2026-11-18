"""A turn paused for approval that the user walks away from is finalized, never left streaming."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from sqlalchemy import text

from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.message_events import MessageEventsRepository
from docsgpt.storage.db.repositories.pending_tool_state import PendingToolStateRepository
from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository

USER = "u-abandon"

COMPLETED = [
    {
        "tool_name": "monitor",
        "call_id": f"call-{n}",
        "action_name": "monitor_create",
        "arguments": {"description": f"link {n}"},
        "result": f'{{"monitor_id": "m-{n}"}}',
        "status": "completed",
    }
    for n in range(1, 5)
]

PENDING = {
    "call_id": "call-5",
    "name": "run_command",
    "llm_name": "run_command",
    "tool_name": "remote_device",
    "tool_id": "t-dev",
    "action_name": "run_command",
    "arguments": {"command": "echo {{link_secret:X3SWZB}} > ~/secret"},
    "pause_type": "awaiting_approval",
    "device_id": "dev-1",
    "secret_refs": ["X3SWZB"],
}


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    with patch("docsgpt.api.answer.services.continuation_service.db_readonly", _yield), patch(
        "docsgpt.api.answer.services.continuation_service.db_session", _yield
    ):
        yield


@pytest.fixture()
def published():
    events: List[tuple] = []
    with patch(
        "docsgpt.events.publisher.publish_user_event",
        side_effect=lambda user, kind, payload, scope=None: events.append((user, kind, payload, scope)),
    ):
        yield events


@pytest.fixture(autouse=True)
def _no_exposed_secrets():
    with patch("docsgpt.monitors.secret_refs.exposed_values", return_value={}):
        yield


def _paused_turn(conn, *, prior=None, pending=None, answer="I'll set this up as a signed webhook.") -> Dict[str, str]:
    """A conversation whose last turn ran four calls and paused on a fifth."""
    conversations = ConversationsRepository(conn)
    conv = conversations.create(USER, name="paused")
    conv_id = str(conv["id"])
    row = conversations.reserve_message(
        conv_id, prompt="Create a webhook link", placeholder_response="Response was terminated", status="streaming"
    )
    message_id = str(row["id"])
    journal = MessageEventsRepository(conn)
    seq = 0
    journal.record(message_id, seq, "message_id", {"type": "message_id", "message_id": message_id})
    seq += 1
    if answer:
        journal.record(message_id, seq, "answer", {"type": "answer", "answer": answer})
        seq += 1
    attempts = ToolCallAttemptsRepository(conn)
    for call in COMPLETED:
        journal.record(message_id, seq, "tool_call", {"type": "tool_call", "data": {**call, "status": "pending"}})
        journal.record(message_id, seq + 1, "tool_call", {"type": "tool_call", "data": call})
        seq += 2
        attempts.upsert_executed(
            call["call_id"], "monitor", "monitor_create", call["arguments"], call["result"],
            message_id=message_id, user_id=USER,
        )
    pending_calls = [PENDING] if pending is None else pending
    for call in pending_calls:
        journal.record(
            message_id, seq, "tool_call",
            {"type": "tool_call", "data": {**call, "status": call["pause_type"]}},
        )
        seq += 1
    PendingToolStateRepository(conn).save_state(
        conv_id,
        USER,
        messages=[{"role": "user", "content": "Create a webhook link"}],
        pending_tool_calls=pending_calls,
        tools_dict={},
        tool_schemas=[],
        agent_config={
            "reserved_message_id": message_id,
            "request_id": "req-1",
            "prior_tool_calls": COMPLETED if prior is None else prior,
        },
    )
    return {"conversation_id": conv_id, "message_id": message_id}


def _message(conn, message_id: str) -> Dict[str, Any]:
    row = conn.execute(
        text("SELECT * FROM conversation_messages WHERE id = CAST(:id AS uuid)"), {"id": message_id}
    ).fetchone()
    return dict(row._mapping)


def _attempt_statuses(conn, message_id: str) -> List[str]:
    rows = conn.execute(
        text("SELECT status FROM tool_call_attempts WHERE message_id = CAST(:id AS uuid) ORDER BY call_id"),
        {"id": message_id},
    ).fetchall()
    return [r.status for r in rows]


class TestANewTurnFinalizesTheAbandonedPause:
    def test_the_paused_message_is_complete_with_every_call_in_order(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        with _patch_db(pg_conn):
            retired = ContinuationService().abandon_pending(turn["conversation_id"], USER)

        assert retired is not None
        message = _message(pg_conn, turn["message_id"])
        assert message["status"] == "complete"
        assert message["response"] == "I'll set this up as a signed webhook."
        calls = message["tool_calls"]
        assert [c["call_id"] for c in calls] == ["call-1", "call-2", "call-3", "call-4", "call-5"]
        assert [c["status"] for c in calls[:4]] == ["completed"] * 4
        assert calls[0]["result"] == '{"monitor_id": "m-1"}'
        assert message["message_metadata"]["pause_retired"] == "moved_on"
        # The order it streamed in survives, so a reload shows the cards where they were.
        segments = message["message_metadata"]["segments"]
        assert segments[0]["kind"] == "text"
        assert [s["call_id"] for s in segments if s["kind"] == "tool"] == [
            "call-1", "call-2", "call-3", "call-4", "call-5",
        ]

    def test_the_pending_call_is_recorded_as_not_run(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        not_run = _message(pg_conn, turn["message_id"])["tool_calls"][-1]
        assert not_run["status"] == "denied"
        assert not_run["not_run"] == "moved_on"
        assert not_run["tool_name"] == "remote_device"
        assert not_run["action_name"] == "run_command"
        assert not_run["device_id"] == "dev-1"
        # Still the reference, never a value.
        assert not_run["arguments"] == {"command": "echo {{link_secret:X3SWZB}} > ~/secret"}
        assert not_run["result"].startswith("Not run:")
        assert "moved on" in not_run["result"]
        # Never journaled as a run.
        row = pg_conn.execute(
            text("SELECT 1 FROM tool_call_attempts WHERE call_id = 'call-5'")
        ).fetchone()
        assert row is None

    def test_the_completed_calls_are_confirmed(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        assert _attempt_statuses(pg_conn, turn["message_id"]) == ["confirmed"] * 4

    def test_the_pending_state_is_gone_and_other_tabs_are_told(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        assert PendingToolStateRepository(pg_conn).load_state_any(turn["conversation_id"], USER) is None
        assert published == [
            (
                USER,
                "tool.approval.cleared",
                {
                    "conversation_id": turn["conversation_id"],
                    "message_id": turn["message_id"],
                    "reason": "moved_on",
                },
                {"kind": "conversation", "id": turn["conversation_id"]},
            )
        ]

    def test_a_client_side_pause_is_recorded_as_not_run_too(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        client_call = {
            "call_id": "call-c",
            "name": "get_weather",
            "llm_name": "get_weather",
            "tool_name": "get_weather",
            "action_name": "get_weather",
            "arguments": {"city": "Kyiv"},
            "pause_type": "requires_client_execution",
        }
        turn = _paused_turn(pg_conn, pending=[client_call])
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        not_run = _message(pg_conn, turn["message_id"])["tool_calls"][-1]
        assert not_run["call_id"] == "call-c"
        assert not_run["status"] == "denied"
        assert not_run["result"].startswith("Not run:")

    def test_an_expired_pause_says_it_expired(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state SET expires_at = clock_timestamp() - interval '1 second' "
                "WHERE conversation_id = CAST(:c AS uuid)"
            ),
            {"c": turn["conversation_id"]},
        )
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        message = _message(pg_conn, turn["message_id"])
        assert message["status"] == "complete"
        assert message["tool_calls"][-1]["not_run"] == "expired"
        assert "expired" in message["tool_calls"][-1]["result"]
        assert published[0][2]["reason"] == "expired"

    def test_a_secret_shown_to_the_assistant_is_stored_as_its_reference(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn, answer="The secret is s3cr3t-value.")
        with _patch_db(pg_conn), patch(
            "docsgpt.monitors.secret_refs.exposed_values", return_value={"s3cr3t-value": "{{link_secret:X3SWZB}}"}
        ):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        assert _message(pg_conn, turn["message_id"])["response"] == "The secret is {{link_secret:X3SWZB}}."

    def test_an_older_pause_without_saved_calls_takes_them_from_the_journal(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state SET agent_config = "
                "CAST(json_build_object('reserved_message_id', CAST(:m AS text)) AS json) "
                "WHERE conversation_id = CAST(:c AS uuid)"
            ),
            {"c": turn["conversation_id"], "m": turn["message_id"]},
        )
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        calls = _message(pg_conn, turn["message_id"])["tool_calls"]
        assert [c["call_id"] for c in calls] == ["call-1", "call-2", "call-3", "call-4", "call-5"]
        assert [c["status"] for c in calls] == ["completed"] * 4 + ["denied"]


class TestNothingToAbandon:
    def test_no_pending_state_is_a_no_op(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        conv = ConversationsRepository(pg_conn).create(USER, name="quiet")
        with _patch_db(pg_conn):
            assert ContinuationService().abandon_pending(str(conv["id"]), USER) is None
        assert published == []

    def test_another_users_pause_is_left_alone(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        with _patch_db(pg_conn):
            assert ContinuationService().abandon_pending(turn["conversation_id"], "someone-else") is None
        assert _message(pg_conn, turn["message_id"])["status"] == "streaming"

    def test_a_message_already_terminal_keeps_its_state(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        pg_conn.execute(
            text("UPDATE conversation_messages SET status = 'failed' WHERE id = CAST(:id AS uuid)"),
            {"id": turn["message_id"]},
        )
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        message = _message(pg_conn, turn["message_id"])
        assert message["status"] == "failed"
        assert message["tool_calls"] == []
        assert PendingToolStateRepository(pg_conn).load_state_any(turn["conversation_id"], USER) is None


class TestApprovalRacingTheNewTurn:
    """The approval and the new turn both reach the same row; exactly one wins."""

    def test_an_approval_that_claimed_first_runs_and_nothing_is_abandoned(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        service = ContinuationService()
        with _patch_db(pg_conn):
            assert service.claim_state(turn["conversation_id"], USER) is not None
            published.clear()
            assert service.abandon_pending(turn["conversation_id"], USER) is None

        assert _message(pg_conn, turn["message_id"])["status"] == "streaming"
        assert PendingToolStateRepository(pg_conn).load_state_any(turn["conversation_id"], USER)["status"] == (
            "resuming"
        )
        assert published == []

    def test_a_late_approval_finds_nothing_to_claim(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        service = ContinuationService()
        with _patch_db(pg_conn):
            assert service.abandon_pending(turn["conversation_id"], USER) is not None
            assert service.claim_state(turn["conversation_id"], USER) is None


class TestPendingStateRepository:
    def test_abandon_takes_only_a_pending_row(self, pg_conn):
        turn = _paused_turn(pg_conn)
        repo = PendingToolStateRepository(pg_conn)
        repo.mark_resuming(turn["conversation_id"], USER)

        assert repo.abandon(turn["conversation_id"], USER) is None
        assert repo.load_state_any(turn["conversation_id"], USER) is not None

    def test_abandon_reports_whether_the_row_had_expired(self, pg_conn):
        turn = _paused_turn(pg_conn)
        repo = PendingToolStateRepository(pg_conn)

        row = repo.abandon(turn["conversation_id"], USER)

        assert row is not None
        assert row["expired"] is False
        assert row["agent_config"]["reserved_message_id"] == turn["message_id"]
        assert repo.load_state_any(turn["conversation_id"], USER) is None

    def test_delete_state_for_a_message_spares_a_later_turns_pause(self, pg_conn):
        turn = _paused_turn(pg_conn)
        repo = PendingToolStateRepository(pg_conn)

        assert repo.delete_state(turn["conversation_id"], USER, message_id="00000000-0000-0000-0000-00000000dead") is False
        assert repo.load_state_any(turn["conversation_id"], USER) is not None
        assert repo.delete_state(turn["conversation_id"], USER, message_id=turn["message_id"]) is True

    def test_cleanup_never_reaps_a_resume_in_flight(self, pg_conn):
        turn = _paused_turn(pg_conn)
        repo = PendingToolStateRepository(pg_conn)
        repo.mark_resuming(turn["conversation_id"], USER)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state SET expires_at = clock_timestamp() - interval '1 second' "
                "WHERE conversation_id = CAST(:c AS uuid)"
            ),
            {"c": turn["conversation_id"]},
        )

        assert repo.cleanup_expired() == []
        assert repo.load_state_any(turn["conversation_id"], USER)["status"] == "resuming"

    def test_cleanup_returns_the_calls_it_retires(self, pg_conn):
        turn = _paused_turn(pg_conn)
        repo = PendingToolStateRepository(pg_conn)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state SET expires_at = clock_timestamp() - interval '1 second' "
                "WHERE conversation_id = CAST(:c AS uuid)"
            ),
            {"c": turn["conversation_id"]},
        )

        (row,) = repo.cleanup_expired()

        assert [c["call_id"] for c in row["pending_tool_calls"]] == ["call-5"]
        assert row["agent_config"]["reserved_message_id"] == turn["message_id"]


class TestEdges:
    def test_a_decision_for_calls_another_pause_has_is_refused_without_taking_it(self, pg_conn, published):
        """A stale tab's decision never takes, resolves or clears the toast of the pause waiting now."""
        from docsgpt.api.answer.services.continuation_service import (
            ContinuationNotPendingError,
            ContinuationService,
        )

        turn = _paused_turn(pg_conn)
        service = ContinuationService()
        with _patch_db(pg_conn):
            with pytest.raises(ContinuationNotPendingError):
                service.claim_state(turn["conversation_id"], USER, call_ids=["call-from-an-older-pause"])
            assert published == []
            assert service.claim_state(turn["conversation_id"], USER, call_ids=["call-5"]) is not None

    def test_nothing_to_retire_without_a_conversation_or_user(self, pg_conn):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        with _patch_db(pg_conn):
            assert ContinuationService().abandon_pending("", USER) is None
            assert ContinuationService().abandon_pending("conv", "") is None
            assert ContinuationService().abandon_pending("not-a-conversation-id", USER) is None

    def test_a_backfilled_legacy_id_finds_the_pause(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        legacy = "507f1f77bcf86cd799439aaa"
        turn = _paused_turn(pg_conn)
        pg_conn.execute(
            text("UPDATE conversations SET legacy_mongo_id = :l WHERE id = CAST(:c AS uuid)"),
            {"l": legacy, "c": turn["conversation_id"]},
        )
        with _patch_db(pg_conn):
            assert ContinuationService().abandon_pending(legacy, USER) is not None
        assert _message(pg_conn, turn["message_id"])["status"] == "complete"

    def test_a_pause_without_a_message_only_retires_its_state(self, pg_conn):
        from docsgpt.api.answer.services.continuation_service import retire_paused_message

        assert retire_paused_message(pg_conn, {"agent_config": {}, "pending_tool_calls": []}, "moved_on") is None

    def test_the_turns_sources_are_kept_trimmed(self, pg_conn, published):
        from docsgpt.api.answer.services.continuation_service import ContinuationService

        turn = _paused_turn(pg_conn)
        pg_conn.execute(
            text(
                "UPDATE pending_tool_state SET agent_config = CAST(:cfg AS json) "
                "WHERE conversation_id = CAST(:c AS uuid)"
            ),
            {
                "c": turn["conversation_id"],
                "cfg": json.dumps(
                    {
                        "reserved_message_id": turn["message_id"],
                        "prior_tool_calls": COMPLETED,
                        "retrieved_docs": [{"title": "Guide", "text": "x" * 5000}],
                    }
                ),
            },
        )
        with _patch_db(pg_conn):
            ContinuationService().abandon_pending(turn["conversation_id"], USER)

        (source,) = _message(pg_conn, turn["message_id"])["sources"]
        assert source["title"] == "Guide"
        assert len(source["text"]) == 1000
