"""Repository for the ``connector_sessions`` table.

Shape notes:

* OAuth connectors (Google Drive, SharePoint, Confluence) write one row
  per ``(user_id, provider)`` with ``server_url = NULL``. The primary
  lookup key post-callback is ``session_token`` (see
  ``complete_oauth`` style routes), so the table has a standalone
  unique constraint on ``session_token``.
* MCP sessions key off ``server_url`` instead — a single user may have
  multiple MCP servers, one row each. The composite unique index
  ``(user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))``
  makes both patterns coexist, and lets one user connect several accounts
  of the same provider (each row carries its own ``account_label``).
* Every secret lives in ``encrypted_credentials``, written and read only by
  ``docsgpt.connectors.service``; ``token_info`` and the ``tokens`` /
  ``client_info`` keys of ``session_data`` are legacy plaintext that
  migration 0038 moved into it.
* ``session_data`` remains a catch-all JSONB for driver-specific state
  (tokens that don't fit anywhere else, per-provider scratch data).
  Promoted columns (``session_token``, ``user_email``, ``status``,
  ``token_info``) are the ones route/auth code queries by.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid, row_to_dict
from docsgpt.storage.db.serialization import PGNativeJSONEncoder


_UPDATABLE_SCALARS = {
    "server_url", "session_token", "user_email", "status", "expires_at",
    "connector_key", "display_name", "account_label", "auth_kind",
    "encrypted_credentials", "has_refresh_token", "last_error", "last_used_at", "account_name",
}
_UPDATABLE_JSONB = {"session_data", "token_info", "scopes"}


def _jsonb(value: Any) -> Any:
    if value is None:
        return None
    return json.dumps(value, cls=PGNativeJSONEncoder)


def owns_connector_session(session: Optional[dict], user_id: str, provider: Optional[str]) -> bool:
    """Whether ``session`` belongs to ``user_id`` and was issued for ``provider`` (case-insensitive)."""
    return bool(
        session
        and session.get("user_id") == user_id
        and provider
        and (session.get("provider") or "").lower() == provider.lower()
    )


class ConnectorSessionsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        user_id: str,
        provider: str,
        session_data: Optional[dict] = None,
        *,
        server_url: Optional[str] = None,
        session_token: Optional[str] = None,
        user_email: Optional[str] = None,
        status: Optional[str] = None,
        token_info: Optional[dict] = None,
        expires_at: Any = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        """Insert or update a connector session row.

        Conflict key is the account index
        ``(user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))``
        so MCP rows (per-server) and OAuth rows (per-provider) both get
        idempotent upsert semantics.
        """
        result = self._conn.execute(
            text(
                """
                INSERT INTO connector_sessions (
                    user_id, provider, server_url, session_token, user_email,
                    status, token_info, session_data, expires_at, legacy_mongo_id
                )
                VALUES (
                    :user_id, :provider, :server_url, :session_token, :user_email,
                    :status, CAST(:token_info AS jsonb),
                    CAST(:session_data AS jsonb), :expires_at, :legacy_mongo_id
                )
                ON CONFLICT (user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))
                DO UPDATE SET
                    session_token = COALESCE(EXCLUDED.session_token, connector_sessions.session_token),
                    user_email    = COALESCE(EXCLUDED.user_email, connector_sessions.user_email),
                    status        = COALESCE(EXCLUDED.status, connector_sessions.status),
                    token_info    = COALESCE(EXCLUDED.token_info, connector_sessions.token_info),
                    session_data  = EXCLUDED.session_data,
                    expires_at    = COALESCE(EXCLUDED.expires_at, connector_sessions.expires_at)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "provider": provider,
                "server_url": server_url,
                "session_token": session_token,
                "user_email": user_email,
                "status": status,
                "token_info": _jsonb(token_info),
                "session_data": _jsonb(session_data or {}),
                "expires_at": expires_at,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get_by_user_provider(
        self, user_id: str, provider: str, *, server_url: Optional[str] = None,
    ) -> Optional[dict]:
        """Legacy (user_id, provider) lookup, optionally scoped by server_url.

        Kept for OAuth providers that only have one row per user — they
        pass ``server_url=None`` and get the single OAuth row.
        """
        sql = (
            "SELECT * FROM connector_sessions "
            "WHERE user_id = :user_id AND provider = :provider"
        )
        params: dict[str, Any] = {"user_id": user_id, "provider": provider}
        if server_url is not None:
            sql += " AND server_url = :server_url"
            params["server_url"] = server_url
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_session_token(self, session_token: str) -> Optional[dict]:
        """Post-OAuth-callback lookup.

        Every OAuth flow (Google Drive, SharePoint, Confluence) redirects
        back with the ``session_token`` as the only handle; the callback
        route resolves it to the full session row.
        """
        result = self._conn.execute(
            text("SELECT * FROM connector_sessions WHERE session_token = :token"),
            {"token": session_token},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_user_and_server_url(
        self, user_id: str, server_url: str,
    ) -> Optional[dict]:
        """MCP-tool lookup: resolve a session by the MCP server URL."""
        result = self._conn.execute(
            text(
                "SELECT * FROM connector_sessions "
                "WHERE user_id = :user_id AND server_url = :server_url "
                "LIMIT 1"
            ),
            {"user_id": user_id, "server_url": server_url},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None,
    ) -> Optional[dict]:
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM connector_sessions WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM connector_sessions WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def create(
        self,
        user_id: str,
        provider: str,
        *,
        connector_key: str,
        auth_kind: str,
        display_name: Optional[str] = None,
        account_label: Optional[str] = None,
        server_url: Optional[str] = None,
        status: str = "connected",
        encrypted_credentials: Optional[str] = None,
        has_refresh_token: bool = False,
    ) -> Optional[dict]:
        """Insert a connection; return None when that account already exists."""
        result = self._conn.execute(
            text(
                """
                INSERT INTO connector_sessions (
                    user_id, provider, server_url, connector_key, auth_kind, display_name,
                    account_label, status, encrypted_credentials, has_refresh_token, session_data
                )
                VALUES (
                    :user_id, :provider, :server_url, :connector_key, :auth_kind, :display_name,
                    :account_label, :status, :encrypted_credentials, :has_refresh_token, '{}'::jsonb
                )
                ON CONFLICT (user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))
                DO NOTHING
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "provider": provider,
                "server_url": server_url,
                "connector_key": connector_key,
                "auth_kind": auth_kind,
                "display_name": display_name,
                "account_label": account_label,
                "status": status,
                "encrypted_credentials": encrypted_credentials,
                "has_refresh_token": has_refresh_token,
            },
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_account(
        self, user_id: str, provider: str, *, server_url: Optional[str], account_label: Optional[str],
    ) -> Optional[dict]:
        """The connection for one account, matching the account unique index."""
        result = self._conn.execute(
            text(
                "SELECT * FROM connector_sessions WHERE user_id = :user_id AND provider = :provider "
                "AND COALESCE(server_url, '') = COALESCE(:server_url, '') "
                "AND COALESCE(account_label, '') = COALESCE(:account_label, '')"
            ),
            {"user_id": user_id, "provider": provider, "server_url": server_url, "account_label": account_label},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def delete_by_id(self, connection_id: str) -> bool:
        """Delete a connection row. Linked sources and tools keep existing (SET NULL)."""
        if not looks_like_uuid(connection_id):
            return False
        result = self._conn.execute(
            text("DELETE FROM connector_sessions WHERE id = CAST(:id AS uuid)"), {"id": str(connection_id)},
        )
        return result.rowcount > 0

    def get(self, connection_id: str) -> Optional[dict]:
        """Fetch a connection by id, whoever owns it. Callers authorise."""
        if not looks_like_uuid(connection_id):
            return None
        result = self._conn.execute(
            text("SELECT * FROM connector_sessions WHERE id = CAST(:id AS uuid)"),
            {"id": str(connection_id)},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_for_user(self, connection_id: str, user_id: str) -> Optional[dict]:
        """Fetch a connection only when ``user_id`` owns it."""
        row = self.get(connection_id)
        if row is None or row.get("user_id") != user_id:
            return None
        return row

    def get_for_update(self, connection_id: str) -> Optional[dict]:
        """Fetch and row-lock a connection until the transaction ends.

        Token refresh holds this lock so two workers refreshing a rotating
        refresh token (Microsoft, Atlassian) cannot both spend it.
        """
        if not looks_like_uuid(connection_id):
            return None
        result = self._conn.execute(
            text("SELECT * FROM connector_sessions WHERE id = CAST(:id AS uuid) FOR UPDATE"),
            {"id": str(connection_id)},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def resource_counts(self, connection_ids: list[str]) -> dict[str, dict[str, int]]:
        """Number of sources and tools linked to each connection id."""
        ids = [str(i) for i in connection_ids if looks_like_uuid(str(i))]
        counts: dict[str, dict[str, int]] = {i: {"sources": 0, "tools": 0} for i in ids}
        if not ids:
            return counts
        for table, key in (("sources", "sources"), ("user_tools", "tools")):
            result = self._conn.execute(
                text(
                    f"SELECT connection_id, count(*) FROM {table} "
                    "WHERE connection_id = ANY(CAST(:ids AS uuid[])) GROUP BY connection_id"
                ),
                {"ids": ids},
            )
            for connection_id, count in result.fetchall():
                counts[str(connection_id)][key] = int(count)
        return counts

    def list_sources(self, connection_id: str) -> list[dict]:
        """Sources synced from a connection, newest first."""
        result = self._conn.execute(
            text(
                "SELECT id, name, type, date, sync_frequency, metadata, remote_data, user_id, file_path "
                "FROM sources WHERE connection_id = CAST(:id AS uuid) ORDER BY date DESC"
            ),
            {"id": str(connection_id)},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_tools(self, connection_id: str) -> list[dict]:
        """Tools a connection provides, oldest first."""
        result = self._conn.execute(
            text(
                "SELECT * FROM user_tools WHERE connection_id = CAST(:id AS uuid) ORDER BY created_at"
            ),
            {"id": str(connection_id)},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, session_id: str, fields: dict) -> bool:
        """Partial update by PG UUID."""
        filtered = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_SCALARS | _UPDATABLE_JSONB
        }
        if not filtered:
            return False
        set_clauses: list[str] = []
        params: dict = {"id": session_id}
        for col, val in filtered.items():
            if col in _UPDATABLE_JSONB:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = _jsonb(val)
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        set_clauses.append("updated_at = now()")
        result = self._conn.execute(
            text(
                f"UPDATE connector_sessions SET {', '.join(set_clauses)} "
                "WHERE id = CAST(:id AS uuid)"
            ),
            params,
        )
        return result.rowcount > 0

    def update_by_legacy_id(self, legacy_mongo_id: str, fields: dict) -> bool:
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        filtered = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_SCALARS | _UPDATABLE_JSONB
        }
        if not filtered:
            return False
        set_clauses: list[str] = []
        params: dict = {"legacy_id": legacy_mongo_id}
        for col, val in filtered.items():
            if col in _UPDATABLE_JSONB:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = _jsonb(val)
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        result = self._conn.execute(
            text(
                f"UPDATE connector_sessions SET {', '.join(set_clauses)} "
                "WHERE legacy_mongo_id = :legacy_id"
            ),
            params,
        )
        return result.rowcount > 0

    def merge_session_data(
        self,
        user_id: str,
        provider: str,
        server_url: Optional[str],
        patch: dict,
    ) -> dict:
        """Upsert by shallow-merging ``patch`` into ``session_data``.

        Writes ``server_url`` to the scalar column so downstream
        ``get_by_user_and_server_url`` lookups can find the row. If
        ``patch`` still carries a ``"server_url"`` key (legacy callers)
        it is stripped before merging so the scalar column stays the
        single source of truth and we don't duplicate it inside the
        JSONB blob.

        Args:
            user_id: Owner of the session.
            provider: Provider tag (e.g. ``"mcp:<base_url>"`` for MCP).
            server_url: Endpoint to pin the row to. ``None`` is valid
                for single-row-per-user OAuth providers.
            patch: Shallow-merge payload for ``session_data``. Keys
                mapped to ``None`` are *dropped* from the stored doc
                (used by the redirect-URI-mismatch clear path).

        Returns:
            The upserted row as a dict.

        Notes:
            The conflict target matches the table's composite unique
            index ``(user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))``
            so MCP's per-URL rows and OAuth's single-row-per-user rows
            both upsert idempotently.
        """
        # Defensively strip ``server_url`` from ``patch`` — the scalar
        # column is authoritative now. Callers still pass it for
        # backwards compatibility during the transition.
        patch = {k: v for k, v in patch.items() if k != "server_url"}
        set_entries = {k: v for k, v in patch.items() if v is not None}
        drop_keys = [k for k, v in patch.items() if v is None]

        result = self._conn.execute(
            text(
                """
                INSERT INTO connector_sessions (
                    user_id, provider, server_url, session_data
                )
                VALUES (
                    :user_id, :provider, :server_url,
                    CAST(:patch AS jsonb)
                )
                ON CONFLICT (user_id, provider, COALESCE(server_url, ''), COALESCE(account_label, ''))
                DO UPDATE SET
                    server_url   = COALESCE(EXCLUDED.server_url, connector_sessions.server_url),
                    session_data =
                        (connector_sessions.session_data || EXCLUDED.session_data)
                        - CAST(:drop_keys AS text[])
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "provider": provider,
                "server_url": server_url,
                "patch": json.dumps(set_entries),
                "drop_keys": "{" + ",".join(f'"{k}"' for k in drop_keys) + "}",
            },
        )
        return row_to_dict(result.fetchone())

    def delete(
        self, user_id: str, provider: str, *, server_url: Optional[str] = None,
    ) -> bool:
        sql = (
            "DELETE FROM connector_sessions "
            "WHERE user_id = :user_id AND provider = :provider"
        )
        params: dict[str, Any] = {"user_id": user_id, "provider": provider}
        if server_url is not None:
            sql += " AND server_url = :server_url"
            params["server_url"] = server_url
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0

    def delete_by_session_token(self, session_token: str, user_id: str) -> bool:
        """Delete the session behind ``session_token`` only if ``user_id`` owns it."""
        result = self._conn.execute(
            text(
                "DELETE FROM connector_sessions "
                "WHERE session_token = :token AND user_id = :user_id"
            ),
            {"token": session_token, "user_id": user_id},
        )
        return result.rowcount > 0
