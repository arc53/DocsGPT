"""0026 stack_logs.agent_id — stable per-agent attribution for activity logs.

``stack_logs`` (webhook + system-error activity logs) previously carried only
the agent's ``api_key`` string, so it could be joined to an agent only through
that key. Now that agents can rotate their key, a key-only join would orphan
history on rotation. This adds a nullable ``agent_id`` UUID (no FK, mirroring
``token_usage.agent_id`` so a stray/legacy id can never block a log write),
indexes it, and backfills existing rows by matching the stored ``api_key`` to
``agents.key``. The backfill is exhaustive today because no key has been
rotated yet. Idempotent both ways.

Revision ID: 0026_stack_logs_agent_id
Revises: 0025_artifacts
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0026_stack_logs_agent_id"
down_revision: Union[str, None] = "0025_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE stack_logs ADD COLUMN IF NOT EXISTS agent_id uuid;")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_stack_logs_agent_id
            ON stack_logs (agent_id)
            WHERE agent_id IS NOT NULL;
        """
    )
    # Backfill from the still-current key mapping. ``agents.key`` is CITEXT and
    # unique, so each api_key resolves to at most one agent.
    op.execute(
        """
        UPDATE stack_logs s
           SET agent_id = a.id
          FROM agents a
         WHERE s.agent_id IS NULL
           AND s.api_key IS NOT NULL
           AND a.key = s.api_key;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_stack_logs_agent_id;")
    op.execute("ALTER TABLE stack_logs DROP COLUMN IF EXISTS agent_id;")
