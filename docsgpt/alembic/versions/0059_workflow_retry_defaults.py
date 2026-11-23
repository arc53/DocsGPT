"""0059 workflow retry defaults — the retry policy a workflow's nodes inherit.

* ``workflows.retry_defaults``: ``{max_attempts, backoff_seconds, on}``, read
  by every agent and code node that does not set its own ``retry``. NULL
  means no workflow-wide retries.

Idempotent both ways. Downgrade drops the column.

Revision ID: 0059_workflow_retry_defaults
Revises: 0058_continuation_wakes
"""

from alembic import op

revision = "0059_workflow_retry_defaults"
down_revision = "0058_continuation_wakes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the workflow-wide retry defaults."""
    op.execute("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS retry_defaults JSONB")


def downgrade() -> None:
    """Drop the workflow-wide retry defaults."""
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS retry_defaults")
