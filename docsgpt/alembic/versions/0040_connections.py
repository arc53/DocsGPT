"""0040 connections — connector_sessions becomes the connections table.

``connector_sessions`` already holds one row per signed-in account (OAuth
ingest providers) or per MCP server. This migration names what each row is
and lets sources and tools point at the row they use:

* ``connector_key`` is the catalog entry (``google_drive``, ``custom_mcp``,
  ``telegram``), ``auth_kind`` how the row signs in, ``display_name`` and
  ``account_label`` what the Connectors page shows.
* ``sources.connection_id`` and ``user_tools.connection_id`` link the
  resources a connection feeds. ``ON DELETE SET NULL`` keeps a source's
  indexed content when its connection is removed.

Connections own their credentials. Every secret of a connection (OAuth
tokens, MCP OAuth tokens and the dynamic client registration, API keys)
moves into ``encrypted_credentials``, a v2 envelope from
``docsgpt.security.encryption`` bound to the owner. Plain columns
(``status``, ``has_refresh_token``, ``scopes``, ``expires_at``) keep status
checks from ever decrypting. The unique index gains ``account_label`` so one
user can connect several accounts of the same service, and
``credential_mode`` says whose account a shared tool or source uses.

Backfill (idempotent, only fills NULLs or unconverted rows):

1. ``connector_key``, ``auth_kind``, ``display_name`` from ``provider``.
2. ``account_label`` from ``user_email`` for OAuth rows.
3. ``sources.connection_id`` for ``connector:file`` sources, matched to the
   owner's only row for ``remote_data->>'provider'``.
4. ``user_tools.connection_id`` for OAuth MCP tools, matched to the owner's
   row for the tool's server base URL.
5. API-key tools (Brave, Telegram, ntfy, PostgreSQL, custom MCP with a key,
   bearer token or basic auth) get one connection per distinct credential,
   re-encrypted into v2. The tool keeps its v1 copy for one release so a
   rollback still works; the executor prefers the connection. Downgrade
   writes a v1 copy back to every tool on an API-key connection, including
   tools added after the upgrade.
6. ``token_info`` and the secret parts of ``session_data`` (``tokens``,
   ``client_info``) are encrypted into ``encrypted_credentials`` and removed
   from the plaintext columns. This needs ``ENCRYPTION_SECRET_KEY`` set to
   the value the app will run with. Downgrade decrypts them back.
7. ``credential_mode`` is ``owner`` everywhere except OAuth MCP tools, which
   resolved each invoking member's own token before this migration and keep
   doing so (``member``); owners can switch them in the share dialog.

``connector_policies`` holds the admin's per-connector switches (enabled,
forced credential mode). ``enabled`` NULL means the default: on when the
connector has the server settings it needs, off (and hidden from members)
until then. The instance-wide "Allow custom MCP servers" switch
is the ``connectors.allow_custom_mcp`` key in ``app_metadata`` (absent means
allowed).

Revision ID: 0040_connections
Revises: 0039_resource_sponsors
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0040_connections"
down_revision: Union[str, None] = "0039_resource_sponsors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OAUTH_PROVIDERS = {
    "google_drive": "Google Drive",
    "share_point": "SharePoint",
    "confluence": "Confluence",
}


_TOOL_CONNECTORS = {
    "brave": "Brave Search",
    "telegram": "Telegram",
    "ntfy": "ntfy",
    "postgres": "PostgreSQL",
}
_MCP_SECRET_AUTH = ("api_key", "bearer", "basic")
_BATCH = 500


def upgrade() -> None:
    _upgrade_links()
    _upgrade_credentials()
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS connector_policies (
            connector_key   TEXT PRIMARY KEY,
            enabled         BOOLEAN,
            credential_mode TEXT NOT NULL DEFAULT 'choose'
                CONSTRAINT connector_policies_credential_mode_chk
                CHECK (credential_mode IN ('choose', 'owner', 'member')),
            updated_by      TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )


def _upgrade_links() -> None:
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


def _credential_hint(credentials: dict) -> str:
    """``…abcd``: the last four characters of the first secret, never more."""
    for value in credentials.values():
        if isinstance(value, str) and len(value) >= 8:
            return "\u2026" + value[-4:]
    return "\u2026"


def _upgrade_credentials() -> None:
    op.execute(
        """
        ALTER TABLE connector_sessions
            ADD COLUMN IF NOT EXISTS encrypted_credentials TEXT,
            ADD COLUMN IF NOT EXISTS has_refresh_token BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS scopes            JSONB   NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS last_error        TEXT,
            ADD COLUMN IF NOT EXISTS last_used_at      TIMESTAMPTZ;
        """
    )
    for table in ("sources", "user_tools"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS credential_mode TEXT NOT NULL DEFAULT 'owner' "
            f"CONSTRAINT {table}_credential_mode_chk CHECK (credential_mode IN ('owner', 'member'));"
        )
    op.execute("DROP INDEX IF EXISTS connector_sessions_user_endpoint_uidx;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS connector_sessions_account_uidx ON connector_sessions "
        "(user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''));"
    )

    # Statuses become connected / pending / reconnect_needed / disconnected /
    # error. MCP rows never had one; name them before their tokens are sealed.
    op.execute("UPDATE connector_sessions SET status = 'connected' WHERE status = 'authorized';")
    op.execute(
        """
        UPDATE connector_sessions SET status =
            CASE WHEN session_data ? 'tokens' THEN 'connected' ELSE 'pending' END
        WHERE provider LIKE 'mcp:%' AND status IS NULL;
        """
    )

    bind = op.get_bind()
    _encrypt_session_secrets(bind)
    _link_api_key_tools(bind)

    # 7: keep OAuth MCP tools on each member's own token, as before.
    op.execute(
        """
        UPDATE user_tools SET credential_mode = 'member'
        WHERE name = 'mcp_tool' AND config->>'auth_type' = 'oauth';
        """
    )


def _encrypt_session_secrets(bind) -> None:
    """6: move plaintext tokens into the owner-bound v2 envelope."""
    import json

    from sqlalchemy import text

    from docsgpt.security.encryption import encrypt_json

    while True:
        rows = bind.execute(
            text(
                """
                SELECT id, user_id, token_info, session_data FROM connector_sessions
                WHERE encrypted_credentials IS NULL
                  AND (token_info IS NOT NULL OR session_data ? 'tokens' OR session_data ? 'client_info')
                LIMIT :batch
                """
            ),
            {"batch": _BATCH},
        ).fetchall()
        if not rows:
            return
        for row in rows:
            token_info = row.token_info if isinstance(row.token_info, dict) else None
            session_data = dict(row.session_data or {})
            secrets = {}
            if token_info:
                secrets["token_info"] = token_info
            for key in ("tokens", "client_info"):
                if key in session_data:
                    secrets[key] = session_data.pop(key)
            tokens = secrets.get("tokens") if isinstance(secrets.get("tokens"), dict) else {}
            has_refresh = bool((token_info or {}).get("refresh_token") or tokens.get("refresh_token"))
            scopes = (token_info or {}).get("scopes") or []
            if isinstance(scopes, str):
                scopes = scopes.split()
            bind.execute(
                text(
                    """
                    UPDATE connector_sessions SET
                        encrypted_credentials = :blob,
                        has_refresh_token = :has_refresh,
                        scopes = CAST(:scopes AS jsonb),
                        token_info = NULL,
                        session_data = CAST(:session_data AS jsonb)
                    WHERE id = :id
                    """
                ),
                {
                    "blob": encrypt_json(secrets, row.user_id),
                    "has_refresh": has_refresh,
                    "scopes": json.dumps(list(scopes)),
                    "session_data": json.dumps(session_data),
                    "id": row.id,
                },
            )


def _link_api_key_tools(bind) -> None:
    """5: one connection per distinct API credential, linked from its tools."""
    from urllib.parse import urlparse

    from sqlalchemy import text

    from docsgpt.security.encryption import (
        CredentialDecryptionError,
        decrypt_credentials,
        decrypt_json,
        encrypt_json,
    )

    rows = bind.execute(
        text(
            """
            SELECT id, user_id, name, custom_name, display_name, config FROM user_tools
            WHERE connection_id IS NULL
              AND config ? 'encrypted_credentials'
              AND (
                name = ANY(:names)
                OR (name = 'mcp_tool' AND config->>'auth_type' = ANY(:mcp_auth))
              )
            """
        ),
        {"names": list(_TOOL_CONNECTORS), "mcp_auth": list(_MCP_SECRET_AUTH)},
    ).fetchall()
    for row in rows:
        config = row.config or {}
        credentials = decrypt_credentials(config.get("encrypted_credentials") or "", row.user_id)
        if not credentials:
            # Written with a different key; the tool keeps its v1 copy.
            continue
        if row.name == "mcp_tool":
            parsed = urlparse(config.get("server_url") or "")
            server_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None
            connector_key = "custom_mcp"
            display_name = row.custom_name or row.display_name or parsed.netloc or "MCP server"
        else:
            server_url = None
            connector_key = row.name
            display_name = _TOOL_CONNECTORS[row.name]
        # The hint is not an identity: reuse a connection only when it holds
        # the same credentials, and give a different key its own label.
        hint = _credential_hint(credentials)
        label, suffix = hint, 1
        while True:
            existing = bind.execute(
                text(
                    """
                    SELECT id, encrypted_credentials FROM connector_sessions
                    WHERE user_id = :user_id AND provider = :provider
                      AND COALESCE(server_url, '') = COALESCE(:server_url, '')
                      AND COALESCE(account_label, '') = :label
                    """
                ),
                {"user_id": row.user_id, "provider": connector_key, "server_url": server_url, "label": label},
            ).fetchone()
            if existing is None:
                break
            try:
                stored = decrypt_json(existing.encrypted_credentials or "", row.user_id).get("credentials")
            except CredentialDecryptionError:
                stored = None
            if stored == credentials:
                break
            suffix += 1
            label = f"{hint} ({suffix})"
        if existing is None:
            connection_id = bind.execute(
                text(
                    """
                    INSERT INTO connector_sessions (
                        user_id, provider, server_url, connector_key, display_name, account_label,
                        auth_kind, status, encrypted_credentials, session_data
                    ) VALUES (
                        :user_id, :provider, :server_url, :provider, :display_name, :label,
                        'api_key', 'connected', :blob, '{}'::jsonb
                    ) RETURNING id
                    """
                ),
                {
                    "user_id": row.user_id,
                    "provider": connector_key,
                    "server_url": server_url,
                    "display_name": display_name,
                    "label": label,
                    "blob": encrypt_json({"credentials": credentials}, row.user_id),
                },
            ).scalar()
        else:
            connection_id = existing.id
        bind.execute(
            text("UPDATE user_tools SET connection_id = :cid WHERE id = :id"),
            {"cid": connection_id, "id": row.id},
        )


def _downgrade_credentials() -> None:
    """Decrypt the envelopes back into the pre-0038 plaintext columns."""

    from sqlalchemy import text


    bind = op.get_bind()
    has_envelope = bind.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'connector_sessions' AND column_name = 'encrypted_credentials'"
        )
    ).first()
    if has_envelope is not None:
        _decrypt_back(bind)
    _restore_account_index()


def _decrypt_back(bind) -> None:
    import json

    from sqlalchemy import text

    from docsgpt.security.encryption import CredentialDecryptionError, decrypt_json, encrypt_credentials

    # API-key connections go away, so their tools get a v1 copy back: tools
    # added after the upgrade never had one, and a reconnect may have changed
    # the key since the backfill.
    linked = bind.execute(
        text(
            "SELECT t.id, t.user_id, c.encrypted_credentials FROM user_tools t "
            "JOIN connector_sessions c ON c.id = t.connection_id "
            "WHERE c.auth_kind = 'api_key' AND c.encrypted_credentials IS NOT NULL"
        )
    ).fetchall()
    for row in linked:
        try:
            credentials = decrypt_json(row.encrypted_credentials, row.user_id).get("credentials")
        except CredentialDecryptionError:
            continue
        if not credentials:
            continue
        bind.execute(
            text(
                "UPDATE user_tools SET config = COALESCE(config, '{}'::jsonb) "
                "|| jsonb_build_object('encrypted_credentials', CAST(:blob AS text)) WHERE id = :id"
            ),
            {"blob": encrypt_credentials(credentials, row.user_id), "id": row.id},
        )
    bind.execute(text("UPDATE user_tools SET connection_id = NULL WHERE connection_id IN "
                      "(SELECT id FROM connector_sessions WHERE auth_kind = 'api_key')"))
    bind.execute(text("DELETE FROM connector_sessions WHERE auth_kind = 'api_key'"))
    rows = bind.execute(
        text(
            "SELECT id, user_id, session_data, encrypted_credentials FROM connector_sessions "
            "WHERE encrypted_credentials IS NOT NULL"
        )
    ).fetchall()
    for row in rows:
        try:
            secrets = decrypt_json(row.encrypted_credentials, row.user_id)
        except CredentialDecryptionError:
            continue
        session_data = dict(row.session_data or {})
        for key in ("tokens", "client_info"):
            if key in secrets:
                session_data[key] = secrets[key]
        bind.execute(
            text(
                "UPDATE connector_sessions SET token_info = CAST(:token_info AS jsonb), "
                "session_data = CAST(:session_data AS jsonb) WHERE id = :id"
            ),
            {
                "token_info": json.dumps(secrets["token_info"]) if "token_info" in secrets else None,
                "session_data": json.dumps(session_data),
                "id": row.id,
            },
        )


def _restore_account_index() -> None:
    # Several accounts per provider cannot survive the old unique index: keep
    # the most recently updated one.
    op.execute(
        """
        DELETE FROM connector_sessions c USING connector_sessions newer
        WHERE c.user_id = newer.user_id AND c.provider = newer.provider
          AND COALESCE(c.server_url, '') = COALESCE(newer.server_url, '')
          AND (c.updated_at, c.id) < (newer.updated_at, newer.id);
        """
    )
    op.execute("DROP INDEX IF EXISTS connector_sessions_account_uidx;")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS connector_sessions_user_endpoint_uidx "
        "ON connector_sessions (user_id, COALESCE(server_url, ''), provider);"
    )
    for table in ("sources", "user_tools"):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS credential_mode;")
    op.execute(
        """
        ALTER TABLE connector_sessions
            DROP COLUMN IF EXISTS last_used_at,
            DROP COLUMN IF EXISTS last_error,
            DROP COLUMN IF EXISTS scopes,
            DROP COLUMN IF EXISTS has_refresh_token,
            DROP COLUMN IF EXISTS encrypted_credentials;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS connector_policies;")
    _downgrade_credentials()
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
