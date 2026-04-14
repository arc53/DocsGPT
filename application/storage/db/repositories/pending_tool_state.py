"""Repository for the ``pending_tool_state`` table.

Mirrors the continuation service's three operations on
``pending_tool_state`` in Mongo:

- save_state  → upsert (INSERT ... ON CONFLICT DO UPDATE)
- load_state  → find_one by (conversation_id, user_id)
- delete_state → delete_one by (conversation_id, user_id)

Plus a cleanup method for the Celery beat task that replaces Mongo's
TTL index.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict

PENDING_STATE_TTL_SECONDS = 30 * 60  # 1800 seconds


class PendingToolStateRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def save_state(
        self,
        conversation_id: str,
        user_id: str,
        *,
        messages: list,
        pending_tool_calls: list,
        tools_dict: dict,
        tool_schemas: list,
        agent_config: dict,
        client_tools: list | None = None,
        ttl_seconds: int = PENDING_STATE_TTL_SECONDS,
    ) -> dict:
        """Upsert pending tool state.

        Mirrors Mongo's ``replace_one(..., upsert=True)``.
        """
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(
            now.timestamp() + ttl_seconds, tz=timezone.utc,
        )

        result = self._conn.execute(
            text(
                """
                INSERT INTO pending_tool_state
                    (conversation_id, user_id, messages, pending_tool_calls,
                     tools_dict, tool_schemas, agent_config, client_tools,
                     created_at, expires_at)
                VALUES
                    (CAST(:conv_id AS uuid), :user_id,
                     CAST(:messages AS jsonb), CAST(:pending AS jsonb),
                     CAST(:tools_dict AS jsonb), CAST(:schemas AS jsonb),
                     CAST(:agent_config AS jsonb), CAST(:client_tools AS jsonb),
                     :created_at, :expires_at)
                ON CONFLICT (conversation_id, user_id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    pending_tool_calls = EXCLUDED.pending_tool_calls,
                    tools_dict = EXCLUDED.tools_dict,
                    tool_schemas = EXCLUDED.tool_schemas,
                    agent_config = EXCLUDED.agent_config,
                    client_tools = EXCLUDED.client_tools,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at
                RETURNING *
                """
            ),
            {
                "conv_id": conversation_id,
                "user_id": user_id,
                "messages": json.dumps(messages),
                "pending": json.dumps(pending_tool_calls),
                "tools_dict": json.dumps(tools_dict),
                "schemas": json.dumps(tool_schemas),
                "agent_config": json.dumps(agent_config),
                "client_tools": json.dumps(client_tools) if client_tools is not None else None,
                "created_at": now,
                "expires_at": expires,
            },
        )
        return row_to_dict(result.fetchone())

    def load_state(self, conversation_id: str, user_id: str) -> Optional[dict]:
        result = self._conn.execute(
            text(
                "SELECT * FROM pending_tool_state "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND user_id = :user_id"
            ),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def delete_state(self, conversation_id: str, user_id: str) -> bool:
        result = self._conn.execute(
            text(
                "DELETE FROM pending_tool_state "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND user_id = :user_id"
            ),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def cleanup_expired(self) -> int:
        """Delete rows where ``expires_at < now()``.

        Replaces Mongo's ``expireAfterSeconds=0`` TTL index. Intended to
        be called from a Celery beat task every 60 seconds.
        """
        # clock_timestamp() — not now() — since the latter is frozen to the
        # start of the transaction, which would let state that has just
        # expired survive one more cleanup tick.
        result = self._conn.execute(
            text("DELETE FROM pending_tool_state WHERE expires_at < clock_timestamp()")
        )
        return result.rowcount
