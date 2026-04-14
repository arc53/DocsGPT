"""Repository for the ``attachments`` table."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import looks_like_uuid, row_to_dict


_UPDATABLE_SCALARS = {
    "filename", "upload_path", "mime_type", "size",
    "content", "token_count", "openai_file_id", "google_file_uri",
}
_UPDATABLE_JSONB = {"metadata"}


class AttachmentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        user_id: str,
        filename: str,
        upload_path: str,
        *,
        mime_type: Optional[str] = None,
        size: Optional[int] = None,
        content: Optional[str] = None,
        token_count: Optional[int] = None,
        openai_file_id: Optional[str] = None,
        google_file_uri: Optional[str] = None,
        metadata: Any = None,
        legacy_mongo_id: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO attachments (
                    user_id, filename, upload_path, mime_type, size,
                    content, token_count, openai_file_id, google_file_uri,
                    metadata, legacy_mongo_id
                )
                VALUES (
                    :user_id, :filename, :upload_path, :mime_type, :size,
                    :content, :token_count, :openai_file_id, :google_file_uri,
                    CAST(:metadata AS jsonb), :legacy_mongo_id
                )
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "filename": filename,
                "upload_path": upload_path,
                "mime_type": mime_type,
                "size": size,
                "content": content,
                "token_count": token_count,
                "openai_file_id": openai_file_id,
                "google_file_uri": google_file_uri,
                "metadata": json.dumps(metadata) if metadata is not None else None,
                "legacy_mongo_id": legacy_mongo_id,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, attachment_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM attachments WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": attachment_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_any(self, attachment_id: str, user_id: str) -> Optional[dict]:
        """Resolve an attachment by either PG UUID or legacy Mongo ObjectId string."""
        if looks_like_uuid(attachment_id):
            row = self.get(attachment_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(attachment_id, user_id)

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch an attachment by the original Mongo ObjectId string."""
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
        sql = "SELECT * FROM attachments WHERE legacy_mongo_id = :legacy_id"
        params: dict[str, str] = {"legacy_id": legacy_mongo_id}
        if user_id is not None:
            sql += " AND user_id = :user_id"
            params["user_id"] = user_id
        result = self._conn.execute(text(sql), params)
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM attachments WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def update(self, attachment_id: str, user_id: str, fields: dict) -> bool:
        """Partial update. Used by the LLM providers to cache their
        uploaded file IDs (``openai_file_id`` / ``google_file_uri``) so we
        don't re-upload the same blob every call.
        """
        filtered = {
            k: v for k, v in fields.items()
            if k in _UPDATABLE_SCALARS | _UPDATABLE_JSONB
        }
        if not filtered:
            return False
        set_clauses: list[str] = []
        params: dict = {"id": attachment_id, "user_id": user_id}
        for col, val in filtered.items():
            if col in _UPDATABLE_JSONB:
                set_clauses.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = json.dumps(val) if val is not None else None
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        result = self._conn.execute(
            text(
                f"UPDATE attachments SET {', '.join(set_clauses)} "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            params,
        )
        return result.rowcount > 0

    def update_any(self, attachment_id: str, user_id: str, fields: dict) -> bool:
        """Partial update addressed by either PG UUID or legacy Mongo ObjectId.

        Cutover helper used by the LLM provider file-ID caching hot path:
        the attachment dict in hand may carry a UUID (post-cutover shape)
        or an ObjectId-string ``_id`` (legacy). Try the UUID path first
        when the id looks like a UUID; otherwise fall back to the
        ``legacy_mongo_id`` update.
        """
        if looks_like_uuid(attachment_id):
            if self.update(attachment_id, user_id, fields):
                return True
        return self.update_by_legacy_id(attachment_id, fields)

    def update_by_legacy_id(self, legacy_mongo_id: str, fields: dict) -> bool:
        """Like ``update`` but addressed by the Mongo ObjectId string.

        Used by the LLM file-ID caching path which, at dual-write time,
        only has the Mongo ``_id`` in hand (the PG UUID hasn't been
        looked up yet). No user scoping — the ObjectId is itself unique.
        """
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
                params[col] = json.dumps(val) if val is not None else None
            else:
                set_clauses.append(f"{col} = :{col}")
                params[col] = val
        result = self._conn.execute(
            text(
                f"UPDATE attachments SET {', '.join(set_clauses)} "
                "WHERE legacy_mongo_id = :legacy_id"
            ),
            params,
        )
        return result.rowcount > 0
