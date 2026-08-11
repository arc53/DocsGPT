"""Repository for ``webhook_dedup`` and ``task_dedup``; 24h TTL enforced at read."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict
from application.storage.db.serialization import PGNativeJSONEncoder

# 24h TTL is the contract surfaced in the upload/webhook docstrings; the
# read filters and the stale-row replacement predicate must agree, or the
# upsert can fall into a window where the row is "fresh" to the writer
# but "expired" to the reader (or vice versa). Keep one constant so any
# future change moves both directions in lockstep.
DEDUP_TTL_INTERVAL = "24 hours"


def _jsonb(value: Any) -> Any:
    if value is None:
        return None
    return json.dumps(value, cls=PGNativeJSONEncoder)


class IdempotencyRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # --- webhook_dedup -----------------------------------------------------

    def get_webhook(self, key: str) -> Optional[dict]:
        """Return the cached webhook row for ``key`` if still within the 24h window."""
        row = self._conn.execute(
            text(
                """
                SELECT * FROM webhook_dedup
                WHERE idempotency_key = :key
                  AND created_at > now() - CAST(:ttl AS interval)
                """
            ),
            {"key": key, "ttl": DEDUP_TTL_INTERVAL},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def record_webhook(
        self,
        key: str,
        agent_id: str,
        task_id: str,
        response_json: dict,
    ) -> Optional[dict]:
        """Insert a webhook dedup row; return None if another writer raced and won.

        ``ON CONFLICT`` replaces an existing row only when its ``created_at``
        is past TTL — atomic stale-row recycling under the row lock. A
        within-TTL conflict yields no row; the caller resolves it via
        :meth:`get_webhook`.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO webhook_dedup (
                    idempotency_key, agent_id, task_id, response_json
                )
                VALUES (
                    :key, CAST(:agent_id AS uuid), :task_id,
                    CAST(:response_json AS jsonb)
                )
                ON CONFLICT (idempotency_key) DO UPDATE
                   SET agent_id      = EXCLUDED.agent_id,
                       task_id       = EXCLUDED.task_id,
                       response_json = EXCLUDED.response_json,
                       created_at    = now()
                   WHERE webhook_dedup.created_at
                         <= now() - CAST(:ttl AS interval)
                RETURNING *
                """
            ),
            {
                "key": key,
                "agent_id": agent_id,
                "task_id": task_id,
                "response_json": _jsonb(response_json),
                "ttl": DEDUP_TTL_INTERVAL,
            },
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    # --- task_dedup --------------------------------------------------------

    def get_task(self, key: str) -> Optional[dict]:
        """Return the cached task row for ``key`` if still within the 24h window."""
        row = self._conn.execute(
            text(
                """
                SELECT * FROM task_dedup
                WHERE idempotency_key = :key
                  AND created_at > now() - CAST(:ttl AS interval)
                """
            ),
            {"key": key, "ttl": DEDUP_TTL_INTERVAL},
        ).fetchone()
        return row_to_dict(row) if row is not None else None

    def claim_task(
        self,
        key: str,
        task_name: str,
        task_id: str,
    ) -> Optional[dict]:
        """Claim ``key`` for this task. Returns the inserted row, or None if
        another writer raced and won. The HTTP entry must call this *before*
        ``.delay()`` so only the winner enqueues the Celery task.

        ``ON CONFLICT`` replaces an existing row in two cases:

        - **status='failed'**: the worker's poison-loop guard or the
          reconciler's stuck-pending sweep finalised the prior attempt
          as failed. Both explicitly intend a same-key retry to re-run
          (see ``run_reconciliation`` Q5 docstring) — letting the row
          block for 24 h would silently undo that intent.
        - **created_at past TTL**: a stale claim from any status no
          longer represents a meaningful dedup signal.

        ``status='completed'`` rows still block within TTL — that's the
        cached-success contract callers rely on. ``status='pending'``
        rows still block within TTL so concurrent same-key requests
        collapse onto the in-flight task. Result/attempt fields are
        reset to their fresh-claim defaults during replacement.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO task_dedup (
                    idempotency_key, task_name, task_id, result_json, status
                )
                VALUES (
                    :key, :task_name, :task_id, NULL, 'pending'
                )
                ON CONFLICT (idempotency_key) DO UPDATE
                   SET task_name     = EXCLUDED.task_name,
                       task_id       = EXCLUDED.task_id,
                       result_json   = NULL,
                       status        = 'pending',
                       attempt_count = 0,
                       created_at    = now()
                   WHERE task_dedup.status = 'failed'
                      OR task_dedup.created_at
                         <= now() - CAST(:ttl AS interval)
                RETURNING *
                """
            ),
            {
                "key": key,
                "task_name": task_name,
                "task_id": task_id,
                "ttl": DEDUP_TTL_INTERVAL,
            },
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def try_claim_lease(
        self,
        key: str,
        task_name: str,
        task_id: str,
        owner_id: str,
        ttl_seconds: int = 60,
    ) -> Optional[int]:
        """Atomically claim the running lease for ``key``.

        Returns the new ``attempt_count`` if this caller now owns the
        lease (fresh insert OR existing row whose lease was empty/expired),
        or ``None`` if a different worker holds a live lease.

        The conflict path also bumps ``attempt_count`` so the
        poison-loop guard in :func:`with_idempotency` can fire after
        :data:`MAX_TASK_ATTEMPTS` reclaims. ``status='completed'`` rows
        are deliberately untouched — :func:`_lookup_completed` is the
        cache short-circuit and runs before this. Uses
        ``clock_timestamp()`` so a same-transaction refresh actually
        moves the expiry forward (``now()`` is frozen at txn start).
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO task_dedup (
                    idempotency_key, task_name, task_id, status, attempt_count,
                    lease_owner_id, lease_expires_at
                ) VALUES (
                    :key, :task_name, :task_id, 'pending', 1,
                    :owner,
                    clock_timestamp() + make_interval(secs => :ttl)
                )
                ON CONFLICT (idempotency_key) DO UPDATE
                   SET attempt_count    = task_dedup.attempt_count + 1,
                       task_name        = EXCLUDED.task_name,
                       lease_owner_id   = EXCLUDED.lease_owner_id,
                       lease_expires_at = EXCLUDED.lease_expires_at
                   WHERE task_dedup.status <> 'completed'
                     AND (task_dedup.lease_expires_at IS NULL
                          OR task_dedup.lease_expires_at <= clock_timestamp())
                RETURNING attempt_count
                """
            ),
            {
                "key": key,
                "task_name": task_name,
                "task_id": task_id,
                "owner": owner_id,
                "ttl": int(ttl_seconds),
            },
        )
        row = result.fetchone()
        return int(row[0]) if row is not None else None

    def refresh_lease(
        self,
        key: str,
        owner_id: str,
        ttl_seconds: int = 60,
    ) -> bool:
        """Bump ``lease_expires_at`` if this caller still owns the lease.

        Returns False when ownership was lost (lease stolen by another
        worker after expiry, or row finalised). The heartbeat thread
        logs that as a warning but doesn't try to abort the running
        task — at-most-one-worker is bounded by ``ttl_seconds``, the
        damage from a brief overlap window is unavoidable in this case.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE task_dedup
                SET lease_expires_at =
                        clock_timestamp() + make_interval(secs => :ttl)
                WHERE idempotency_key = :key
                  AND lease_owner_id = :owner
                  AND status = 'pending'
                """
            ),
            {
                "key": key,
                "owner": owner_id,
                "ttl": int(ttl_seconds),
            },
        )
        return result.rowcount > 0

    def release_lease(self, key: str, owner_id: str) -> bool:
        """Clear ``lease_owner_id`` / ``lease_expires_at`` on the
        wrapper's exception path so Celery's autoretry_for doesn't have
        to wait the full ``ttl_seconds`` before the next worker can
        re-claim. No-op if a different worker has since taken over the
        lease — that case is benign (we'd just be acknowledging we
        weren't the owner anymore).
        """
        result = self._conn.execute(
            text(
                """
                UPDATE task_dedup
                SET lease_owner_id   = NULL,
                    lease_expires_at = NULL
                WHERE idempotency_key = :key
                  AND lease_owner_id = :owner
                  AND status = 'pending'
                """
            ),
            {"key": key, "owner": owner_id},
        )
        return result.rowcount > 0

    def finalize_task(
        self,
        key: str,
        *,
        result_json: Optional[dict],
        status: str,
    ) -> bool:
        """Promote ``status='pending'`` → ``completed|failed`` with the
        recorded result. Also clears the lease columns so a stale
        ``lease_expires_at`` doesn't show up in operator dashboards.
        No-op if the row is already terminal — preserves the first
        writer's outcome on a crash + retry.
        """
        if status not in ("completed", "failed"):
            raise ValueError(f"finalize_task: invalid status {status!r}")
        result = self._conn.execute(
            text(
                """
                UPDATE task_dedup
                SET status           = :status,
                    result_json      = CAST(:result_json AS jsonb),
                    lease_owner_id   = NULL,
                    lease_expires_at = NULL
                WHERE idempotency_key = :key
                  AND status = 'pending'
                """
            ),
            {
                "key": key,
                "status": status,
                "result_json": _jsonb(result_json),
            },
        )
        return result.rowcount > 0

    # --- housekeeping ------------------------------------------------------

    def cleanup_expired(self) -> dict:
        """Delete rows past TTL from both dedup tables; return per-table counts.

        The TTL-aware upserts already prevent stale rows from blocking new
        work, so this is purely housekeeping — bounds table growth and
        keeps test isolation cheap. Safe to run concurrently with other
        writers: a same-key INSERT racing the DELETE will either find no
        row (acts as a fresh insert) or find a fresh row (re-created
        between DELETE and conflict-check), neither of which is wrong.
        """
        task_deleted = self._conn.execute(
            text(
                """
                DELETE FROM task_dedup
                WHERE created_at <= now() - CAST(:ttl AS interval)
                """
            ),
            {"ttl": DEDUP_TTL_INTERVAL},
        ).rowcount
        webhook_deleted = self._conn.execute(
            text(
                """
                DELETE FROM webhook_dedup
                WHERE created_at <= now() - CAST(:ttl AS interval)
                """
            ),
            {"ttl": DEDUP_TTL_INTERVAL},
        ).rowcount
        return {
            "task_dedup_deleted": int(task_deleted or 0),
            "webhook_dedup_deleted": int(webhook_deleted or 0),
        }

