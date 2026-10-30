"""0060 agent prompt preset — an agent keeps the ``creative`` / ``strict`` preset.

* ``agents.prompt_preset``: the built-in preset an agent runs with when it has
  no ``prompts`` row. The presets have no row, so ``agents.prompt_id`` (a
  foreign key to ``prompts``) can't hold them; ``default`` stays as both NULL.
* ``agents_prompt_preset_chk``: only ``creative`` or ``strict``.
* ``agents_prompt_preset_exclusive_chk``: NULL whenever ``prompt_id`` is set.

No backfill: no agent could store a preset before this revision. Idempotent
both ways. Downgrade drops the column, so those agents fall back to the
default prompt.

Revision ID: 0060_agent_prompt_preset
Revises: 0059_workflow_retry_defaults
"""

from alembic import op

revision = "0060_agent_prompt_preset"
down_revision = "0059_workflow_retry_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the agent prompt preset and its two checks."""
    op.execute("ALTER TABLE agents ADD COLUMN IF NOT EXISTS prompt_preset TEXT")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_chk")
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_prompt_preset_chk "
        "CHECK (prompt_preset IN ('creative', 'strict'))"
    )
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_exclusive_chk")
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_prompt_preset_exclusive_chk "
        "CHECK (prompt_id IS NULL OR prompt_preset IS NULL)"
    )


def downgrade() -> None:
    """Drop the agent prompt preset; its agents run the default prompt."""
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_exclusive_chk")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_chk")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS prompt_preset")
