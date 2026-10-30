"""Allow durable wakes for unfinished rounds without labeling them as approvals.

Revision ID: 0058_continuation_wakes
Revises: 0057_conversation_labels
"""

from alembic import op

revision = "0058_continuation_wakes"
down_revision = "0057_conversation_labels"
branch_labels = None
depends_on = None

_SOURCES = "'job', 'monitor', 'monitor_paused', 'monitor_expired', 'trigger', 'approval', 'lost'"


def upgrade() -> None:
    """Allow a continuation round to schedule its successor durably."""
    op.execute("ALTER TABLE conversation_wakes DROP CONSTRAINT IF EXISTS conversation_wakes_source_chk")
    op.execute(
        f"ALTER TABLE conversation_wakes ADD CONSTRAINT conversation_wakes_source_chk "
        f"CHECK (source IN ({_SOURCES}, 'continuation'))"
    )


def downgrade() -> None:
    """Retain saved wakes as internal events that the previous schema accepts."""
    op.execute("UPDATE conversation_wakes SET source = 'approval' WHERE source = 'continuation'")
    op.execute("ALTER TABLE conversation_wakes DROP CONSTRAINT IF EXISTS conversation_wakes_source_chk")
    op.execute(
        f"ALTER TABLE conversation_wakes ADD CONSTRAINT conversation_wakes_source_chk CHECK (source IN ({_SOURCES}))"
    )
