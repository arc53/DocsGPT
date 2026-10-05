"""Repository for the ``user_tool_preferences`` table.

A grantee's personal "In my chats" switch for a tool shared with them. The
owner's own switch stays in ``user_tools.status``; a missing row here means
off, so sharing a tool never adds it to anyone's chats.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import Connection, text

from docsgpt.storage.db.base_repository import looks_like_uuid


class UserToolPreferencesRepository:
    """Per-user, per-tool chat preferences for shared tools."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def set_in_chat(self, user_id: str, tool_id: str, in_chat: bool) -> None:
        """Upsert the caller's "In my chats" switch for one tool.

        Args:
            user_id: The grantee's user id.
            tool_id: The shared tool's UUID.
            in_chat: Whether the tool joins the grantee's agentless chats.
        """
        self._conn.execute(
            text(
                """
                INSERT INTO user_tool_preferences (user_id, tool_id, in_chat)
                VALUES (:user_id, CAST(:tool_id AS uuid), :in_chat)
                ON CONFLICT (user_id, tool_id)
                DO UPDATE SET in_chat = EXCLUDED.in_chat, updated_at = now()
                """
            ),
            {"user_id": user_id, "tool_id": str(tool_id), "in_chat": bool(in_chat)},
        )

    def in_chat_many(self, user_id: str, tool_ids: Iterable[str]) -> dict[str, bool]:
        """``tool_id -> in_chat`` for the given tools; missing rows are False.

        Args:
            user_id: The grantee's user id.
            tool_ids: Tool ids to look up (non-UUIDs are ignored).

        Returns:
            A dict with one entry per UUID-shaped input id.
        """
        ids = [str(t) for t in tool_ids if looks_like_uuid(str(t))]
        out = {tid: False for tid in ids}
        if not ids or not user_id:
            return out
        rows = self._conn.execute(
            text(
                """
                SELECT tool_id, in_chat FROM user_tool_preferences
                WHERE user_id = :user_id AND tool_id = ANY(CAST(:ids AS uuid[]))
                """
            ),
            {"user_id": user_id, "ids": ids},
        ).fetchall()
        for tool_id, in_chat in rows:
            out[str(tool_id)] = bool(in_chat)
        return out

    def list_in_chat_tool_ids(self, user_id: str) -> list[str]:
        """Ids of tools the user switched into their chats (any owner).

        Args:
            user_id: The grantee's user id.

        Returns:
            Tool ids as strings; access must still be re-checked by the caller.
        """
        if not user_id:
            return []
        rows = self._conn.execute(
            text(
                """
                SELECT tool_id FROM user_tool_preferences
                WHERE user_id = :user_id AND in_chat = true
                ORDER BY updated_at
                """
            ),
            {"user_id": user_id},
        ).fetchall()
        return [str(r[0]) for r in rows]
