"""0019 agent slug — stable per-user identifier for YAML export/import.

Adds ``agents.slug`` (CITEXT) plus a partial unique index on
``(user_id, slug)`` where slug is not null, so an exported agent can be
re-imported idempotently (and mapped from a repo file for GitOps) while
still allowing multiple agents to carry NULL. Idempotent both ways.

Revision ID: 0019_agent_slug
Revises: 0018_tool_attempts_attribution
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0019_agent_slug"
down_revision: Union[str, None] = "0018_tool_attempts_attribution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS slug CITEXT;")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_user_slug
            ON agents (user_id, slug)
            WHERE slug IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_agents_user_slug;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS slug;")
