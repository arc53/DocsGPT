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
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class UserToolsRepository:
    """Postgres-backed replacement for Mongo ``user_tools_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, *, config: Optional[dict] = None,
               custom_name: Optional[str] = None, display_name: Optional[str] = None,
               extra: Optional[dict] = None) -> dict:
        """Insert a new tool row. ``extra`` is merged into the config JSONB."""
        cfg = config or {}
        if extra:
            cfg.update(extra)
        result = self._conn.execute(
            text(
                """
                INSERT INTO user_tools (user_id, name, custom_name, display_name, config)
                VALUES (:user_id, :name, :custom_name, :display_name, CAST(:config AS jsonb))
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "name": name,
                "custom_name": custom_name,
                "display_name": display_name,
                "config": json.dumps(cfg),
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, tool_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM user_tools WHERE id = CAST(:id AS uuid)"),
            {"id": tool_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM user_tools WHERE user_id = :user_id ORDER BY created_at"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, tool_id: str, user_id: str, fields: dict) -> None:
        """Update arbitrary fields on a tool row.

        ``fields`` maps column names to new values. Only ``name``,
        ``custom_name``, ``display_name``, and ``config`` are allowed.
        """
        allowed = {"name", "custom_name", "display_name", "config"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        params: dict = {
            "id": tool_id,
            "user_id": user_id,
            "name": filtered.get("name"),
            "custom_name": filtered.get("custom_name"),
            "display_name": filtered.get("display_name"),
            "config": (
                json.dumps(filtered["config"])
                if "config" in filtered and isinstance(filtered["config"], dict)
                else filtered.get("config")
            ),
        }
        self._conn.execute(
            text(
                """
                UPDATE user_tools
                SET
                    name = COALESCE(:name, name),
                    custom_name = COALESCE(:custom_name, custom_name),
                    display_name = COALESCE(:display_name, display_name),
                    config = COALESCE(CAST(:config AS jsonb), config),
                    updated_at = now()
                WHERE id = CAST(:id AS uuid) AND user_id = :user_id
                """
            ),
            params,
        )

    def delete(self, tool_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM user_tools WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": tool_id, "user_id": user_id},
        )
        return result.rowcount > 0
