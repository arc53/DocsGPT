"""Repository for the ``connector_sessions`` table.

Shape notes:

* OAuth connectors (Google Drive, SharePoint, Confluence) write one row
  per ``(user_id, provider)`` with ``server_url = NULL``. The primary
  lookup key post-callback is ``session_token`` (see
  ``complete_oauth`` style routes), so the table has a standalone
  unique constraint on ``session_token``.
* MCP sessions key off ``server_url`` instead — a single user may have
  multiple MCP servers, one row each. The composite unique index
  ``(user_id, COALESCE(server_url, ''), provider)`` makes both patterns
  coexist without collision.
* ``session_data`` remains a catch-all JSONB for driver-specific state
  (tokens that don't fit anywhere else, per-provider scratch data).
  Promoted columns (``session_token``, ``user_email``, ``status``,
  ``token_info``) are the ones route/auth code queries by.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict
from application.storage.db.serialization import PGNativeJSONEncoder


_UPDATABLE_SCALARS = {
    "server_url", "session_token", "user_email", "status", "expires_at",
}
_UPDATABLE_JSONB = {"session_data", "token_info"}


def _jsonb(value: Any) -> Any:
    if value is None:
        return None
    return json.dumps(value, cls=PGNativeJSONEncoder)


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

        Conflict key is ``(user_id, COALESCE(server_url, ''), provider)``
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
                ON CONFLICT (user_id, COALESCE(server_url, ''), provider)
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
            text("SELECT * FROM connector_sessions WHERE user_id = :user_id"),
            {"user_id": user_id},
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
            constraint ``(user_id, COALESCE(server_url, ''), provider)``
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
                ON CONFLICT (user_id, COALESCE(server_url, ''), provider)
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

    def delete_by_session_token(self, session_token: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM connector_sessions WHERE session_token = :token"
            ),
            {"token": session_token},
        )
        return result.rowcount > 0
