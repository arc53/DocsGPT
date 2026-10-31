"""0060 agent prompt preset — an agent keeps the ``creative`` / ``strict`` preset.

* ``agents.prompt_preset``: the built-in preset an agent runs with when it has
  no ``prompts`` row. The presets have no row, so ``agents.prompt_id`` (a
  foreign key to ``prompts``) can't hold them; ``default`` stays as both NULL.
* ``agents_prompt_preset_chk``: only ``creative`` or ``strict``.
* ``agents_prompt_preset_exclusive_chk``: NULL whenever ``prompt_id`` is set.

* ``agents_tools_gin_idx`` and ``agents_extra_source_ids_gin_idx``: GIN
  indexes for the Workspace ``used_by`` lookups (``agents.tools ?| ids``,
  ``agents.extra_source_ids && ids``).
* Tool ids in ``agents.tools`` are lowercased. Agent create and update store
  canonical ids since 2026-09-29; older rows may hold upper-case UUIDs, which
  the ``used_by`` lookup (an exact, lower-case match) would miss. A twin left
  by lowercasing is dropped, keeping the first position; anything that isn't
  a UUID string is kept as it is.

No preset backfill: no agent could store a preset before this revision.
Idempotent both ways. Downgrade drops the column, so those agents fall back to
the default prompt, and the indexes; the lowercased tool ids stay (they are
the canonical form).

Revision ID: 0060_agent_prompt_preset
Revises: 0059_workflow_retry_defaults
"""

from alembic import op

revision = "0060_agent_prompt_preset"
down_revision = "0059_workflow_retry_defaults"
branch_labels = None
depends_on = None


_UUID_RE = "^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"

# Lowercase every UUID string in agents.tools, drop the twins that leaves and
# keep the order; only rows holding an upper-case UUID are rewritten.
_LOWERCASE_TOOL_IDS = f"""
    WITH fixed AS (
        SELECT id, jsonb_agg(entry ORDER BY first_pos) AS tools
        FROM (
            SELECT a.id, e.entry, min(e.pos) AS first_pos
            FROM agents a
            CROSS JOIN LATERAL (
                SELECT CASE WHEN jsonb_typeof(v) = 'string' AND (v #>> '{{}}') ~ '{_UUID_RE}'
                            THEN to_jsonb(lower(v #>> '{{}}')) ELSE v END AS entry,
                       pos
                FROM jsonb_array_elements(a.tools) WITH ORDINALITY AS t(v, pos)
            ) e
            WHERE jsonb_typeof(a.tools) = 'array'
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements_text(a.tools) AS u(ref)
                  WHERE u.ref ~ '{_UUID_RE}' AND u.ref <> lower(u.ref)
              )
            GROUP BY a.id, e.entry
        ) entries
        GROUP BY id
    )
    UPDATE agents SET tools = fixed.tools FROM fixed WHERE agents.id = fixed.id
"""


def upgrade() -> None:
    """Add the agent prompt preset and its two checks, the usage indexes, and lowercase tool ids."""
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
    op.execute("CREATE INDEX IF NOT EXISTS agents_tools_gin_idx ON agents USING gin (tools)")
    op.execute("CREATE INDEX IF NOT EXISTS agents_extra_source_ids_gin_idx ON agents USING gin (extra_source_ids)")
    op.execute(_LOWERCASE_TOOL_IDS)


def downgrade() -> None:
    """Drop the agent prompt preset (its agents run the default prompt) and the usage indexes."""
    op.execute("DROP INDEX IF EXISTS agents_extra_source_ids_gin_idx")
    op.execute("DROP INDEX IF EXISTS agents_tools_gin_idx")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_exclusive_chk")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_chk")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS prompt_preset")
