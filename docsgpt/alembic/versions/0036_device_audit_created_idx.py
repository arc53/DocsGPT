"""0036 device audit feed index — created_at for the merged activity feed.

``device_audit_log`` carried only ``(device_id, created_at DESC)`` and
``(user_id, created_at DESC)``. Both serve a per-device or per-user lookup;
neither can serve the merged admin activity feed, which orders by
``created_at DESC`` across every user and device, so that branch of the union
was sequentially scanned on every page.

``auth_events`` got the equivalent index in 0034 and ``guardrail_events`` has
had ``ix_guardrail_events_created`` since 0029; this closes the third journal.

Idempotent both ways.

Revision ID: 0036_device_audit_created_idx
Revises: 0035_token_usage_latency
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0036_device_audit_created_idx"
down_revision: Union[str, None] = "0035_token_usage_latency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS device_audit_created_idx "
        "ON device_audit_log (created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS device_audit_created_idx;")
