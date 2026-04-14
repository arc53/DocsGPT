"""Repository for the ``shared_conversations`` table.

Covers the sharing operations from ``shared_conversations_collections``
in Mongo:

- create a share record (with UUID, conversation_id, user, visibility flags)
- look up by uuid (public access)
- look up by conversation_id + user + flags (dedup check)
"""

from __future__ import annotations

import uuid as uuid_mod
from typing import Optional

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.storage.db.base_repository import row_to_dict
from application.storage.db.models import shared_conversations_table


class SharedConversationsRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        conversation_id: str,
        user_id: str,
        *,
        is_promptable: bool = False,
        first_n_queries: int = 0,
        api_key: str | None = None,
        prompt_id: str | None = None,
        chunks: int | None = None,
        share_uuid: str | None = None,
    ) -> dict:
        """Create a share record.

        ``share_uuid`` allows the dual-write caller to supply the same
        UUID that Mongo received, so public ``/shared/{uuid}`` links
        keep resolving from both stores during the dual-write window.

        Callers that need race-free dedup on the logical share key
        should use :meth:`get_or_create` instead — it relies on the
        composite partial unique index added in migration 0008 to
        collapse concurrent requests to a single row.
        """
        final_uuid = share_uuid or str(uuid_mod.uuid4())
        values: dict = {
            "uuid": final_uuid,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "is_promptable": is_promptable,
            "first_n_queries": first_n_queries,
        }
        if api_key:
            values["api_key"] = api_key
        if prompt_id:
            values["prompt_id"] = prompt_id
        if chunks is not None:
            values["chunks"] = chunks

        stmt = (
            pg_insert(shared_conversations_table)
            .values(**values)
            .returning(shared_conversations_table)
        )
        result = self._conn.execute(stmt)
        return row_to_dict(result.fetchone())

    def get_or_create(
        self,
        conversation_id: str,
        user_id: str,
        *,
        is_promptable: bool = False,
        first_n_queries: int = 0,
        api_key: str | None = None,
        prompt_id: str | None = None,
        chunks: int | None = None,
        share_uuid: str | None = None,
    ) -> dict:
        """Race-free share create/lookup keyed on the logical dedup tuple.

        Leverages the partial unique index on
        ``(conversation_id, user_id, is_promptable, first_n_queries,
        COALESCE(api_key, ''))`` added in migration 0008. Concurrent
        requests for the same logical share converge on one row. The
        returned dict's ``uuid`` is the canonical public identifier.

        Dedup key rationale — ``prompt_id`` and ``chunks`` are
        deliberately *not* part of the uniqueness key. A share row is
        identified by "who shared what conversation under which
        visibility rules"; ``prompt_id`` / ``chunks`` are mutable
        properties of that share and are last-write-wins on re-share.
        This preserves existing public ``/shared/{uuid}`` URLs when a
        user updates the prompt or chunk count, matching the Mongo
        ``find_one`` + ``update`` semantics.
        """
        final_uuid = share_uuid or str(uuid_mod.uuid4())
        result = self._conn.execute(
            text(
                """
                INSERT INTO shared_conversations
                    (uuid, conversation_id, user_id, is_promptable,
                     first_n_queries, api_key, prompt_id, chunks)
                VALUES
                    (CAST(:uuid AS uuid), CAST(:conversation_id AS uuid),
                     :user_id, :is_promptable, :first_n_queries,
                     :api_key, CAST(:prompt_id AS uuid), :chunks)
                ON CONFLICT (conversation_id, user_id, is_promptable,
                             first_n_queries, COALESCE(api_key, ''))
                DO UPDATE SET prompt_id = EXCLUDED.prompt_id,
                              chunks = EXCLUDED.chunks
                RETURNING *
                """
            ),
            {
                "uuid": final_uuid,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "is_promptable": is_promptable,
                "first_n_queries": first_n_queries,
                "api_key": api_key,
                "prompt_id": prompt_id,
                "chunks": chunks,
            },
        )
        return row_to_dict(result.fetchone())

    def find_by_uuid(self, share_uuid: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM shared_conversations "
                "WHERE uuid = CAST(:uuid AS uuid)"
            ),
            {"uuid": share_uuid},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def find_existing(
        self,
        conversation_id: str,
        user_id: str,
        is_promptable: bool,
        first_n_queries: int,
        api_key: str | None = None,
    ) -> Optional[dict]:
        """Check for an existing share with matching parameters.

        Mirrors the Mongo ``find_one`` dedup check before creating a share.
        """
        if api_key:
            result = self._conn.execute(
                text(
                    "SELECT * FROM shared_conversations "
                    "WHERE conversation_id = CAST(:conv_id AS uuid) "
                    "AND user_id = :user_id "
                    "AND is_promptable = :is_promptable "
                    "AND first_n_queries = :fnq "
                    "AND api_key = :api_key "
                    "LIMIT 1"
                ),
                {
                    "conv_id": conversation_id,
                    "user_id": user_id,
                    "is_promptable": is_promptable,
                    "fnq": first_n_queries,
                    "api_key": api_key,
                },
            )
        else:
            result = self._conn.execute(
                text(
                    "SELECT * FROM shared_conversations "
                    "WHERE conversation_id = CAST(:conv_id AS uuid) "
                    "AND user_id = :user_id "
                    "AND is_promptable = :is_promptable "
                    "AND first_n_queries = :fnq "
                    "AND api_key IS NULL "
                    "LIMIT 1"
                ),
                {
                    "conv_id": conversation_id,
                    "user_id": user_id,
                    "is_promptable": is_promptable,
                    "fnq": first_n_queries,
                },
            )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def list_for_conversation(self, conversation_id: str) -> list[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM shared_conversations "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "ORDER BY created_at DESC"
            ),
            {"conv_id": conversation_id},
        )
        return [row_to_dict(r) for r in result.fetchall()]
