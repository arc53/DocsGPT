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

from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.models import conversations_table, conversation_messages_table
from application.storage.db.serialization import PGNativeJSONEncoder


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
    # Reference translation helpers
    # ------------------------------------------------------------------
    #
    # During the Mongo→Postgres dual-write window, callers routinely
    # hand us Mongo ObjectId strings (24-char hex) for fields that are
    # UUID FKs in Postgres (``agent_id``, ``attachments`` entries, ...).
    # Casting those straight to ``uuid`` raises and the outer dual-write
    # shim swallows the exception, so the write silently drops. These
    # helpers translate via the ``legacy_mongo_id`` columns we added
    # precisely for this purpose.

    def _resolve_agent_ref(self, agent_id_raw: str | None) -> str | None:
        """Translate ``agent_id_raw`` to a Postgres UUID string.

        - ``None``/empty → ``None`` (no agent).
        - Already-UUID-shaped → returned as-is.
        - Otherwise treated as a Mongo ObjectId and looked up via
          ``agents.legacy_mongo_id``. Returns ``None`` if no PG row
          exists yet (e.g. the agent was created before Phase 1
          backfill).
        """
        if not agent_id_raw:
            return None
        value = str(agent_id_raw)
        if looks_like_uuid(value):
            return value
        result = self._conn.execute(
            text("SELECT id FROM agents WHERE legacy_mongo_id = :lid LIMIT 1"),
            {"lid": value},
        )
        row = result.fetchone()
        return str(row[0]) if row is not None else None

    def _resolve_attachment_refs(
        self, ids: list[str] | None,
    ) -> list[str]:
        """Translate a list of attachment ids to canonical PG
        ``attachments.id`` UUIDs.

        Inputs may be:

        - A Mongo ObjectId string (24-hex), legacy dual-write era —
          must be looked up via ``attachments.legacy_mongo_id``.
        - A UUID string that is a real ``attachments.id`` PK.
        - A UUID string that is *only* present as
          ``attachments.legacy_mongo_id`` — this is the post-cutover
          shape: ``/store_attachment`` mints a UUID, hands it to the
          worker, and the worker stashes it in ``legacy_mongo_id``
          while the row gets a freshly-generated PK. Trusting the
          input UUID as a PK here orphans the array entry: the column
          is ``uuid[]`` (no FK), so PG accepts the bad value and all
          downstream reads via ``AttachmentsRepository.get_any`` miss.

        Resolution therefore tries ``legacy_mongo_id`` first for every
        id (UUID-shaped or not), then falls back to the direct PK
        match. Unknown ids are dropped — they'd have failed the
        ``uuid[]`` cast otherwise and the whole row would have vanished
        via dual-write's exception swallow.
        """
        if not ids:
            return []
        # Defer to AttachmentsRepository for the batched lookup so the
        # legacy-first semantics live in one place.
        from application.storage.db.repositories.attachments import (
            AttachmentsRepository,
        )

        clean: list[str] = [str(raw) for raw in ids if raw is not None]
        if not clean:
            return []
        repo = AttachmentsRepository(self._conn)
        mapping = repo.resolve_ids(clean)
        out: list[str] = []
        for value in clean:
            mapped = mapping.get(value)
            if mapped is not None:
                out.append(mapped)
        return out

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
        # ``agent_id`` may arrive as a Mongo ObjectId during the dual-write
        # window; resolve to a UUID (or drop silently if not yet backfilled).
        resolved_agent_id = self._resolve_agent_ref(agent_id)
        if resolved_agent_id:
            values["agent_id"] = resolved_agent_id
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
        legacy_mongo_id = str(legacy_mongo_id) if legacy_mongo_id is not None else None
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

    def get_any(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Resolve a conversation by either PG UUID or legacy Mongo ObjectId string.

        Returns a conversation the user owns or has shared access to.
        """
        if looks_like_uuid(conversation_id):
            row = self.get(conversation_id, user_id)
            if row is not None:
                return row
        return self.get_by_legacy_id(conversation_id, user_id)

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
        # Shape-gate so a non-UUID id (legacy Mongo ObjectId still floating
        # around in client-side state during the cutover) never reaches the
        # ``CAST(:id AS uuid)`` — that cast raises on the server and poisons
        # the enclosing transaction, making every subsequent query on the
        # same connection fail.
        if not looks_like_uuid(conversation_id):
            return False
        result = self._conn.execute(
            text(
                "UPDATE conversations SET name = :name, updated_at = now() "
                "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
            ),
            {"id": conversation_id, "user_id": user_id, "name": name},
        )
        return result.rowcount > 0

    def add_shared_user(self, conversation_id: str, user_to_add: str) -> bool:
        """Idempotently append ``user_to_add`` to ``shared_with``.

        Accepts either a PG UUID or a legacy Mongo ObjectId as the
        conversation id. Mirrors Mongo ``$addToSet`` semantics via the
        ``NOT (:user = ANY(shared_with))`` guard.
        """
        if not user_to_add:
            return False
        if looks_like_uuid(conversation_id):
            sql = (
                "UPDATE conversations "
                "SET shared_with = array_append(shared_with, :user), "
                "    updated_at = now() "
                "WHERE id = CAST(:id AS uuid) "
                "AND NOT (:user = ANY(shared_with))"
            )
        else:
            sql = (
                "UPDATE conversations "
                "SET shared_with = array_append(shared_with, :user), "
                "    updated_at = now() "
                "WHERE legacy_mongo_id = :id "
                "AND NOT (:user = ANY(shared_with))"
            )
        result = self._conn.execute(
            text(sql), {"id": conversation_id, "user": user_to_add},
        )
        return result.rowcount > 0

    def remove_shared_user(self, conversation_id: str, user_to_remove: str) -> bool:
        """Remove ``user_to_remove`` from ``shared_with``. Mirror of Mongo ``$pull``."""
        if not user_to_remove:
            return False
        if looks_like_uuid(conversation_id):
            sql = (
                "UPDATE conversations "
                "SET shared_with = array_remove(shared_with, :user), "
                "    updated_at = now() "
                "WHERE id = CAST(:id AS uuid) "
                "AND :user = ANY(shared_with)"
            )
        else:
            sql = (
                "UPDATE conversations "
                "SET shared_with = array_remove(shared_with, :user), "
                "    updated_at = now() "
                "WHERE legacy_mongo_id = :id "
                "AND :user = ANY(shared_with)"
            )
        result = self._conn.execute(
            text(sql), {"id": conversation_id, "user": user_to_remove},
        )
        return result.rowcount > 0

    def set_shared_token(self, conversation_id: str, user_id: str, token: str) -> bool:
        # Shape-gate: see ``rename`` — prevents transaction poisoning when
        # a non-UUID id reaches this code path.
        if not looks_like_uuid(conversation_id):
            return False
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
        # Shape-gate: see ``rename`` — prevents transaction poisoning when
        # a non-UUID id reaches this code path.
        if not looks_like_uuid(conversation_id):
            return False
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
        # Shape-gate: the streaming pipeline may pass through a legacy id
        # that ``get_by_legacy_id`` couldn't resolve; in that case the id
        # remains a non-UUID string and the CAST would poison the txn.
        if not looks_like_uuid(conversation_id):
            return False
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
        # Shape-gate: see ``set_compression_flags``.
        if not looks_like_uuid(conversation_id):
            return False
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
                "point": json.dumps(point, cls=PGNativeJSONEncoder),
                "max_points": int(max_points),
            },
        )
        return result.rowcount > 0

    def delete(self, conversation_id: str, user_id: str) -> bool:
        # Shape-gate: see ``rename`` — prevents transaction poisoning when
        # a non-UUID id reaches this code path.
        if not looks_like_uuid(conversation_id):
            return False
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
        # Shape-gate: see ``rename``. Callers today always pass a resolved
        # UUID (via ``get_any`` first), but the guard costs nothing and
        # keeps future callers safe from txn-poisoning.
        if not looks_like_uuid(conversation_id):
            return None
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
            # Attachment ids may arrive as Mongo ObjectIds during the
            # dual-write window — resolve each to a PG UUID or drop it.
            resolved = self._resolve_attachment_refs(
                [str(a) for a in attachments],
            )
            if resolved:
                values["attachments"] = resolved

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
            # Feedback can be re-set in rare continuation flows; without
            # it in the whitelist an upstream re-append that happens to
            # carry feedback would silently lose it. Mirrors
            # ``set_feedback`` — column is JSONB.
            "feedback", "feedback_timestamp",
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
            if key in ("sources", "tool_calls", "metadata", "feedback"):
                set_parts.append(f"{col} = CAST(:{col} AS jsonb)")
                if val is None:
                    params[col] = None
                else:
                    params[col] = (
                        json.dumps(val) if not isinstance(val, str) else val
                    )
            elif key == "attachments":
                # Attachment ids may be Mongo ObjectIds during the
                # dual-write window; translate via attachments.legacy_mongo_id.
                set_parts.append(f"{col} = CAST(:{col} AS uuid[])")
                params[col] = self._resolve_attachment_refs(
                    [str(a) for a in val] if val else [],
                )
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

    def reserve_message(
        self,
        conversation_id: str,
        *,
        prompt: str,
        placeholder_response: str,
        request_id: str | None = None,
        status: str = "pending",
        attachments: list[str] | None = None,
        model_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """Pre-persist a placeholder assistant message before the LLM call."""
        self._conn.execute(
            text(
                "SELECT id FROM conversations "
                "WHERE id = CAST(:conv_id AS uuid) FOR UPDATE"
            ),
            {"conv_id": conversation_id},
        )
        next_pos = self._conn.execute(
            text(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos "
                "FROM conversation_messages "
                "WHERE conversation_id = CAST(:conv_id AS uuid)"
            ),
            {"conv_id": conversation_id},
        ).scalar()

        values = {
            "conversation_id": conversation_id,
            "position": next_pos,
            "prompt": prompt,
            "response": placeholder_response,
            "status": status,
            "request_id": request_id,
            "model_id": model_id,
            "message_metadata": metadata or {},
        }
        if attachments:
            resolved = self._resolve_attachment_refs(
                [str(a) for a in attachments],
            )
            if resolved:
                values["attachments"] = resolved

        stmt = (
            pg_insert(conversation_messages_table)
            .values(**values)
            .returning(conversation_messages_table)
        )
        result = self._conn.execute(stmt)
        self._conn.execute(
            text(
                "UPDATE conversations SET updated_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": conversation_id},
        )
        return _message_row_to_dict(result.fetchone())

    def update_message_by_id(
        self, message_id: str, fields: dict,
        *, only_if_non_terminal: bool = False,
    ) -> bool:
        """Update specific fields on a message identified by its UUID.

        ``metadata`` is merged into the existing JSONB rather than
        overwritten, so a reconciler-set ``reconcile_attempts`` survives
        a successful late finalize. When ``only_if_non_terminal`` is
        True, the update is gated so a late finalize cannot retract a
        reconciler-set ``failed`` (or a prior ``complete``).
        """
        if not looks_like_uuid(message_id):
            return False
        allowed = {
            "prompt", "response", "thought", "sources", "tool_calls",
            "attachments", "model_id", "metadata", "timestamp", "status",
            "request_id", "feedback", "feedback_timestamp",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return False

        api_to_col = {"metadata": "message_metadata"}

        set_parts = []
        params: dict = {"id": message_id}
        for key, val in filtered.items():
            col = api_to_col.get(key, key)
            if key == "metadata":
                if val is None:
                    set_parts.append(f"{col} = NULL")
                else:
                    set_parts.append(
                        f"{col} = COALESCE({col}, '{{}}'::jsonb) "
                        f"|| CAST(:{col} AS jsonb)"
                    )
                    params[col] = (
                        json.dumps(val) if not isinstance(val, str) else val
                    )
            elif key in ("sources", "tool_calls", "feedback"):
                set_parts.append(f"{col} = CAST(:{col} AS jsonb)")
                if val is None:
                    params[col] = None
                else:
                    params[col] = (
                        json.dumps(val) if not isinstance(val, str) else val
                    )
            elif key == "attachments":
                set_parts.append(f"{col} = CAST(:{col} AS uuid[])")
                params[col] = self._resolve_attachment_refs(
                    [str(a) for a in val] if val else [],
                )
            else:
                set_parts.append(f"{col} = :{col}")
                params[col] = val

        set_parts.append("updated_at = now()")
        where_clauses = ["id = CAST(:id AS uuid)"]
        if only_if_non_terminal:
            where_clauses.append("status NOT IN ('complete', 'failed')")
        sql = (
            f"UPDATE conversation_messages SET {', '.join(set_parts)} "
            f"WHERE {' AND '.join(where_clauses)}"
        )
        result = self._conn.execute(text(sql), params)
        return result.rowcount > 0

    def update_message_status(
        self, message_id: str, status: str,
    ) -> bool:
        """Cheap status-only transition (e.g. pending → streaming).

        Only flips non-terminal rows: a reconciler-set ``failed`` row
        stays put so the late streaming chunk doesn't silently retract
        the alert.
        """
        if not looks_like_uuid(message_id):
            return False
        result = self._conn.execute(
            text(
                "UPDATE conversation_messages SET status = :status, "
                "updated_at = now() "
                "WHERE id = CAST(:id AS uuid) "
                "AND status NOT IN ('complete', 'failed')"
            ),
            {"id": message_id, "status": status},
        )
        return result.rowcount > 0

    def heartbeat_message(self, message_id: str) -> bool:
        """Stamp ``message_metadata.last_heartbeat_at`` with ``clock_timestamp()``.

        The reconciler's staleness check uses ``GREATEST(timestamp,
        last_heartbeat_at)``, so this call extends a long-running
        stream's effective freshness without touching ``timestamp`` (the
        creation time, used for history sort) or ``status`` (the WAL
        marker). Skips terminal rows so a late heartbeat can't silently
        retract a reconciler-set ``failed``.
        """
        if not looks_like_uuid(message_id):
            return False
        result = self._conn.execute(
            text(
                """
                UPDATE conversation_messages
                SET message_metadata = jsonb_set(
                    COALESCE(message_metadata, '{}'::jsonb),
                    '{last_heartbeat_at}',
                    to_jsonb(clock_timestamp())
                )
                WHERE id = CAST(:id AS uuid)
                  AND status NOT IN ('complete', 'failed')
                """
            ),
            {"id": message_id},
        )
        return result.rowcount > 0

    def confirm_executed_tool_calls(self, message_id: str) -> int:
        """Flip ``tool_call_attempts.status='executed' → 'confirmed'`` for the message."""
        if not looks_like_uuid(message_id):
            return 0
        result = self._conn.execute(
            text(
                "UPDATE tool_call_attempts SET status = 'confirmed', "
                "updated_at = now() "
                "WHERE message_id = CAST(:mid AS uuid) AND status = 'executed'"
            ),
            {"mid": message_id},
        )
        return result.rowcount or 0

    def truncate_after(self, conversation_id: str, keep_up_to: int) -> int:
        """Delete messages with position > keep_up_to.

        Mirrors Mongo's ``$push`` + ``$slice`` that trims queries after an
        index-based update.
        """
        # Shape-gate: see ``rename`` — prevents transaction poisoning when
        # a non-UUID id reaches this code path.
        if not looks_like_uuid(conversation_id):
            return 0
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
        # Shape-gate: see ``rename`` — prevents transaction poisoning when
        # a non-UUID id reaches this code path.
        if not looks_like_uuid(conversation_id):
            return False
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
