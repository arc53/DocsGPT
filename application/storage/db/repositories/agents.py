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

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AgentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, name: str, status: str, **kwargs) -> dict:
        cols = ["user_id", "name", "status"]
        vals = [":user_id", ":name", ":status"]
        params: dict = {"user_id": user_id, "name": name, "status": status}

        _TEXT_COLS = {"description", "agent_type", "key", "retriever",
                      "default_model_id", "incoming_webhook_token"}
        _UUID_COLS = {"source_id", "prompt_id", "folder_id"}
        _INT_COLS = {"chunks", "token_limit", "request_limit"}
        _BOOL_COLS = {"limited_token_mode", "limited_request_mode", "shared"}
        _JSONB_COLS = {"tools", "json_schema", "models"}

        for col in _TEXT_COLS:
            if col in kwargs and kwargs[col] is not None:
                cols.append(col)
                vals.append(f":{col}")
                params[col] = kwargs[col]
        for col in _UUID_COLS:
            if col in kwargs and kwargs[col] is not None:
                cols.append(col)
                vals.append(f"CAST(:{col} AS uuid)")
                params[col] = str(kwargs[col])
        for col in _INT_COLS:
            if col in kwargs and kwargs[col] is not None:
                cols.append(col)
                vals.append(f":{col}")
                params[col] = int(kwargs[col])
        for col in _BOOL_COLS:
            if col in kwargs:
                cols.append(col)
                vals.append(f":{col}")
                params[col] = bool(kwargs[col])
        for col in _JSONB_COLS:
            if col in kwargs and kwargs[col] is not None:
                cols.append(col)
                vals.append(f"CAST(:{col} AS jsonb)")
                params[col] = json.dumps(kwargs[col])

        sql = f"INSERT INTO agents ({', '.join(cols)}) VALUES ({', '.join(vals)}) RETURNING *"
        result = self._conn.execute(text(sql), params)
        return row_to_dict(result.fetchone())

    def get(self, agent_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE id = CAST(:id AS uuid)"),
            {"id": agent_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_for_user(self, agent_id: str, user_id: str) -> Optional[dict]:
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

        set_clauses = []
        params: dict = {"id": agent_id, "user_id": user_id}
        for col, val in filtered.items():
            if col in ("tools", "json_schema", "models"):
                set_clauses.append(f"{col} = CAST(:val_{col} AS jsonb)")
                params[f"val_{col}"] = json.dumps(val) if not isinstance(val, str) else val
            elif col in ("source_id", "prompt_id", "folder_id"):
                set_clauses.append(f"{col} = CAST(:val_{col} AS uuid)")
                params[f"val_{col}"] = str(val) if val else None
            else:
                set_clauses.append(f"{col} = :val_{col}")
                params[f"val_{col}"] = val
        set_clauses.append("updated_at = now()")
        sql = f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
        result = self._conn.execute(text(sql), params)
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
