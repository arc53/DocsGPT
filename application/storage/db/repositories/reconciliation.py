"""Repository for reconciliation sweeps over stuck durability rows."""

from __future__ import annotations

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class ReconciliationRepository:
    """Sweeps and terminal writes for the reconciler beat task."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_and_lock_stuck_messages(
        self, *, age_minutes: int = 5, limit: int = 100,
    ) -> list[dict]:
        """Lock stuck pending/streaming messages skipping live resumes.

        Staleness rides on the **later of** ``cm.timestamp`` (creation)
        and ``message_metadata.last_heartbeat_at`` (route heartbeat). An
        in-flight stream that re-stamps the heartbeat each minute stays
        out of the sweep; reconciler-side writes deliberately don't
        touch either column so the per-row attempts counter advances
        across ticks. Liveness exemption covers both ``pending`` (paused
        waiting for resume) and ``resuming`` (actively executing)
        ``pending_tool_state`` rows so a paused message survives until
        the PT row's own TTL retires it.
        """
        result = self._conn.execute(
            text(
                """
                SELECT cm.id, cm.conversation_id, cm.user_id, cm.timestamp,
                       cm.message_metadata
                FROM conversation_messages cm
                WHERE cm.status IN ('pending', 'streaming')
                  AND cm.timestamp < now() - make_interval(mins => :age)
                  AND COALESCE(
                      (cm.message_metadata->>'last_heartbeat_at')::timestamptz,
                      cm.timestamp
                  ) < now() - make_interval(mins => :age)
                  AND NOT EXISTS (
                      SELECT 1
                      FROM pending_tool_state pts
                      WHERE pts.conversation_id = cm.conversation_id
                        AND (
                            (pts.status = 'pending'
                             AND pts.expires_at > now())
                            OR
                            (pts.status = 'resuming'
                             AND pts.resumed_at
                                 > now() - interval '10 minutes')
                        )
                  )
                ORDER BY cm.timestamp ASC
                LIMIT :limit
                FOR UPDATE OF cm SKIP LOCKED
                """
            ),
            {"age": age_minutes, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def find_and_lock_proposed_tool_calls(
        self, *, age_minutes: int = 5, limit: int = 100,
    ) -> list[dict]:
        """Lock tool_call_attempts that never advanced past ``proposed``."""
        result = self._conn.execute(
            text(
                """
                SELECT call_id, message_id, tool_id, tool_name, action_name,
                       arguments, attempted_at, updated_at
                FROM tool_call_attempts
                WHERE status = 'proposed'
                  AND attempted_at < now() - make_interval(mins => :age)
                ORDER BY attempted_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"age": age_minutes, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def find_and_lock_executed_tool_calls(
        self, *, age_minutes: int = 15, limit: int = 100,
    ) -> list[dict]:
        """Lock tool_call_attempts stuck in ``executed`` past confirm window."""
        result = self._conn.execute(
            text(
                """
                SELECT call_id, message_id, tool_id, tool_name, action_name,
                       arguments, result, attempted_at, updated_at
                FROM tool_call_attempts
                WHERE status = 'executed'
                  AND updated_at < now() - make_interval(mins => :age)
                ORDER BY updated_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"age": age_minutes, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def find_and_lock_stalled_ingests(
        self, *, age_minutes: int = 30, limit: int = 100,
    ) -> list[dict]:
        """Lock ingest checkpoints whose heartbeat hasn't ticked recently."""
        result = self._conn.execute(
            text(
                """
                SELECT source_id, total_chunks, embedded_chunks,
                       last_index, last_updated
                FROM ingest_chunk_progress
                WHERE last_updated < now() - make_interval(mins => :age)
                  AND embedded_chunks < total_chunks
                ORDER BY last_updated ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"age": age_minutes, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def touch_ingest_progress(self, source_id: str) -> bool:
        """Bump ``last_updated`` so a once-stalled ingest re-enters the watch window."""
        result = self._conn.execute(
            text(
                "UPDATE ingest_chunk_progress SET last_updated = now() "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": str(source_id)},
        )
        return result.rowcount > 0

    def increment_message_reconcile_attempts(self, message_id: str) -> int:
        """Bump ``message_metadata.reconcile_attempts`` and return the new count."""
        result = self._conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET message_metadata = jsonb_set(
                    COALESCE(message_metadata, '{}'::jsonb),
                    '{reconcile_attempts}',
                    to_jsonb(
                        COALESCE(
                            (message_metadata->>'reconcile_attempts')::int,
                            0
                        ) + 1
                    )
                )
                WHERE id = CAST(:message_id AS uuid)
                RETURNING (message_metadata->>'reconcile_attempts')::int
                         AS new_count
                """
            ),
            {"message_id": message_id},
        )
        row = result.fetchone()
        return int(row[0]) if row is not None else 0

    def mark_message_failed(self, message_id: str, *, error: str) -> bool:
        """Flip a message to ``status='failed'`` and stash ``error`` in metadata."""
        result = self._conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET status = 'failed',
                    message_metadata = jsonb_set(
                        COALESCE(message_metadata, '{}'::jsonb),
                        '{error}',
                        to_jsonb(CAST(:error AS text))
                    )
                WHERE id = CAST(:message_id AS uuid)
                """
            ),
            {"message_id": message_id, "error": error},
        )
        return result.rowcount > 0

    def mark_tool_call_failed(self, call_id: str, *, error: str) -> bool:
        """Flip a tool_call_attempts row to ``failed`` with ``error``."""
        result = self._conn.execute(
            text(
                "UPDATE tool_call_attempts SET status = 'failed', "
                "error = :error WHERE call_id = :call_id"
            ),
            {"call_id": call_id, "error": error},
        )
        return result.rowcount > 0

    def find_stuck_idempotency_pending(
        self,
        *,
        max_attempts: int,
        lease_grace_seconds: int = 60,
        limit: int = 100,
    ) -> list[dict]:
        """Lock ``task_dedup`` rows abandoned past the lease + retry budget.

        A row is "stuck" when:

        - ``status='pending'`` (lease was claimed but never finalised)
        - ``lease_expires_at`` is past by at least ``lease_grace_seconds``
          (the heartbeat thread is gone — the lease isn't going to come
          back)
        - ``attempt_count >= max_attempts`` (the poison-loop guard
          should already have escalated this; if it hasn't, the wrapper
          died before getting there)

        These rows would otherwise sit in ``pending`` until the 24 h
        TTL aged them out, blocking same-key retries via
        ``_lookup_completed`` returning None for the whole window.
        """
        result = self._conn.execute(
            text(
                """
                SELECT idempotency_key, task_name, task_id, attempt_count,
                       lease_owner_id, lease_expires_at, created_at
                FROM task_dedup
                WHERE status = 'pending'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at
                      < now() - make_interval(secs => :grace)
                  AND attempt_count >= :max_attempts
                ORDER BY created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {
                "max_attempts": int(max_attempts),
                "grace": int(lease_grace_seconds),
                "limit": int(limit),
            },
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def mark_idempotency_pending_failed(
        self, key: str, *, error: str,
    ) -> bool:
        """Promote a stuck pending ``task_dedup`` row to ``failed``."""
        from application.storage.db.serialization import PGNativeJSONEncoder
        import json

        result = self._conn.execute(
            text(
                """
                UPDATE task_dedup
                SET status = 'failed',
                    result_json = CAST(:result AS jsonb),
                    lease_owner_id = NULL,
                    lease_expires_at = NULL
                WHERE idempotency_key = :key
                  AND status = 'pending'
                """
            ),
            {
                "key": key,
                "result": json.dumps(
                    {
                        "success": False,
                        "error": error,
                        "reconciled": True,
                    },
                    cls=PGNativeJSONEncoder,
                ),
            },
        )
        return result.rowcount > 0
