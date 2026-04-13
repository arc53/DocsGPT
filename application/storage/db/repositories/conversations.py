"""Repository for the ``conversations`` and ``conversation_messages`` tables.

Covers every operation the legacy Mongo code performs on
``conversations_collection``:

- create / get / list / delete conversations
- append message (transactional position allocation)
- update message at index (overwrite + optional truncation)
- set / unset feedback on a message
- rename conversation
- update compression metadata
- shared_with access checks
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import conversations_table, conversation_messages_table


def _message_row_to_dict(row) -> dict:
    """Like ``row_to_dict`` but renames the DB column ``message_metadata``
    back to the public API key ``metadata`` so callers keep the Mongo-era
    shape. See migration 0016 for the column rename rationale."""
    out = row_to_dict(row)
    if "message_metadata" in out:
        out["metadata"] = out.pop("message_metadata")
    return out


class ConversationsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Conversation CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        user_id: str,
        name: str | None = None,
        *,
        agent_id: str | None = None,
        api_key: str | None = None,
        is_shared_usage: bool = False,
        shared_token: str | None = None,
        legacy_mongo_id: str | None = None,
    ) -> dict:
        """Create a new conversation.

        ``legacy_mongo_id`` is used by the dual-write shim so that a
        Postgres row inserted *after* a successful Mongo insert carries
        the Mongo ``_id`` as a lookup key. Subsequent appends/updates
        can then resolve the PG row by that id via
        :meth:`get_by_legacy_id`.
        """
        values: dict = {
            "user_id": user_id,
            "name": name,
        }
        if agent_id:
            values["agent_id"] = agent_id
        if api_key:
            values["api_key"] = api_key
        if is_shared_usage:
            values["is_shared_usage"] = True
        if shared_token:
            values["shared_token"] = shared_token
        if legacy_mongo_id:
            values["legacy_mongo_id"] = legacy_mongo_id

        stmt = pg_insert(conversations_table).values(**values).returning(conversations_table)
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def get_by_legacy_id(
        self, legacy_mongo_id: str, user_id: str | None = None,
    ) -> Optional[dict]:
        """Look up a conversation by the original Mongo ObjectId string.

        Used by the dual-write helpers to translate a Mongo ``_id`` into
        the Postgres UUID for follow-up writes. When ``user_id`` is
        provided, the lookup is scoped to rows owned by that user so
        callers can't accidentally resolve another user's conversation.
        """
        if user_id is not None:
            result = self._conn.execute(
                text(
                    "SELECT * FROM conversations "
                    "WHERE legacy_mongo_id = :legacy_id AND user_id = :user_id"
                ),
                {"legacy_id": legacy_mongo_id, "user_id": user_id},
            )
        else:
            result = self._conn.execute(
                text(
                    "SELECT * FROM conversations WHERE legacy_mongo_id = :legacy_id"
                ),
                {"legacy_id": legacy_mongo_id},
            )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Fetch a conversation the user owns or has shared access to."""
        result = self._conn.execute(
            text(
                "SELECT * FROM conversations "
                "WHERE id = CAST(:id AS uuid) "
                "AND (user_id = :user_id OR :user_id = ANY(shared_with))"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def get_owned(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Fetch a conversation owned by the user (no shared access)."""
        result = self._conn.execute(
            text(
                "SELECT * FROM conversations "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_user(self, user_id: str, limit: int = 30) -> list[dict]:
        """List conversations for a user, most recent first.

        Mirrors the Mongo query: either no api_key or agent_id exists.
        """
        result = self._conn.execute(
            text(
                "SELECT * FROM conversations "
                "WHERE user_id = :user_id "
                "AND (api_key IS NULL OR agent_id IS NOT NULL) "
                "ORDER BY date DESC LIMIT :limit"
            ),
            {"user_id": user_id, "limit": limit},
        )
        return [row_to_dict(r) for r in result.fetchall()]

    def rename(self, conversation_id: str, user_id: str, name: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE conversations SET name = :name, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id, "name": name},
        )
        return result.rowcount > 0

    def set_shared_token(self, conversation_id: str, user_id: str, token: str) -> bool:
        result = self._conn.execute(
            text(
                "UPDATE conversations SET shared_token = :token, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id, "token": token},
        )
        return result.rowcount > 0

    def update_compression_metadata(
        self, conversation_id: str, user_id: str, metadata: dict,
    ) -> bool:
        """Replace the entire ``compression_metadata`` JSONB blob.

        Prefer :meth:`append_compression_point` + :meth:`set_compression_flags`
        to match the Mongo service semantics exactly (those two mirror
        ``$set`` + ``$push $slice``). This method is retained for callers
        that already compute the full merged blob client-side.
        """
        result = self._conn.execute(
            text(
                "UPDATE conversations "
                "SET compression_metadata = CAST(:meta AS jsonb), updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id, "meta": json.dumps(metadata)},
        )
        return result.rowcount > 0

    def set_compression_flags(
        self,
        conversation_id: str,
        *,
        is_compressed: bool,
        last_compression_at,
    ) -> bool:
        """Update ``compression_metadata.is_compressed`` and
        ``compression_metadata.last_compression_at`` without touching
        ``compression_points``.

        Mirrors the Mongo ``$set`` on those two subfields in
        ``ConversationService.update_compression_metadata``. Initialises
        the surrounding object when the row has no ``compression_metadata``
        yet.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE conversations SET
                    compression_metadata = jsonb_set(
                        jsonb_set(
                            COALESCE(compression_metadata, '{}'::jsonb),
                            '{is_compressed}',
                            to_jsonb(CAST(:is_compressed AS boolean)), true
                        ),
                        '{last_compression_at}',
                        to_jsonb(CAST(:last_compression_at AS text)), true
                    ),
                    updated_at = now()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": conversation_id,
                "is_compressed": bool(is_compressed),
                "last_compression_at": (
                    str(last_compression_at) if last_compression_at is not None else None
                ),
            },
        )
        return result.rowcount > 0

    def append_compression_point(
        self,
        conversation_id: str,
        point: dict,
        *,
        max_points: int,
    ) -> bool:
        """Append one compression point, keeping at most ``max_points``.

        Mirrors Mongo's ``$push {"$each": [point], "$slice": -max_points}``
        on ``compression_metadata.compression_points``. Preserves the
        other top-level keys in ``compression_metadata``.
        """
        result = self._conn.execute(
            text(
                """
                UPDATE conversations SET
                    compression_metadata = jsonb_set(
                        COALESCE(compression_metadata, '{}'::jsonb),
                        '{compression_points}',
                        COALESCE(
                            (
                                SELECT jsonb_agg(elem ORDER BY rn)
                                FROM (
                                    SELECT
                                        elem,
                                        row_number() OVER () AS rn,
                                        count(*) OVER () AS cnt
                                    FROM jsonb_array_elements(
                                        COALESCE(
                                            compression_metadata -> 'compression_points',
                                            '[]'::jsonb
                                        ) || jsonb_build_array(CAST(:point AS jsonb))
                                    ) AS elem
                                ) ranked
                                WHERE rn > cnt - :max_points
                            ),
                            '[]'::jsonb
                        ),
                        true
                    ),
                    updated_at = now()
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {
                "id": conversation_id,
                "point": json.dumps(point, default=str),
                "max_points": int(max_points),
            },
        )
        return result.rowcount > 0

    def delete(self, conversation_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM conversations "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def delete_all_for_user(self, user_id: str) -> int:
        result = self._conn.execute(
            text("DELETE FROM conversations WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        return result.rowcount

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def get_messages(self, conversation_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "ORDER BY position ASC"
            ),
            {"conv_id": conversation_id},
        )
        return [_message_row_to_dict(r) for r in result.fetchall()]

    def get_message_at(self, conversation_id: str, position: int) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND position = :pos"
            ),
            {"conv_id": conversation_id, "pos": position},
        )
        row = result.fetchone()
        return _message_row_to_dict(row) if row is not None else None

    def append_message(self, conversation_id: str, message: dict) -> dict:
        """Append a message to a conversation.

        Uses ``SELECT ... FOR UPDATE`` to allocate the next position
        atomically. The caller must be inside a transaction.

        Mirrors Mongo's ``$push`` on the ``queries`` array.
        """
        # Lock the parent conversation row to serialize concurrent appends.
        self._conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE id = CAST(:conv_id AS uuid) FOR UPDATE"
            ),
            {"conv_id": conversation_id},
        )
        next_pos_result = self._conn.execute(
            text(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos "
                "FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid)"
            ),
            {"conv_id": conversation_id},
        )
        next_pos = next_pos_result.scalar()

        values = {
            "conversation_id": conversation_id,
            "position": next_pos,
            "prompt": message.get("prompt"),
            "response": message.get("response"),
            "thought": message.get("thought"),
            "sources": message.get("sources") or [],
            "tool_calls": message.get("tool_calls") or [],
            "model_id": message.get("model_id"),
            "message_metadata": message.get("metadata") or {},
        }
        if message.get("timestamp") is not None:
            values["timestamp"] = message["timestamp"]

        attachments = message.get("attachments")
        if attachments:
            values["attachments"] = [str(a) for a in attachments]

        stmt = (
            pg_insert(conversation_messages_table)
            .values(**values)
            .returning(conversation_messages_table)
        )
        result = self._conn.execute(stmt)
        # Touch the parent conversation's updated_at.
        self._conn.execute(
            text(
                "UPDATE conversations SET updated_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": conversation_id},
        )
        return _message_row_to_dict(result.fetchone())

    def update_message_at(
        self, conversation_id: str, position: int, fields: dict,
    ) -> bool:
        """Update specific fields on a message at a given position.

        Mirrors Mongo's ``$set`` on ``queries.{index}.*``.
        """
        allowed = {
            "prompt", "response", "thought", "sources", "tool_calls",
            "attachments", "model_id", "metadata", "timestamp",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        # Map public API key ``metadata`` → DB column ``message_metadata``.
        api_to_col = {"metadata": "message_metadata"}

        set_parts = []
        params: dict = {"conv_id": conversation_id, "pos": position}
        for key, val in filtered.items():
            col = api_to_col.get(key, key)
            if key in ("sources", "tool_calls", "metadata"):
                set_parts.append(f"{col} = CAST(:{col} AS jsonb)")
                params[col] = json.dumps(val) if not isinstance(val, str) else val
            elif key == "attachments":
                set_parts.append(f"{col} = CAST(:{col} AS uuid[])")
                params[col] = [str(a) for a in val] if val else []
            else:
                set_parts.append(f"{col} = :{col}")
                params[col] = val

        if "timestamp" not in filtered:
            set_parts.append("timestamp = now()")
        sql = (
            f"UPDATE conversation_messages SET {', '.join(set_parts)} "
            "WHERE conversation_id = CAST(:conv_id AS uuid) AND position = :pos"
        )
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0

    def truncate_after(self, conversation_id: str, keep_up_to: int) -> int:
        """Delete messages with position > keep_up_to.

        Mirrors Mongo's ``$push`` + ``$slice`` that trims queries after an
        index-based update.
        """
        result = self._conn.execute(
            text(
                "DELETE FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND position > :pos"
            ),
            {"conv_id": conversation_id, "pos": keep_up_to},
        )
        return result.rowcount

    def set_feedback(
        self, conversation_id: str, position: int, feedback: dict | None,
    ) -> bool:
        """Set or unset feedback on a message.

        ``feedback`` is a JSONB value, e.g. ``{"text": "thumbs_up",
        "timestamp": "..."}`` or ``None`` to unset.
        """
        fb_json = json.dumps(feedback) if feedback is not None else None
        result = self._conn.execute(
            text(
                "UPDATE conversation_messages "
                "SET feedback = CAST(:fb AS jsonb) "
                "WHERE conversation_id = CAST(:conv_id AS uuid) AND position = :pos"
            ),
            {"conv_id": conversation_id, "pos": position, "fb": fb_json},
        )
        return result.rowcount > 0

    def message_count(self, conversation_id: str) -> int:
        result = self._conn.execute(
            text(
                "SELECT COUNT(*) FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid)"
            ),
            {"conv_id": conversation_id},
        )
        return result.scalar() or 0
