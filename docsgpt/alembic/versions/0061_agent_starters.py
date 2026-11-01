"""0061 agent starters — the questions a new chat with an agent offers.

* ``agents.starters``: up to four questions the agent's owner (or an editor)
  writes, shown to anyone who opens a new chat with the agent. A JSON array of
  strings, ``[]`` when there are none; the API trims, dedupes and caps them
  (``docsgpt/api/user/agents/starters.py``), so the column holds no check.

No trigger change: 0060's ``agents_set_updated_at`` compares the whole row
minus the bookkeeping columns, so a new column such as ``starters`` counts as
content and a change to it moves ``updated_at`` (the builders' stale-write
token) without being listed.

No backfill: every existing agent starts with ``[]``. Idempotent both ways.
Downgrade drops the column, and with it the starters.

Revision ID: 0061_agent_starters
Revises: 0060_agent_prompt_preset
"""

from alembic import op

revision = "0061_agent_starters"
down_revision = "0060_agent_prompt_preset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ``agents.starters``, an empty JSON array on every existing agent."""
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS starters JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    """Drop ``agents.starters``; the agents lose their starters."""
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS starters")
