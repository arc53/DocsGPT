"""0008 ingest_chunk_progress.status — terminal flag for stalled ingests.

The reconciler's stalled-ingest sweep had no terminal write, so a dead
ingest re-alerted every ~30 min forever. ``status`` lets it escalate a
stalled checkpoint to ``'stalled'`` once and stop re-selecting it;
``init_progress`` resets it to ``'active'`` on reingest.

Revision ID: 0008_ingest_progress_status
Revises: 0007_message_events
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0008_ingest_progress_status"
down_revision: Union[str, None] = "0007_message_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Constant DEFAULT — metadata-only ADD COLUMN, no table rewrite.
    op.execute(
        """
        ALTER TABLE ingest_chunk_progress
            ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'stalled'));
        """
    )
    # Partial index for the reconciler's stalled-ingest sweep.
    op.execute(
        "CREATE INDEX ingest_chunk_progress_active_idx "
        "ON ingest_chunk_progress (last_updated) "
        "WHERE status = 'active';"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ingest_chunk_progress_active_idx;")
    op.execute(
        "ALTER TABLE ingest_chunk_progress DROP COLUMN IF EXISTS status;"
    )
