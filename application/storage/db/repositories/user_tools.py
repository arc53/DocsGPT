"""Repository for the ``user_tools`` table.

Covers every operation the legacy Mongo code performs on
``user_tools_collection``:

1. ``find`` by user in tools/routes.py and base.py (list all / active)
2. ``find_one`` by id in tools/routes.py and sharing.py (get single)
3. ``insert_one`` in tools/routes.py and mcp.py (create)
4. ``update_one`` in tools/routes.py and mcp.py (update fields)
5. ``delete_one`` in tools/routes.py (delete)
6. ``find`` by user+status in stream_processor.py and tool_executor.py (active tools)
7. ``find_one`` by user+name in mcp.py (upsert check)
"""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import looks_like_uuid, row_to_dict


_JSONB_COLUMNS = {"config", "config_requirements", "actions"}
_SCALAR_COLUMNS = {"name", "custom_name", "display_name", "description", "status"}
_ALLOWED_COLUMNS = _SCALAR_COLUMNS | _JSONB_COLUMNS


def _encode_jsonb(value: Any) -> Any:
    """Serialize a Python value for a JSONB bind parameter.

    Accepts ``None``, already-encoded strings, or Python dict/list. Returns a
    JSON string suitable for ``CAST(:x AS jsonb)``.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


class UserToolsRepository:
    """Postgres-backed replacement for Mongo ``user_tools_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        name: str,
        *,
        config: Optional[dict] = None,
        custom_name: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        config_requirements: Optional[dict] = None,
        actions: Optional[list] = None,
        status: bool = True,
        extra: Optional[dict] = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        """Insert a new tool row. ``extra`` is merged into the config JSONB."""
        cfg = config or {}
        if extra:
            cfg.update(extra)
        result = self._conn.execute(
            text(
                """
                INSERT INTO user_tools (
                    user_id, name, custom_name, display_name, description,
                    config, config_requirements, actions, status, legacy_mongo_id
                )
                VALUES (
                    :user_id, :name, :custom_name, :display_name, :description,
                    CAST(:config AS jsonb),
                    CAST(:config_requirements AS jsonb),
                    CAST(:actions AS jsonb),
                    :status, :legacy_mongo_id
                )
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "custom_name": custom_name,
                "display_name": display_name,
                "description": description,
                "config": json.dumps(cfg),
                "config_requirements": _encode_jsonb(config_requirements or {}),
                "actions": _encode_jsonb(actions or []),
                "status": status,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, tool_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM user_tools WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": tool_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Fetch a user_tool by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM user_tools WHERE legacy_mongo_id = :legacy_id"
        params: dict = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_any(self, tool_id: str, user_id: str) -> Optional[dict]:
        """Resolve a user_tool by PG UUID or legacy Mongo ObjectId string.

        Cutover helper: route handlers may receive either shape from
        older clients. Always returns a row scoped to ``user_id``.
        """
        if looks_like_uuid(tool_id):
            row = self.get(tool_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(tool_id, user_id)

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM user_tools WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_active_for_user(self, user_id: str) -> list[dict]:
        """Return only tools with ``status = true`` — matches the legacy
        ``find({"user": user, "status": True})`` used by the answer pipeline."""
        result = self._conn.execute(
            text(
                "SELECT * FROM user_tools "
                "WHERE user_id = :user_id AND status = true "
                "ORDER BY created_at"
            ),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def find_by_user_and_name(self, user_id: str, name: str) -> Optional[dict]:
        """Used by the MCP save flow to decide between insert and update."""
        result = self._conn.execute(
            text(
                "SELECT * FROM user_tools "
                "WHERE user_id = :user_id AND name = :name "
                "LIMIT 1"
            ),
            {"user_id": user_id, "name": name},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def update(self, tool_id: str, user_id: str, fields: dict) -> bool:
        """Update arbitrary fields on a tool row.

        ``fields`` maps column names to new values. Only columns in
        ``_ALLOWED_COLUMNS`` are honored; unknown keys are silently dropped
        to keep route handlers from accidentally leaking DB shape. JSONB
        values are accepted as dicts/lists and serialized here.

        Returns ``True`` if the row was updated, ``False`` if the id/user
        didn't match anything.
        """
        filtered = {k: v for k, v in fields.items() if k in _ALLOWED_COLUMNS}
        if not filtered:
            return False

        set_clauses: list[str] = []
        params: dict = {"id": tool_id, "user_id": user_id}
        for col, val in filtered.items():
            if col not in _ALLOWED_COLUMNS:
                raise ValueError(f"disallowed column: {col!r}")
            if col in _JSONB_COLUMNS:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = _encode_jsonb(val)
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        set_clauses.append("updated_at = now()")

        result = self._conn.execute(
            text(
                f"""
                UPDATE user_tools
                SET {", ".join(set_clauses)}
                WHERE id = CAST(:id AS uuid) AND user_id = :user_id
                """
            ),
            params,
        )
        return result.rowcount > 0

    def delete(self, tool_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM user_tools WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": tool_id, "user_id": user_id},
        )
        return result.rowcount > 0
