"""0038 connections — connector_sessions becomes the connections table.

``connector_sessions`` already holds one row per signed-in account (OAuth
ingest providers) or per MCP server. This migration names what each row is
and lets sources and tools point at the row they use:

* ``connector_key`` is the catalog entry (``google_drive``, ``custom_mcp``,
  ``telegram``), ``auth_kind`` how the row signs in, ``display_name`` and
  ``account_label`` what the Connectors page shows.
* ``sources.connection_id`` and ``user_tools.connection_id`` link the
  resources a connection feeds. ``ON DELETE SET NULL`` keeps a source's
  indexed content when its connection is removed.

Backfill (idempotent, only fills NULLs):

1. ``connector_key``, ``auth_kind``, ``display_name`` from ``provider``.
2. ``account_label`` from ``user_email`` for OAuth rows.
3. ``sources.connection_id`` for ``connector:file`` sources, matched to the
   owner's only row for ``remote_data->>'provider'``.
4. ``user_tools.connection_id`` for OAuth MCP tools, matched to the owner's
   row for the tool's server base URL.

Revision ID: 0038_connections
Revises: 0037_request_traces
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0038_connections"
down_revision: Union[str, None] = "0037_request_traces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OAUTH_PROVIDERS = {
    "google_drive": "Google Drive",
    "share_point": "SharePoint",
    "confluence": "Confluence",
}


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE connector_sessions
            ADD COLUMN IF NOT EXISTS connector_key TEXT,
            ADD COLUMN IF NOT EXISTS display_name  TEXT,
            ADD COLUMN IF NOT EXISTS account_label TEXT,
            ADD COLUMN IF NOT EXISTS auth_kind     TEXT,
            ADD COLUMN IF NOT EXISTS updated_at    TIMESTAMPTZ NOT NULL DEFAULT now();
        """
    )
    op.execute(
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS connection_id UUID "
        "REFERENCES connector_sessions(id) ON DELETE SET NULL;"
    )
    op.execute(
        "ALTER TABLE user_tools ADD COLUMN IF NOT EXISTS connection_id UUID "
        "REFERENCES connector_sessions(id) ON DELETE SET NULL;"
    )
    op.execute("CREATE INDEX IF NOT EXISTS sources_connection_idx ON sources (connection_id);")
    op.execute("CREATE INDEX IF NOT EXISTS user_tools_connection_idx ON user_tools (connection_id);")

    # 1 + 2: name the existing rows.
    for provider, name in _OAUTH_PROVIDERS.items():
        op.execute(
            f"""
            UPDATE connector_sessions SET
                connector_key = COALESCE(connector_key, '{provider}'),
                auth_kind     = COALESCE(auth_kind, 'oauth'),
                display_name  = COALESCE(display_name, '{name}'),
                account_label = COALESCE(account_label, user_email)
            WHERE provider = '{provider}';
            """
        )
    op.execute(
        """
        UPDATE connector_sessions SET
            connector_key = COALESCE(connector_key, 'custom_mcp'),
            auth_kind     = COALESCE(auth_kind, 'mcp_oauth'),
            display_name  = COALESCE(
                display_name,
                regexp_replace(COALESCE(server_url, substr(provider, 5)), '^https?://', '')
            )
        WHERE provider LIKE 'mcp:%';
        """
    )

    # 3: connector sources point at the owner's only session for the provider.
    op.execute(
        """
        UPDATE sources s SET connection_id = cs.id
        FROM connector_sessions cs
        WHERE s.connection_id IS NULL
          AND s.type = 'connector:file'
          AND cs.user_id = s.user_id
          AND cs.provider = s.remote_data->>'provider'
          AND (
              SELECT count(*) FROM connector_sessions c2
              WHERE c2.user_id = s.user_id AND c2.provider = cs.provider
          ) = 1;
        """
    )

    # 4: OAuth MCP tools point at the owner's session for the server's base URL.
    op.execute(
        """
        UPDATE user_tools t SET connection_id = cs.id
        FROM connector_sessions cs
        WHERE t.connection_id IS NULL
          AND t.name = 'mcp_tool'
          AND t.config->>'auth_type' = 'oauth'
          AND cs.user_id = t.user_id
          AND cs.provider = 'mcp:' || substring(t.config->>'server_url' from '^(https?://[^/]+)');
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS user_tools_connection_idx;")
    op.execute("DROP INDEX IF EXISTS sources_connection_idx;")
    op.execute("ALTER TABLE user_tools DROP COLUMN IF EXISTS connection_id;")
    op.execute("ALTER TABLE sources DROP COLUMN IF EXISTS connection_id;")
    op.execute(
        """
        ALTER TABLE connector_sessions
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS auth_kind,
            DROP COLUMN IF EXISTS account_label,
            DROP COLUMN IF EXISTS display_name,
            DROP COLUMN IF EXISTS connector_key;
        """
    )
