"""Repository for the ``agents`` table.

This is the most complex Phase 2 repository. Covers every write operation
the legacy Mongo code performs on ``agents_collection``:

- create, update, delete
- find by key (API key lookup)
- find by webhook token
- list for user, list templates
- folder assignment
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import agents_table


class AgentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, status: str, **kwargs) -> dict:
        values: dict = {"user_id": user_id, "name": name, "status": status}

        _ALLOWED = {
            "description", "agent_type", "key", "retriever",
            "default_model_id", "incoming_webhook_token",
            "source_id", "prompt_id", "folder_id",
            "chunks", "token_limit", "request_limit",
            "limited_token_mode", "limited_request_mode", "shared",
            "tools", "json_schema", "models",
        }

        for col, val in kwargs.items():
            if col not in _ALLOWED or val is None:
                continue
            if col in ("tools", "json_schema", "models"):
                values[col] = json.dumps(val)
            elif col in ("chunks", "token_limit", "request_limit"):
                values[col] = int(val)
            elif col in ("limited_token_mode", "limited_request_mode", "shared"):
                values[col] = bool(val)
            elif col in ("source_id", "prompt_id", "folder_id"):
                values[col] = str(val)
            else:
                values[col] = val

        stmt = pg_insert(agents_table).values(**values).returning(agents_table)
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def get(self, agent_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": agent_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_by_key(self, key: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE key = :key"),
            {"key": key},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_by_webhook_token(self, token: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE incoming_webhook_token = :token"),
            {"token": token},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def list_templates(self) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE user_id = 'system' ORDER BY name"),
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, agent_id: str, user_id: str, fields: dict) -> bool:
        allowed = {
            "name", "description", "agent_type", "status", "key", "source_id",
            "chunks", "retriever", "prompt_id", "tools", "json_schema", "models",
            "default_model_id", "folder_id", "limited_token_mode", "token_limit",
            "limited_request_mode", "request_limit", "shared",
            "incoming_webhook_token", "last_used_at",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        values: dict = {}
        for col, val in filtered.items():
            if col in ("tools", "json_schema", "models"):
                values[col] = json.dumps(val) if not isinstance(val, str) else val
            elif col in ("source_id", "prompt_id", "folder_id"):
                values[col] = str(val) if val else None
            else:
                values[col] = val
        values["updated_at"] = func.now()

        t = agents_table
        stmt = (
            t.update()
            .where(t.c.id == agent_id)
            .where(t.c.user_id == user_id)
            .values(**values)
        )
        result = self._conn.execute(stmt)
        return result.rowcount > 0

    def delete(self, agent_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM agents WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": agent_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def set_folder(self, agent_id: str, user_id: str, folder_id: Optional[str]) -> None:
        self._conn.execute(
            text(
                """
                UPDATE agents SET folder_id = CAST(:folder_id AS uuid), updated_at = now()
                WHERE id = CAST(:id AS uuid) AND user_id = :user_id
                """
            ),
            {"id": agent_id, "user_id": user_id, "folder_id": folder_id},
        )

    def clear_folder_for_all(self, folder_id: str, user_id: str) -> None:
        """Remove folder assignment from all agents in a folder (used on folder delete)."""
        self._conn.execute(
            text(
                "UPDATE agents SET folder_id = NULL, updated_at = now() "
                "WHERE folder_id = CAST(:folder_id AS uuid) AND user_id = :user_id"
            ),
            {"folder_id": folder_id, "user_id": user_id},
        )
