"""The unread mark on a conversation (``conversations.unread_at``).

Set when a message lands that the owner has not seen (a continuation turn
while they were elsewhere), cleared when they open the conversation. Neither
write touches ``date`` or ``updated_at``, so marking never reorders the sidebar.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid


class ConversationUnreadRepository:
    """Mark a user's conversation unread, or read."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def mark_unread(self, conversation_id: str, user_id: str) -> bool:
        """Mark the conversation unread for its owner.

        Args:
            conversation_id: The conversation.
            user_id: Its owner; another user's id matches nothing.

        Returns:
            True when the owner's conversation was marked.
        """
        if not looks_like_uuid(conversation_id):
            return False
        result = self._conn.execute(
            text(
                "UPDATE conversations SET unread_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        return bool(result.rowcount)

    def mark_read(self, conversation_id: str, user_id: str) -> bool:
        """Clear the unread mark.

        Returns:
            True when there was a mark to clear.
        """
        if not looks_like_uuid(conversation_id):
            return False
        result = self._conn.execute(
            text(
                "UPDATE conversations SET unread_at = NULL "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id AND unread_at IS NOT NULL"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        return bool(result.rowcount)
