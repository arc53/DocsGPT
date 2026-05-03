"""Tests for the reconciler beat task.

Seeds stuck rows of each kind (Q1 messages, Q2 proposed tool calls, Q3
executed tool calls) and verifies that ``run_reconciliation`` either
retries (Q1 within 3 attempts) or escalates them to terminal status
with both a structured logger error and a stack_logs row.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers — seed rows in shapes that mirror the live writers (T3 reserve_message
# for stuck messages, T8 record_proposed for tool_call_attempts).
# ---------------------------------------------------------------------------


def _create_conv(conn, user_id: str = "u-1") -> dict:
    from application.storage.db.repositories.conversations import (
        ConversationsRepository,
    )

    return ConversationsRepository(conn).create(user_id, "rec test")


def _seed_pending_message(
    conn,
    *,
    user_id: str = "u-1",
    age_minutes: int = 6,
    status: str = "pending",
) -> dict:
    """Insert a conversation_messages row in ``status`` with stale ``timestamp``."""
    conv = _create_conv(conn, user_id=user_id)
    row = conn.execute(
        text(
            """
            INSERT INTO conversation_messages (
                conversation_id, position, prompt, response, status,
                user_id, timestamp
            )
            VALUES (
                CAST(:conv_id AS uuid), 0, :prompt, :resp, :status,
                :user_id,
                clock_timestamp() - make_interval(mins => :age)
            )
            RETURNING id
            """
        ),
        {
            "conv_id": conv["id"],
            "prompt": "hello",
            "resp": "",
            "status": status,
            "user_id": user_id,
            "age": age_minutes,
        },
    ).fetchone()
    return {"id": str(row[0]), "conversation_id": conv["id"], "user_id": user_id}


def _seed_resuming_state(conn, conv_id: str, user_id: str, *, secs_ago: int) -> None:
    """Insert a pending_tool_state row in ``resuming`` with ``resumed_at`` backdated."""
    conn.execute(
        text(
            """
            INSERT INTO pending_tool_state (
                conversation_id, user_id, messages, pending_tool_calls,
                tools_dict, tool_schemas, agent_config,
                created_at, expires_at, status, resumed_at
            )
            VALUES (
                CAST(:conv_id AS uuid), :user_id,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                clock_timestamp(),
                clock_timestamp() + interval '30 minutes',
                'resuming',
                clock_timestamp() - make_interval(secs => :secs_ago)
            )
            """
        ),
        {"conv_id": conv_id, "user_id": user_id, "secs_ago": secs_ago},
    )


def _seed_pending_state(
    conn, conv_id: str, user_id: str, *, expires_in_minutes: int = 30,
) -> None:
    """Insert a paused ``pending_tool_state`` row (status='pending').

    A negative ``expires_in_minutes`` simulates a TTL-expired row that
    the cleanup janitor hasn't yet reaped.
    """
    conn.execute(
        text(
            """
            INSERT INTO pending_tool_state (
                conversation_id, user_id, messages, pending_tool_calls,
                tools_dict, tool_schemas, agent_config,
                created_at, expires_at, status, resumed_at
            )
            VALUES (
                CAST(:conv_id AS uuid), :user_id,
                '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                clock_timestamp(),
                clock_timestamp() + make_interval(mins => :exp),
                'pending',
                NULL
            )
            """
        ),
        {"conv_id": conv_id, "user_id": user_id, "exp": expires_in_minutes},
    )


def _seed_tool_call(
    conn,
    *,
    call_id: str,
    status: str,
    tool_name: str = "notes",
    age_minutes: int = 16,
    tool_id: str | None = None,
    arguments: dict | None = None,
    action_name: str = "view",
) -> None:
    """Insert a tool_call_attempts row, then backdate ``attempted_at``/``updated_at``."""
    conn.execute(
        text(
            """
            INSERT INTO tool_call_attempts (
                call_id, tool_id, tool_name, action_name, arguments, status
            )
            VALUES (
                :call_id, CAST(:tool_id AS uuid), :tool_name, :action_name,
                CAST(:arguments AS jsonb), :status
            )
            """
        ),
        {
            "call_id": call_id,
            "tool_id": tool_id,
            "tool_name": tool_name,
            "action_name": action_name,
            "arguments": json.dumps(arguments or {}),
            "status": status,
        },
    )
    # The set_updated_at BEFORE-UPDATE trigger would clobber updated_at;
    # disable it briefly so the backdate lands.
    conn.execute(text("ALTER TABLE tool_call_attempts DISABLE TRIGGER USER"))
    try:
        conn.execute(
            text(
                """
                UPDATE tool_call_attempts
                SET attempted_at = clock_timestamp() - make_interval(mins => :age),
                    updated_at = clock_timestamp() - make_interval(mins => :age)
                WHERE call_id = :call_id
                """
            ),
            {"call_id": call_id, "age": age_minutes},
        )
    finally:
        conn.execute(text("ALTER TABLE tool_call_attempts ENABLE TRIGGER USER"))


def _stack_logs_count(conn, query: str | None = None) -> int:
    if query is None:
        result = conn.execute(text("SELECT count(*) FROM stack_logs"))
    else:
        result = conn.execute(
            text("SELECT count(*) FROM stack_logs WHERE query = :q"),
            {"q": query},
        )
    return int(result.scalar() or 0)


@contextmanager
def _route_engine_to(pg_conn):
    """Patch ``get_engine`` so the run_reconciliation reuses the test conn."""

    @contextmanager
    def _fake_begin():
        # The repository writes happen on this connection; rolling back
        # at the end of the test cleans them up.
        yield pg_conn

    fake_engine = MagicMock()
    fake_engine.begin = _fake_begin

    with patch(
        "application.api.user.reconciliation.get_engine",
        return_value=fake_engine,
    ):
        yield


# ---------------------------------------------------------------------------
# Q1 — stuck messages
# ---------------------------------------------------------------------------


class TestStuckMessages:
    @pytest.mark.unit
    def test_first_two_attempts_increment_only(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)

        with _route_engine_to(pg_conn):
            r1 = run_reconciliation()
            r2 = run_reconciliation()

        assert r1["messages_failed"] == 0
        assert r2["messages_failed"] == 0

        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata "
                "FROM conversation_messages WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "pending"
        assert row[1]["reconcile_attempts"] == 2

    @pytest.mark.unit
    def test_third_attempt_marks_failed_and_emits_alert(self, pg_conn, caplog):
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)
        before_logs = _stack_logs_count(pg_conn, "reconciler_message_failed")

        with _route_engine_to(pg_conn), caplog.at_level(
            logging.ERROR, logger="application.api.user.reconciliation",
        ):
            run_reconciliation()
            run_reconciliation()
            r3 = run_reconciliation()

        assert r3["messages_failed"] == 1

        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata "
                "FROM conversation_messages WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "failed"
        assert row[1]["reconcile_attempts"] == 3
        assert "reconciler:" in (row[1].get("error") or "")

        # Structured alert + stack_logs row both surface the failure.
        assert any(
            "reconciler alert" in rec.getMessage()
            and rec.levelname == "ERROR"
            and getattr(rec, "alert", None) == "reconciler_message_failed"
            for rec in caplog.records
        )
        assert (
            _stack_logs_count(pg_conn, "reconciler_message_failed")
            == before_logs + 1
        )

    @pytest.mark.unit
    def test_streaming_status_also_eligible(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn, status="streaming")
        with _route_engine_to(pg_conn):
            run_reconciliation()
            run_reconciliation()
            run_reconciliation()

        row = pg_conn.execute(
            text(
                "SELECT status FROM conversation_messages "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "failed"

    @pytest.mark.unit
    def test_skipped_when_active_resuming_state(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)
        # Active resume started 60 seconds ago — within 10-min grace.
        _seed_resuming_state(pg_conn, msg["conversation_id"], msg["user_id"], secs_ago=60)

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["messages_failed"] == 0
        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata "
                "FROM conversation_messages WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "pending"
        # No attempts recorded: row was skipped, not just not-yet-failed.
        assert "reconcile_attempts" not in row[1]

    @pytest.mark.unit
    def test_stale_resuming_does_not_skip(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)
        # 11 minutes ago — past the 10-minute grace window.
        _seed_resuming_state(
            pg_conn, msg["conversation_id"], msg["user_id"], secs_ago=11 * 60,
        )

        with _route_engine_to(pg_conn):
            run_reconciliation()

        row = pg_conn.execute(
            text(
                "SELECT message_metadata FROM conversation_messages "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        # Stale resuming shouldn't shield: attempt counter must have moved.
        assert row[0].get("reconcile_attempts") == 1

    @pytest.mark.unit
    def test_fresh_message_left_alone(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        # 1 minute old — well under the 5-minute threshold.
        msg = _seed_pending_message(pg_conn, age_minutes=1)

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["messages_failed"] == 0
        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata FROM conversation_messages "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "pending"
        assert "reconcile_attempts" not in row[1]

    @pytest.mark.unit
    def test_skipped_when_paused_pending_state_active(self, pg_conn):
        """A paused conversation (PT.status='pending') must not get failed
        while the user is still considering tool approval. The PT row's
        own ``expires_at`` TTL is the abandonment signal.
        """
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)
        _seed_pending_state(
            pg_conn, msg["conversation_id"], msg["user_id"],
            expires_in_minutes=30,
        )

        with _route_engine_to(pg_conn):
            r1 = run_reconciliation()
            r2 = run_reconciliation()
            r3 = run_reconciliation()

        assert r1["messages_failed"] == 0
        assert r2["messages_failed"] == 0
        assert r3["messages_failed"] == 0
        row = pg_conn.execute(
            text(
                "SELECT status, message_metadata FROM conversation_messages "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0] == "pending"
        # No attempts recorded: the row was excluded from the sweep, not
        # just held under the 3-attempt threshold.
        assert "reconcile_attempts" not in row[1]

    @pytest.mark.unit
    def test_expired_pending_state_does_not_skip(self, pg_conn):
        """When the PT row's TTL has expired but the cleanup janitor
        hasn't reaped it yet, the message becomes eligible immediately
        — we don't wait an extra ~60s for janitor cadence to align.
        """
        from application.api.user.reconciliation import run_reconciliation

        msg = _seed_pending_message(pg_conn)
        _seed_pending_state(
            pg_conn, msg["conversation_id"], msg["user_id"],
            expires_in_minutes=-1,
        )

        with _route_engine_to(pg_conn):
            run_reconciliation()

        row = pg_conn.execute(
            text(
                "SELECT message_metadata FROM conversation_messages "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": msg["id"]},
        ).fetchone()
        assert row[0].get("reconcile_attempts") == 1


# ---------------------------------------------------------------------------
# Q2 — proposed tool calls (side effect unknown)
# ---------------------------------------------------------------------------


class TestStuckProposedToolCalls:
    @pytest.mark.unit
    def test_marks_proposed_failed_with_alert(self, pg_conn, caplog):
        from application.api.user.reconciliation import run_reconciliation

        _seed_tool_call(pg_conn, call_id="cp-1", status="proposed", age_minutes=6)
        before = _stack_logs_count(pg_conn, "reconciler_tool_call_failed_proposed")

        with _route_engine_to(pg_conn), caplog.at_level(
            logging.ERROR, logger="application.api.user.reconciliation",
        ):
            r = run_reconciliation()

        assert r["tool_calls_failed"] == 1
        row = pg_conn.execute(
            text("SELECT status, error FROM tool_call_attempts WHERE call_id = :id"),
            {"id": "cp-1"},
        ).fetchone()
        assert row[0] == "failed"
        assert "side effect status unknown" in (row[1] or "")

        assert any(
            getattr(rec, "alert", None) == "reconciler_tool_call_failed_proposed"
            for rec in caplog.records
        )
        assert (
            _stack_logs_count(pg_conn, "reconciler_tool_call_failed_proposed")
            == before + 1
        )

    @pytest.mark.unit
    def test_fresh_proposed_left_alone(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        _seed_tool_call(pg_conn, call_id="cp-2", status="proposed", age_minutes=2)

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["tool_calls_failed"] == 0
        row = pg_conn.execute(
            text("SELECT status FROM tool_call_attempts WHERE call_id = :id"),
            {"id": "cp-2"},
        ).fetchone()
        assert row[0] == "proposed"


# ---------------------------------------------------------------------------
# Q3 — executed tool calls (escalate to failed; manual cleanup expected)
# ---------------------------------------------------------------------------


class TestStuckExecutedToolCalls:
    @pytest.mark.unit
    def test_executed_past_ttl_marked_failed_with_alert(self, pg_conn, caplog):
        from application.api.user.reconciliation import run_reconciliation

        _seed_tool_call(
            pg_conn, call_id="ce-1", status="executed",
            tool_name="notes", age_minutes=16,
        )
        before = _stack_logs_count(pg_conn, "reconciler_tool_call_failed_executed")

        with _route_engine_to(pg_conn), caplog.at_level(
            logging.ERROR, logger="application.api.user.reconciliation",
        ):
            r = run_reconciliation()

        assert r["tool_calls_failed"] == 1
        row = pg_conn.execute(
            text("SELECT status, error FROM tool_call_attempts WHERE call_id = :id"),
            {"id": "ce-1"},
        ).fetchone()
        assert row[0] == "failed"
        assert "executed-not-confirmed" in (row[1] or "")
        assert "manual cleanup" in (row[1] or "")
        assert any(
            getattr(rec, "alert", None) == "reconciler_tool_call_failed_executed"
            for rec in caplog.records
        )
        assert (
            _stack_logs_count(pg_conn, "reconciler_tool_call_failed_executed")
            == before + 1
        )

    @pytest.mark.unit
    def test_fresh_executed_left_alone(self, pg_conn):
        from application.api.user.reconciliation import run_reconciliation

        _seed_tool_call(
            pg_conn, call_id="ce-2", status="executed",
            tool_name="notes", age_minutes=5,  # under 15-min threshold
        )

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["tool_calls_failed"] == 0
        row = pg_conn.execute(
            text("SELECT status FROM tool_call_attempts WHERE call_id = :id"),
            {"id": "ce-2"},
        ).fetchone()
        assert row[0] == "executed"


# ---------------------------------------------------------------------------
# Q5 — stuck idempotency pending rows (lease expired + attempts exhausted)
# ---------------------------------------------------------------------------


def _seed_stuck_idempotency_row(
    conn,
    *,
    key: str,
    attempt_count: int,
    lease_secs_ago: int,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO task_dedup (
                idempotency_key, task_name, task_id, status,
                attempt_count, lease_owner_id, lease_expires_at,
                created_at
            ) VALUES (
                :key, 'ingest', :tid, 'pending', :attempts,
                :owner,
                clock_timestamp() - make_interval(secs => :secs),
                clock_timestamp() - make_interval(mins => 5)
            )
            """
        ),
        {
            "key": key,
            "tid": f"task-{key}",
            "attempts": int(attempt_count),
            "owner": f"owner-{key}",
            "secs": int(lease_secs_ago),
        },
    )


class TestStuckIdempotencyPending:
    @pytest.mark.unit
    def test_promotes_to_failed_with_alert(self, pg_conn, caplog):
        """A pending row whose lease expired and whose attempt counter
        already hit the poison-loop threshold gets escalated to failed
        so a same-key retry can re-claim instead of waiting 24 h.
        """
        from application.api.user.reconciliation import run_reconciliation

        _seed_stuck_idempotency_row(
            pg_conn, key="abandoned", attempt_count=5, lease_secs_ago=120,
        )
        before = _stack_logs_count(
            pg_conn, "reconciler_idempotency_pending_failed",
        )

        with _route_engine_to(pg_conn), caplog.at_level(
            logging.ERROR, logger="application.api.user.reconciliation",
        ):
            r = run_reconciliation()

        assert r["idempotency_pending_failed"] == 1
        row = pg_conn.execute(
            text(
                "SELECT status, result_json FROM task_dedup "
                "WHERE idempotency_key = :k"
            ),
            {"k": "abandoned"},
        ).fetchone()
        assert row[0] == "failed"
        assert row[1]["reconciled"] is True
        assert "lease expired" in row[1]["error"]

        assert any(
            getattr(rec, "alert", None) == "reconciler_idempotency_pending_failed"
            for rec in caplog.records
        )
        assert (
            _stack_logs_count(
                pg_conn, "reconciler_idempotency_pending_failed",
            )
            == before + 1
        )

    @pytest.mark.unit
    def test_skips_under_attempt_threshold(self, pg_conn):
        """Attempt count below the threshold means the wrapper might
        still re-claim cleanly — leave the row alone.
        """
        from application.api.user.reconciliation import run_reconciliation

        _seed_stuck_idempotency_row(
            pg_conn, key="recoverable", attempt_count=2, lease_secs_ago=120,
        )

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["idempotency_pending_failed"] == 0
        row = pg_conn.execute(
            text("SELECT status FROM task_dedup WHERE idempotency_key = :k"),
            {"k": "recoverable"},
        ).fetchone()
        assert row[0] == "pending"

    @pytest.mark.unit
    def test_skips_within_lease_grace(self, pg_conn):
        """A lease that just expired (10 s ago) might be in the
        heartbeat-tick window; the 60 s grace keeps the sweep quiet.
        """
        from application.api.user.reconciliation import run_reconciliation

        _seed_stuck_idempotency_row(
            pg_conn, key="just-expired", attempt_count=5, lease_secs_ago=10,
        )

        with _route_engine_to(pg_conn):
            r = run_reconciliation()

        assert r["idempotency_pending_failed"] == 0


# ---------------------------------------------------------------------------
# Skip path
# ---------------------------------------------------------------------------


class TestPostgresUriMissing:
    @pytest.mark.unit
    def test_returns_skip_dict(self, monkeypatch):
        from application.api.user.reconciliation import run_reconciliation
        from application.core.settings import settings

        monkeypatch.setattr(settings, "POSTGRES_URI", None, raising=False)

        result = run_reconciliation()
        assert result == {
            "messages_failed": 0,
            "tool_calls_failed": 0,
            "skipped": "POSTGRES_URI not set",
        }
