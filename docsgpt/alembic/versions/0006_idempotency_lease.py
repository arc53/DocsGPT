"""0006 task_dedup lease columns — running-lease for in-flight tasks.

Without these, ``with_idempotency`` only short-circuits *completed*
rows. A late-ack redelivery (Redis ``visibility_timeout`` exceeded by a
long ingest, or a hung-but-alive worker) hands the same message to a
second worker; ``_claim_or_bump`` only bumped the attempt counter and
both workers ran the task body in parallel — duplicate vector writes,
duplicate token spend, duplicate webhook side effects.

``lease_owner_id`` + ``lease_expires_at`` turn that into an atomic
compare-and-swap. The wrapper claims a lease at entry, refreshes it via
a 30 s heartbeat thread, and finalises (which makes the lease moot via
``status='completed'``). A second worker hitting the same key sees a
fresh lease and ``self.retry(countdown=LEASE_TTL)``s instead of running.
A crashed worker's lease expires after ``LEASE_TTL`` seconds and the
next retry can claim it.

Revision ID: 0006_idempotency_lease
Revises: 0005_ingest_attempt_id
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0006_idempotency_lease"
down_revision: Union[str, None] = "0005_ingest_attempt_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE task_dedup
            ADD COLUMN lease_owner_id   TEXT,
            ADD COLUMN lease_expires_at TIMESTAMPTZ;
        """
    )
    # Reconciler's stuck-pending sweep filters by
    # ``(status='pending', lease_expires_at < now() - 60s, attempt_count >= 5)``.
    # Partial index keeps the scan small even under heavy task throughput.
    op.execute(
        "CREATE INDEX task_dedup_pending_lease_idx "
        "ON task_dedup (lease_expires_at) "
        "WHERE status = 'pending';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS task_dedup_pending_lease_idx;")
    op.execute(
        "ALTER TABLE task_dedup "
        "DROP COLUMN IF EXISTS lease_expires_at, "
        "DROP COLUMN IF EXISTS lease_owner_id;"
    )
