"""Repository for reconciliation sweeps over stuck durability rows."""

from __future__ import annotations

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class ReconciliationRepository:
    """Sweeps and terminal writes for the reconciler beat task."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def find_and_lock_stuck_messages(
        self, *, age_minutes: int = 5, tool_grace_minutes: int = 15,
        limit: int = 100,
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

        A second exemption covers **server-executed** tools.
        ``pending_tool_state`` is only written on the pause path (client-side
        tools, approval gates), so an agent grinding through
        ``google_search``/``read_webpage``/``code_executor`` rounds has no PT
        row and was swept as "stuck" while perfectly healthy. A message with a
        ``proposed``/``executed`` ``tool_call_attempts`` row that transitioned
        within ``tool_grace_minutes`` is therefore also exempt. This is
        deliberately redundant with the stream's timed heartbeat: that write
        shares the app's connection pool, so pool pressure is exactly the
        moment liveness should not depend on it, whereas these rows were
        committed earlier by a different code path.

        Note the coupling — the ``proposed`` (5 min) and ``executed`` (15 min)
        sweeps below both flip rows to ``failed``, which drops them out of this
        exemption. That is intentional (a genuinely dead stream's exemption
        expires rather than lasting forever), but it means shortening either
        sweep silently shortens this grace too.

        Args:
            age_minutes: Staleness threshold for the message row.
            tool_grace_minutes: How recently a tool call must have transitioned
                for its message to count as live.
            limit: Maximum rows to lock per tick.

        Returns:
            The locked rows as dicts.
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
                        AND pts.user_id = cm.user_id
                        AND (
                            (pts.status = 'pending'
                             AND pts.expires_at > now())
                            OR
                            (pts.status = 'resuming'
                             AND pts.resumed_at
                                 > now() - interval '10 minutes')
                        )
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM tool_call_attempts tca
                      WHERE tca.message_id = cm.id
                        AND tca.status IN ('proposed', 'executed')
                        AND tca.updated_at
                            > now() - make_interval(mins => :tool_grace)
                  )
                ORDER BY cm.timestamp ASC
                LIMIT :limit
                FOR UPDATE OF cm SKIP LOCKED
                """
            ),
            {
                "age": age_minutes,
                "tool_grace": tool_grace_minutes,
                "limit": limit,
            },
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
        """Lock still-active ingest checkpoints with a silent heartbeat.

        The ``status = 'active'`` filter skips rows already escalated to
        ``'stalled'``, so a dead ingest is alerted once, not every tick.
        """
        result = self._conn.execute(
            text(
                """
                SELECT icp.source_id, icp.total_chunks, icp.embedded_chunks,
                       icp.last_index, icp.last_updated,
                       s.user_id, s.name AS source_name
                FROM ingest_chunk_progress icp
                LEFT JOIN sources s ON s.id = icp.source_id
                WHERE icp.last_updated < now() - make_interval(mins => :age)
                  AND icp.embedded_chunks < icp.total_chunks
                  AND icp.status = 'active'
                ORDER BY icp.last_updated ASC
                LIMIT :limit
                FOR UPDATE OF icp SKIP LOCKED
                """
            ),
            {"age": age_minutes, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def mark_ingest_stalled(self, source_id: str) -> bool:
        """Escalate a stalled checkpoint to terminal ``status='stalled'``.

        Drops the row out of the sweep so the reconciler alerts once;
        ``init_progress`` flips it back to ``'active'`` on reingest.
        """
        result = self._conn.execute(
            text(
                "UPDATE ingest_chunk_progress SET status = 'stalled' "
                "WHERE source_id = CAST(:sid AS uuid)"
            ),
            {"sid": str(source_id)},
        )
        return result.rowcount > 0

    def increment_message_reconcile_attempts(self, message_id: str) -> int:
        """Bump ``reconcile_attempts``, resetting it if the row proved alive.

        The counter means *consecutive* stale ticks, not a lifetime total. It
        used to be a pure accumulator, so a long tool loop that stalled, then
        recovered, then stalled again died on its second stall — with a
        counter whose name lied about what it counted. Each tick records the
        ``last_heartbeat_at`` it observed; if the heartbeat has advanced since
        the previous tick, the stream demonstrably produced life in between
        and the count restarts at 1.

        This also absorbs a race the timed heartbeat introduces: the
        reconciler can lock a row microseconds before the ticker's stamp
        commits, and without the reset that phantom attempt would be
        permanent.

        Safe against masking a dead stream: ``last_heartbeat_at`` is only ever
        written by ``heartbeat_message``, which runs in the process producing
        the stream. A dead producer cannot advance it, so the reset condition
        can never be met and escalation proceeds unchanged.

        Args:
            message_id: The message row to bump.

        Returns:
            The new consecutive-stale-tick count.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET message_metadata =
                    jsonb_set(
                        jsonb_set(
                            COALESCE(message_metadata, '{}'::jsonb),
                            '{reconcile_attempts}',
                            to_jsonb(
                                CASE
                                    WHEN message_metadata->>'last_heartbeat_at'
                                         IS DISTINCT FROM
                                         message_metadata->>'last_reconcile_seen_heartbeat'
                                    THEN 1
                                    ELSE COALESCE(
                                        (message_metadata->>'reconcile_attempts')::int,
                                        0
                                    ) + 1
                                END
                            )
                        ),
                        '{last_reconcile_seen_heartbeat}',
                        COALESCE(
                            message_metadata->'last_heartbeat_at',
                            'null'::jsonb
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

    def mark_message_approval_cleared(self, message_id: str) -> bool:
        """Record that this sweep also revoked an awaiting-approval prompt.

        Read by ``finalize_message``'s reclaim path, which refuses to revive a
        row whose ``pending_tool_state`` the reconciler already deleted and
        whose ``tool.approval.cleared`` event has already been published.

        Args:
            message_id: The message row to stamp.

        Returns:
            True when the row was stamped.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET message_metadata = jsonb_set(
                    COALESCE(message_metadata, '{}'::jsonb),
                    '{reconciler_cleared_approval}',
                    'true'::jsonb
                )
                WHERE id = CAST(:message_id AS uuid)
                """
            ),
            {"message_id": message_id},
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
