"""0060 agent prompt preset — an agent keeps the ``creative`` / ``strict`` preset.

* ``agents.prompt_preset``: the built-in preset an agent runs with when it has
  no ``prompts`` row. The presets have no row, so ``agents.prompt_id`` (a
  foreign key to ``prompts``) can't hold them; ``default`` stays as both NULL.
* ``agents_prompt_preset_chk``: only ``creative`` or ``strict``.
* ``agents_prompt_preset_exclusive_chk``: NULL whenever ``prompt_id`` is set.

* ``agents_tools_gin_idx`` and ``agents_extra_source_ids_gin_idx``: GIN
  indexes for the Workspace ``used_by`` lookups (``agents.tools ?| ids``,
  ``agents.extra_source_ids && ids``).
* ``workflow_node_refs(config, key)``: the lower-case tool (``key`` =
  ``tools``) or source (``sources``) ids a workflow node's config names, read
  from ``config.config`` when that is an object, else ``config``, like the
  engine reads a node's settings; a lone id counts as one.
  ``workflow_nodes_tool_refs_gin_idx`` and ``workflow_nodes_source_refs_gin_idx``
  index it over agent nodes, so the ``used_by`` lookup of workflow agents
  doesn't expand every node's config on the instance.
* Tool ids in ``agents.tools`` are lowercased. Agent create and update store
  canonical ids since 2026-09-29; older rows may hold upper-case UUIDs, which
  the ``used_by`` lookup (an exact, lower-case match) would miss. A twin left
  by lowercasing is dropped, keeping the first position; anything that isn't
  a UUID string is kept as it is.
* ``agents_set_updated_at`` fires only when a content column changes. The
  builders send ``updated_at`` back as their stale-write token, so a write of
  bookkeeping alone (``last_used_at`` on every owner chat, a regenerated
  ``key``, the ``incoming_webhook_token``, the share link, the ``slug`` an
  export assigns, the owner's ``folder_id``) must not move it.

No preset backfill: no agent could store a preset before this revision.
Idempotent both ways. Downgrade drops the column, so those agents fall back to
the default prompt, and the indexes, and puts back the trigger that fires on
any change; the lowercased tool ids stay (they are the canonical form).

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


_NODE_REFS_FUNCTION = """
    CREATE OR REPLACE FUNCTION workflow_node_refs(config jsonb, key text) RETURNS text[]
    LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
        SELECT COALESCE(array_agg(lower(r.ref)), '{}'::text[])
        FROM (
            SELECT CASE WHEN jsonb_typeof(config -> 'config') = 'object'
                        THEN config -> 'config' ELSE config END -> key AS v
        ) AS refs
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE jsonb_typeof(refs.v)
                WHEN 'array' THEN refs.v
                WHEN 'string' THEN jsonb_build_array(refs.v)
                WHEN 'number' THEN jsonb_build_array(refs.v)
                ELSE '[]'::jsonb END
        ) AS r(ref)
    $$
"""

#: ``(index, key)`` of the node ref indexes; ``resource_usage`` queries the same expressions.
_NODE_REF_INDEXES = (
    ("workflow_nodes_tool_refs_gin_idx", "tools"),
    ("workflow_nodes_source_refs_gin_idx", "sources"),
)


#: Agent columns whose change alone keeps ``updated_at`` (``AgentsRepository.BOOKKEEPING_COLUMNS``).
_BOOKKEEPING = (
    "ARRAY['updated_at', 'last_used_at', 'key', 'incoming_webhook_token', "
    "'shared', 'shared_token', 'shared_metadata', 'slug', 'folder_id']"
)

_CONTENT_TRIGGER = (
    "CREATE TRIGGER agents_set_updated_at BEFORE UPDATE ON agents FOR EACH ROW "
    f"WHEN ((to_jsonb(OLD) - {_BOOKKEEPING}) IS DISTINCT FROM (to_jsonb(NEW) - {_BOOKKEEPING})) "
    "EXECUTE FUNCTION set_updated_at()"
)

# 0001's trigger: any change moves updated_at.
_ANY_CHANGE_TRIGGER = (
    "CREATE TRIGGER agents_set_updated_at BEFORE UPDATE ON agents FOR EACH ROW "
    "WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION set_updated_at()"
)


def upgrade() -> None:
    """Add the agent prompt preset and its checks, the usage indexes, lowercase tool ids, the content trigger."""
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
    op.execute(_NODE_REFS_FUNCTION)
    for index, key in _NODE_REF_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index} ON workflow_nodes "
            f"USING gin (workflow_node_refs(config, '{key}')) WHERE node_type = 'agent'"
        )
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_CONTENT_TRIGGER)


def downgrade() -> None:
    """Drop the agent prompt preset (its agents run the default prompt), the usage indexes, the content trigger."""
    op.execute("DROP TRIGGER IF EXISTS agents_set_updated_at ON agents")
    op.execute(_ANY_CHANGE_TRIGGER)
    for index, _ in _NODE_REF_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")
    op.execute("DROP FUNCTION IF EXISTS workflow_node_refs(jsonb, text)")
    op.execute("DROP INDEX IF EXISTS agents_extra_source_ids_gin_idx")
    op.execute("DROP INDEX IF EXISTS agents_tools_gin_idx")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_exclusive_chk")
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_prompt_preset_chk")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS prompt_preset")
