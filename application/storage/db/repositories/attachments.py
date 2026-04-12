"""Repository for the ``attachments`` table."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class AttachmentsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(self, user_id: str, filename: str, upload_path: str, *,
               mime_type: Optional[str] = None, size: Optional[int] = None) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO attachments (user_id, filename, upload_path, mime_type, size)
                VALUES (:user_id, :filename, :upload_path, :mime_type, :size)
                RETURNING *
                """
            ),
            {
                "user_id": user_id,
                "filename": filename,
                "upload_path": upload_path,
                "mime_type": mime_type,
                "size": size,
            },
        )
        return row_to_dict(result.fetchone())

    def get(self, attachment_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text("SELECT * FROM attachments WHERE id = CAST(:id AS uuid)"),
            {"id": attachment_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str) -> list[dict]:
        result = self._conn.execute(
            text("SELECT * FROM attachments WHERE user_id = :user_id ORDER BY created_at DESC"),
            {"user_id": user_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]
