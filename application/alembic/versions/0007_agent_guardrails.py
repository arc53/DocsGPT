"""0007 agent guardrails columns — adds guardrails_enabled, input_guardrails,
and output_guardrails boolean columns to the agents table.

These columns allow agents to have safety guardrails configured to filter
and validate input and output separately.

Revision ID: 0007_agent_guardrails
Revises: 0006_idempotency_lease
"""
from typing import Sequence, Union
from alembic import op

revision: str = "0007_agent_guardrails"
down_revision: Union[str, None] = "0006_idempotency_lease"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agents
            ADD COLUMN guardrails_enabled  BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN input_guardrails    BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN output_guardrails   BOOLEAN NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agents
            DROP COLUMN IF EXISTS guardrails_enabled,
            DROP COLUMN IF EXISTS input_guardrails,
            DROP COLUMN IF EXISTS output_guardrails;
        """
    )