"""Repository for the ``agents`` table.

Covers every write operation
the legacy Mongo code performs on ``agents_collection``:

- create, update, delete
- find by key (API key lookup)
- find by webhook token
- list for user, list templates
- folder assignment
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.models import agents_table


class AgentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    @staticmethod
    def _normalize_unique_text(col: str, val):
        """Coerce blank strings for nullable unique text columns to NULL."""
        if col == "key" and val == "":
            return None
        return val

    def create(self, user_id: str, name: str, status: str, **kwargs) -> dict:
        values: dict = {"user_id": user_id, "name": name, "status": status}

        _ALLOWED = {
            "description", "agent_type", "key", "retriever",
            "default_model_id", "incoming_webhook_token",
            "source_id", "prompt_id", "folder_id", "workflow_id",
            "extra_source_ids", "image",
            "chunks", "token_limit", "request_limit",
            "limited_token_mode", "limited_request_mode",
            "allow_system_prompt_override",
            "shared", "shared_token", "shared_metadata",
            "tools", "json_schema", "models", "legacy_mongo_id",
            "created_at", "updated_at", "last_used_at",
        }

        for col, val in kwargs.items():
            if col not in _ALLOWED or val is None:
                continue
            if col in ("tools", "json_schema", "models", "shared_metadata"):
                # JSONB columns: pass the Python object directly. SQLAlchemy
                # Core's JSONB type processor json.dumps it once during
                # bind; pre-serialising would double-encode and the value
                # would round-trip as a JSON string instead of the dict.
                values[col] = val
            elif col in ("chunks", "token_limit", "request_limit"):
                values[col] = int(val)
            elif col in (
                "limited_token_mode", "limited_request_mode",
                "shared", "allow_system_prompt_override",
            ):
                values[col] = bool(val)
            elif col in ("source_id", "prompt_id", "folder_id", "workflow_id"):
                values[col] = str(val)
            elif col == "extra_source_ids":
                # ARRAY(UUID) — pass list of strings; psycopg adapts it.
                values[col] = [str(x) for x in val] if val else []
            else:
                values[col] = self._normalize_unique_text(col, val)

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

    def get_any(self, agent_id: str, user_id: str) -> Optional[dict]:
        """Resolve an agent by either PG UUID or legacy Mongo ObjectId string.

        Cutover helper: URLs / bookmarks / old client state may still hold
        Mongo ObjectId-strings. Try the UUID path first (the post-cutover
        shape) and fall back to ``legacy_mongo_id`` — both are scoped by
        ``user_id`` so cross-user access is impossible.
        """
        if looks_like_uuid(agent_id):
            row = self.get(agent_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(agent_id, user_id)

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch an agent by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM agents WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_by_key(self, key: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM agents WHERE key = :key"),
            {"key": key},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_by_shared_token(self, token: str) -> Optional[dict]:
        """Resolve a publicly-shared agent by its rotating share token.

        Only returns rows with ``shared = true`` so revoking a share
        (setting ``shared = false``) immediately stops token access even
        if the token value itself is still in the row.
        """
        result = self._conn.execute(
            text(
                "SELECT * FROM agents "
                "WHERE shared_token = :token AND shared = true"
            ),
            {"token": token},
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
            "default_model_id", "folder_id", "workflow_id",
            "extra_source_ids", "image",
            "limited_token_mode", "token_limit",
            "limited_request_mode", "request_limit",
            "allow_system_prompt_override",
            "shared", "shared_token", "shared_metadata",
            "incoming_webhook_token", "last_used_at",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        values: dict = {}
        for col, val in filtered.items():
            if col in ("tools", "json_schema", "models", "shared_metadata"):
                # See note in create(): JSONB columns receive Python
                # objects, the type processor handles serialisation.
                values[col] = val
            elif col in ("source_id", "prompt_id", "folder_id", "workflow_id"):
                values[col] = str(val) if val else None
            elif col == "extra_source_ids":
                values[col] = [str(x) for x in val] if val else []
            elif col in (
                "limited_token_mode", "limited_request_mode",
                "shared", "allow_system_prompt_override",
            ):
                values[col] = bool(val)
            else:
                values[col] = self._normalize_unique_text(col, val)
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

    def update_by_legacy_id(self, legacy_mongo_id: str, user_id: str, fields: dict) -> bool:
        """Update an agent addressed by the Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        agent = self.get_by_legacy_id(legacy_mongo_id, user_id)
        if agent is None:
            return False
        return self.update(agent["id"], user_id, fields)

    def delete(self, agent_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text("DELETE FROM agents WHERE id = CAST(:id AS uuid) AND user_id = :user_id"),
            {"id": agent_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete_by_legacy_id(self, legacy_mongo_id: str, user_id: str) -> bool:
        """Delete an agent addressed by the Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        result = self._conn.execute(
            text(
                "DELETE FROM agents "
                "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
            ),
            {"legacy_id": legacy_mongo_id, "user_id": user_id},
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
