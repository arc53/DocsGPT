"""Repository for the ``feedback`` table.

The ``feedback_collection`` global is declared in ``base.py`` but currently
has zero direct call sites in the application code (all feedback writes go
through ``conversation_messages.feedback`` JSONB field on the conversations
collection). The table exists for when feedback is denormalized into its own
rows. This repository provides the append-only insert and basic reads
needed for that future.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict


class FeedbackRepository:
    """Postgres-backed replacement for Mongo ``feedback_collection``."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        conversation_id: str,
        user_id: str,
        question_index: int,
        feedback_text: Optional[str] = None,
    ) -> dict:
        result = self._conn.execute(
            text(
                """
                INSERT INTO feedback (conversation_id, user_id, question_index, feedback_text)
                VALUES (CAST(:conversation_id AS uuid), :user_id, :question_index, :feedback_text)
                RETURNING *
                """
            ),
            {
                "conversation_id": conversation_id,
                "user_id": user_id,
                "question_index": question_index,
                "feedback_text": feedback_text,
            },
        )
        return row_to_dict(result.fetchone())

    def list_for_conversation(self, conversation_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM feedback WHERE conversation_id = CAST(:cid AS uuid) ORDER BY question_index"
            ),
            {"cid": conversation_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]
