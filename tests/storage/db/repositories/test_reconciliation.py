"""Tests for ReconciliationRepository against a real Postgres instance."""

from __future__ import annotations

import json

from sqlalchemy import text

from application.storage.db.repositories.conversations import (
    ConversationsRepository,
)
from application.storage.db.repositories.reconciliation import (
    ReconciliationRepository,
)


def _seed_message(
    conn, *, status: str = "pending", age_minutes: int = 6, user_id: str = "u",
) -> dict:
    conv = ConversationsRepository(conn).create(user_id, "rec repo test")
    row = conn.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, position, prompt, response, status, user_id, timestamp
            )
            VALUES (
                CAST(:cid AS uuid), 0, 'p', '', :status, :uid,
                clock_timestamp() - make_interval(mins => :age)
            )
            RETURNING id
            """
        ),
        {"cid": conv["id"], "status": status, "uid": user_id, "age": age_minutes},
    ).fetchone()
    return {"id": str(row[0]), "conversation_id": conv["id"], "user_id": user_id}


def _seed_resuming(conn, conv_id: str, user_id: str, *, secs_ago: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO pending_tool_state (
                conversation_id, user_id, messages, pending_tool_calls,
                tools_dict, tool_schemas, agent_config,
                created_at, expires_at, status, resumed_at
            )
            VALUES (
                CAST(:cid AS uuid), :uid,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                clock_timestamp(),
                clock_timestamp() + interval '30 minutes',
                'resuming',
                clock_timestamp() - make_interval(secs => :secs)
            )
            """
        ),
        {"cid": conv_id, "uid": user_id, "secs": secs_ago},
    )


def _seed_pending_state(
    conn, conv_id: str, user_id: str, *, expires_in_minutes: int = 30,
) -> None:
    """Insert a paused ``pending_tool_state`` row (status='pending')."""
    conn.execute(
        text(
            """
            INSERT INTO pending_tool_state (
                conversation_id, user_id, messages, pending_tool_calls,
                tools_dict, tool_schemas, agent_config,
                created_at, expires_at, status, resumed_at
            )
            VALUES (
                CAST(:cid AS uuid), :uid,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                clock_timestamp(),
                clock_timestamp() + make_interval(mins => :exp),
                'pending',
                NULL
            )
            """
        ),
        {"cid": conv_id, "uid": user_id, "exp": expires_in_minutes},
    )


def _seed_tool_call(
    conn,
    *,
    call_id: str,
    status: str,
    age_minutes: int,
    tool_name: str = "notes",
    action_name: str = "view",
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO tool_call_attempts (
                call_id, tool_name, action_name, arguments, status
            )
            VALUES (:cid, :tn, :an, CAST(:args AS jsonb), :st)
            """
        ),
        {
            "cid": call_id,
            "tn": tool_name,
            "an": action_name,
            "args": json.dumps({}),
            "st": status,
        },
    )
    # The ``set_updated_at`` BEFORE-UPDATE trigger would otherwise reset
    # ``updated_at`` to ``now()`` and defeat the backdate. Temporarily
    # disable user triggers on this row so the seed lands as written.
    conn.execute(text("ALTER TABLE tool_call_attempts DISABLE TRIGGER USER"))
    try:
        conn.execute(
            text(
                """
                UPDATE tool_call_attempts
                SET attempted_at = clock_timestamp() - make_interval(mins => :age),
                    updated_at = clock_timestamp() - make_interval(mins => :age)
                WHERE call_id = :cid
                """
            ),
            {"cid": call_id, "age": age_minutes},
        )
    finally:
        conn.execute(text("ALTER TABLE tool_call_attempts ENABLE TRIGGER USER"))


class TestFindAndLockStuckMessages:
    def test_returns_stuck_pending(self, pg_conn):
        msg = _seed_message(pg_conn, status="pending", age_minutes=6)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg["id"] for r in rows)

    def test_returns_stuck_streaming(self, pg_conn):
        msg = _seed_message(pg_conn, status="streaming", age_minutes=6)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg["id"] for r in rows)

    def test_excludes_terminal_status(self, pg_conn):
        msg = _seed_message(pg_conn, status="complete", age_minutes=10)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg["id"] for r in rows)

    def test_excludes_under_age_threshold(self, pg_conn):
        msg = _seed_message(pg_conn, age_minutes=2)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg["id"] for r in rows)

    def test_skipped_when_resuming_within_grace(self, pg_conn):
        msg = _seed_message(pg_conn)
        _seed_resuming(pg_conn, msg["conversation_id"], msg["user_id"], secs_ago=60)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg["id"] for r in rows)

    def test_not_skipped_when_resuming_past_grace(self, pg_conn):
        msg = _seed_message(pg_conn)
        _seed_resuming(
            pg_conn, msg["conversation_id"], msg["user_id"],
            secs_ago=11 * 60,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg["id"] for r in rows)

    def test_skipped_when_pending_state_active(self, pg_conn):
        """Paused row (PT.status='pending') with future expires_at exempts the message."""
        msg = _seed_message(pg_conn)
        _seed_pending_state(
            pg_conn, msg["conversation_id"], msg["user_id"],
            expires_in_minutes=30,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg["id"] for r in rows)

    def test_not_skipped_when_pending_state_expired(self, pg_conn):
        """An expired PT row (expires_at <= now()) no longer shields the message."""
        msg = _seed_message(pg_conn)
        _seed_pending_state(
            pg_conn, msg["conversation_id"], msg["user_id"],
            expires_in_minutes=-1,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg["id"] for r in rows)

    def test_recent_heartbeat_keeps_long_stream_alive(self, pg_conn):
        """A stale ``timestamp`` plus fresh heartbeat in metadata excludes the row."""
        # 20-min-old creation simulates a long-running agent stream;
        # metadata.last_heartbeat_at at 30s ago is the route heartbeat.
        conv = ConversationsRepository(pg_conn).create("u", "heartbeat test")
        row = pg_conn.execute(
            text(
                """
                INSERT INTO conversation_messages (
                    conversation_id, position, prompt, response, status,
                    user_id, timestamp, message_metadata
                )
                VALUES (
                    CAST(:cid AS uuid), 0, 'p', '', 'streaming', 'u',
                    clock_timestamp() - make_interval(mins => 20),
                    jsonb_build_object(
                        'last_heartbeat_at',
                        to_jsonb(clock_timestamp() - make_interval(secs => 30))
                    )
                )
                RETURNING id
                """
            ),
            {"cid": conv["id"]},
        ).fetchone()
        msg_id = str(row[0])
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert all(str(r["id"]) != msg_id for r in rows)

    def test_stale_heartbeat_does_not_keep_message_alive(self, pg_conn):
        """A heartbeat older than the threshold doesn't shield the row."""
        conv = ConversationsRepository(pg_conn).create("u", "stale heartbeat test")
        row = pg_conn.execute(
            text(
                """
                INSERT INTO conversation_messages (
                    conversation_id, position, prompt, response, status,
                    user_id, timestamp, message_metadata
                )
                VALUES (
                    CAST(:cid AS uuid), 0, 'p', '', 'streaming', 'u',
                    clock_timestamp() - make_interval(mins => 20),
                    jsonb_build_object(
                        'last_heartbeat_at',
                        to_jsonb(clock_timestamp() - make_interval(mins => 10))
                    )
                )
                RETURNING id
                """
            ),
            {"cid": conv["id"]},
        ).fetchone()
        msg_id = str(row[0])
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_stuck_messages()
        assert any(str(r["id"]) == msg_id for r in rows)


class TestFindAndLockProposedToolCalls:
    def test_returns_stuck_proposed(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="p-1", status="proposed", age_minutes=6)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_proposed_tool_calls()
        assert any(r["call_id"] == "p-1" for r in rows)

    def test_excludes_under_age(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="p-2", status="proposed", age_minutes=2)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_proposed_tool_calls()
        assert all(r["call_id"] != "p-2" for r in rows)

    def test_excludes_other_status(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="p-3", status="executed", age_minutes=20)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_proposed_tool_calls()
        assert all(r["call_id"] != "p-3" for r in rows)


class TestFindAndLockExecutedToolCalls:
    def test_returns_stuck_executed(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="e-1", status="executed", age_minutes=16)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_executed_tool_calls()
        assert any(r["call_id"] == "e-1" for r in rows)

    def test_excludes_under_age(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="e-2", status="executed", age_minutes=5)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_executed_tool_calls()
        assert all(r["call_id"] != "e-2" for r in rows)

    def test_excludes_other_status(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="e-3", status="confirmed", age_minutes=20)
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_and_lock_executed_tool_calls()
        assert all(r["call_id"] != "e-3" for r in rows)


class TestIncrementMessageReconcileAttempts:
    def test_starts_at_one_then_two(self, pg_conn):
        msg = _seed_message(pg_conn)
        repo = ReconciliationRepository(pg_conn)
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 1
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 2
        assert repo.increment_message_reconcile_attempts(msg["id"]) == 3

    def test_zero_for_missing_id(self, pg_conn):
        repo = ReconciliationRepository(pg_conn)
        # Non-existent UUID — UPDATE matches no row, RETURNING is empty.
        assert (
            repo.increment_message_reconcile_attempts(
                "00000000-0000-0000-0000-000000000000",
            )
            == 0
        )


class TestMarkMessageFailed:
    def test_flips_status_and_writes_error(self, pg_conn):
        msg = _seed_message(pg_conn)
        repo = ReconciliationRepository(pg_conn)
        assert repo.mark_message_failed(msg["id"], error="boom") is True
        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata "
                "FROM conversation_messages WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "failed"
        assert row[1]["error"] == "boom"


class TestMarkToolCallFailed:
    def test_flips_to_failed(self, pg_conn):
        _seed_tool_call(pg_conn, call_id="t-1", status="proposed", age_minutes=6)
        repo = ReconciliationRepository(pg_conn)
        assert repo.mark_tool_call_failed("t-1", error="oops") is True
        row = pg_conn.execute(
            text("SELECT status, error FROM tool_call_attempts WHERE call_id = :id"),
            {"id": "t-1"},
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] == "oops"


def _seed_stuck_idempotency(
    conn,
    *,
    key: str,
    attempt_count: int,
    lease_secs_ago: int,
    status: str = "pending",
) -> None:
    """Seed a ``task_dedup`` row whose lease has already expired.

    The reconciler sweep promotes rows where ``lease_expires_at`` is past
    by at least 60 seconds AND ``attempt_count`` has hit the poison-loop
    threshold.
    """
    conn.execute(
        text(
            """
            INSERT INTO task_dedup (
                idempotency_key, task_name, task_id, status,
                attempt_count, lease_owner_id, lease_expires_at,
                created_at
            ) VALUES (
                :key, 'ingest', :tid, :status, :attempts,
                :owner, clock_timestamp() - make_interval(secs => :secs),
                clock_timestamp() - make_interval(mins => 5)
            )
            """
        ),
        {
            "key": key, "tid": f"task-{key}", "status": status,
            "attempts": int(attempt_count), "owner": f"owner-{key}",
            "secs": int(lease_secs_ago),
        },
    )


class TestFindStuckIdempotencyPending:
    def test_returns_stuck_pending_with_expired_lease_and_max_attempts(
        self, pg_conn,
    ):
        _seed_stuck_idempotency(
            pg_conn, key="stuck-1", attempt_count=5, lease_secs_ago=120,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_stuck_idempotency_pending(max_attempts=5)
        assert any(r["idempotency_key"] == "stuck-1" for r in rows)

    def test_excludes_completed_rows(self, pg_conn):
        _seed_stuck_idempotency(
            pg_conn, key="done", attempt_count=5, lease_secs_ago=120,
            status="completed",
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_stuck_idempotency_pending(max_attempts=5)
        assert all(r["idempotency_key"] != "done" for r in rows)

    def test_excludes_under_attempt_threshold(self, pg_conn):
        _seed_stuck_idempotency(
            pg_conn, key="few", attempt_count=2, lease_secs_ago=120,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_stuck_idempotency_pending(max_attempts=5)
        assert all(r["idempotency_key"] != "few" for r in rows)

    def test_excludes_within_grace_window(self, pg_conn):
        """Lease expired only 10 seconds ago — heartbeat may still be
        ticking; grace window keeps the row out of the sweep until the
        worker is definitively gone.
        """
        _seed_stuck_idempotency(
            pg_conn, key="recent", attempt_count=5, lease_secs_ago=10,
        )
        repo = ReconciliationRepository(pg_conn)
        rows = repo.find_stuck_idempotency_pending(
            max_attempts=5, lease_grace_seconds=60,
        )
        assert all(r["idempotency_key"] != "recent" for r in rows)


class TestMarkIdempotencyPendingFailed:
    def test_flips_to_failed_with_reconciled_marker(self, pg_conn):
        _seed_stuck_idempotency(
            pg_conn, key="esc", attempt_count=5, lease_secs_ago=120,
        )
        repo = ReconciliationRepository(pg_conn)
        assert repo.mark_idempotency_pending_failed(
            "esc", error="abandoned",
        ) is True
        row = pg_conn.execute(
            text(
                "SELECT status, result_json, lease_owner_id, lease_expires_at "
                "FROM task_dedup WHERE idempotency_key = :k"
            ),
            {"k": "esc"},
        ).fetchone()
        assert row[0] == "failed"
        assert row[1]["reconciled"] is True
        assert row[1]["error"] == "abandoned"
        # Lease columns cleared so the row no longer shows as in-flight
        # in operator dashboards.
        assert row[2] is None
        assert row[3] is None

    def test_no_op_when_already_terminal(self, pg_conn):
        _seed_stuck_idempotency(
            pg_conn, key="done-2", attempt_count=5, lease_secs_ago=120,
            status="completed",
        )
        repo = ReconciliationRepository(pg_conn)
        assert repo.mark_idempotency_pending_failed(
            "done-2", error="should-not-overwrite",
        ) is False
        row = pg_conn.execute(
            text("SELECT status FROM task_dedup WHERE idempotency_key = :k"),
            {"k": "done-2"},
        ).fetchone()
        assert row[0] == "completed"
