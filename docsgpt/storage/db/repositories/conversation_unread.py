"""The unread mark on a conversation (``conversations.unread_at``).

Set when a message lands that the owner has not seen (a continuation turn,
or an answer that finished or failed, while they were elsewhere), cleared when they open the conversation. Reading
also stamps ``read_at``, which Activity compares a failed job against: one
that ended before it was seen. Neither write touches ``date`` or
``updated_at``, so marking never reorders the sidebar.
"""

from __future__ import annotations

from typing import Optional

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

    def listed_chat_of_message(self, message_id: str) -> Optional[tuple[str, str]]:
        """The sidebar conversation a message belongs to, and its owner.

        Args:
            message_id: The message.

        Returns:
            ``(conversation_id, user_id)``, or ``None`` when the message is
            unknown or its conversation isn't listed (API, ``/v1`` and agent
            chats have no sidebar row to mark).
        """
        if not looks_like_uuid(message_id):
            return None
        row = self._conn.execute(
            text(
                "SELECT c.id, c.user_id FROM conversation_messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.id = CAST(:id AS uuid) AND c.visibility = 'listed'"
            ),
            {"id": message_id},
        ).fetchone()
        return (str(row[0]), str(row[1])) if row is not None else None

    def mark_read(self, conversation_id: str, user_id: str) -> bool:
        """Clear the unread mark and stamp ``read_at``, unread or not.

        Returns:
            True when there was a mark to clear.
        """
        if not looks_like_uuid(conversation_id):
            return False
        was_unread = self._conn.execute(
            text(
                "UPDATE conversations c SET unread_at = NULL, read_at = now() "
                "FROM (SELECT unread_at FROM conversations "
                "      WHERE id = CAST(:id AS uuid) AND user_id = :user_id FOR UPDATE) before "
                "WHERE c.id = CAST(:id AS uuid) AND c.user_id = :user_id "
                "RETURNING before.unread_at IS NOT NULL"
            ),
            {"id": conversation_id, "user_id": user_id},
        ).scalar()
        return bool(was_unread)
