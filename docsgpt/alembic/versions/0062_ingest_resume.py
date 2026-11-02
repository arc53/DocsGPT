"""0062 ingest resume — what the reconciler needs to restart a killed ingest.

* ``ingest_chunk_progress.chunk_fingerprint``: a hash of the chunk set being
  embedded (its texts and the embeddings model). A new task for the same
  source and the same chunk set resumes from the checkpoint; a changed chunk
  set starts again from chunk 0. NULL on existing rows, which keep the
  attempt-id rule.
* ``ingest_chunk_progress.dispatch``: the task name and arguments of the
  ingest, while it runs, so the reconciler can queue it again after a
  restart killed it. Cleared once the embed finishes or the ingest ends.
* ``ingest_chunk_progress.resume_attempts``: how many times the reconciler
  has queued the ingest again; past ``INGEST_RESUME_MAX_ATTEMPTS`` it stops.

No backfill. Idempotent both ways; downgrade drops the three columns.

Revision ID: 0062_ingest_resume
Revises: 0061_agent_starters
"""

from alembic import op

revision = "0062_ingest_resume"
down_revision = "0061_agent_starters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the fingerprint, dispatch and resume counter to ``ingest_chunk_progress``."""
    op.execute(
        """
        ALTER TABLE ingest_chunk_progress
            ADD COLUMN IF NOT EXISTS chunk_fingerprint TEXT,
            ADD COLUMN IF NOT EXISTS dispatch JSONB,
            ADD COLUMN IF NOT EXISTS resume_attempts INT NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    """Drop the resume columns from ``ingest_chunk_progress``."""
    op.execute(
        """
        ALTER TABLE ingest_chunk_progress
            DROP COLUMN IF EXISTS resume_attempts,
            DROP COLUMN IF EXISTS dispatch,
            DROP COLUMN IF EXISTS chunk_fingerprint
        """
    )
