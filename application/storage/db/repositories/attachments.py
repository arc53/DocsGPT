"""Repository for the ``attachments`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AttachmentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, filename: str, upload_path: str, *,
               mime_type: Optional[str] = None, size: Optional[int] = None,
               legacy_mongo_id: Optional[str] = None) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO attachments
                    (user_id, filename, upload_path, mime_type, size, legacy_mongo_id)
                VALUES
                    (:user_id, :filename, :upload_path, :mime_type, :size, :legacy_mongo_id)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "filename": filename,
                "upload_path": upload_path,
                "mime_type": mime_type,
                "size": size,
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

    def get_by_legacy_id(self, legacy_mongo_id: str, user_id: str | None = None) -> Optional[dict]:
        """Fetch an attachment by the original Mongo ObjectId string."""
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
