"""Repository for the ``pending_tool_state`` table.

Provides the continuation lifecycle operations for ``pending_tool_state``:

- save_state  → upsert (INSERT ... ON CONFLICT DO UPDATE)
- load_state  → fetch live pending state by (conversation_id, user_id)
- claim_state → atomically transition live pending state to ``resuming``
- delete_state → delete_one by (conversation_id, user_id)

Retains ``mark_resuming`` for compatibility; new resume paths use the atomic
claim. A separate ``revert_stale_resuming`` flips abandoned
``resuming`` rows back to ``pending`` so a crashed worker doesn't
strand the user.

Plus a cleanup method for the Celery beat task that replaces Mongo's
TTL index.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Connection, text

from application.storage.db.base_repository import row_to_dict
from application.storage.db.serialization import PGNativeJSONEncoder

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
                    expires_at = EXCLUDED.expires_at,
                    status = 'pending',
                    resumed_at = NULL
                RETURNING *
                """
            ),
            {
                "conv_id": conversation_id,
                "user_id": user_id,
                "messages": json.dumps(messages, cls=PGNativeJSONEncoder),
                "pending": json.dumps(pending_tool_calls, cls=PGNativeJSONEncoder),
                "tools_dict": json.dumps(tools_dict, cls=PGNativeJSONEncoder),
                "schemas": json.dumps(tool_schemas, cls=PGNativeJSONEncoder),
                "agent_config": json.dumps(agent_config, cls=PGNativeJSONEncoder),
                "client_tools": (
                    json.dumps(client_tools, cls=PGNativeJSONEncoder)
                    if client_tools is not None else None
                ),
                "created_at": now,
                "expires_at": expires,
            },
        )
        return row_to_dict(result.fetchone())

    def load_state(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Load live pending state without exposing expired/resuming rows."""
        result = self._conn.execute(
            text(
                "SELECT * FROM pending_tool_state "
                "WHERE conversation_id = CAST(:conv_id AS uuid) "
                "AND user_id = :user_id "
                "AND status = 'pending' "
                "AND expires_at > clock_timestamp()"
            ),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        row = result.fetchone()
        return row_to_dict(row) if row is not None else None

    def load_state_any(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Load state regardless of lifecycle for conflict classification."""
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

    def claim_state(self, conversation_id: str, user_id: str) -> Optional[dict]:
        """Atomically claim one live pending continuation and return it."""
        result = self._conn.execute(
            text(
                """
                UPDATE pending_tool_state
                SET status = 'resuming', resumed_at = clock_timestamp()
                WHERE conversation_id = CAST(:conv_id AS uuid)
                  AND user_id = :user_id
                  AND status = 'pending'
                  AND expires_at > clock_timestamp()
                RETURNING *
                """
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

    def mark_resuming(self, conversation_id: str, user_id: str) -> bool:
        """Flip a pending row to ``resuming`` and stamp ``resumed_at``."""
        result = self._conn.execute(
            text(
                """
                UPDATE pending_tool_state
                SET status = 'resuming', resumed_at = clock_timestamp()
                WHERE conversation_id = CAST(:conv_id AS uuid)
                  AND user_id = :user_id
                  AND status = 'pending'
                  AND expires_at > clock_timestamp()
                """
            ),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        return result.rowcount > 0

    def revert_stale_resuming(
        self,
        grace_seconds: int = 600,
        ttl_extension_seconds: int = PENDING_STATE_TTL_SECONDS,
    ) -> int:
        """Revert ``resuming`` rows older than ``grace_seconds`` to ``pending``; bump TTL."""
        result = self._conn.execute(
            text(
                """
                UPDATE pending_tool_state
                SET status = 'pending',
                    resumed_at = NULL,
                    expires_at = clock_timestamp()
                                 + make_interval(secs => :ttl)
                WHERE status = 'resuming'
                  AND resumed_at
                      < clock_timestamp() - make_interval(secs => :grace)
                """
            ),
            {"grace": grace_seconds, "ttl": ttl_extension_seconds},
        )
        return result.rowcount

    def cleanup_expired(self) -> list[dict]:
        """Delete TTL-expired rows; return their ``(conversation_id, user_id)``.

        Replaces Mongo's ``expireAfterSeconds=0`` TTL index. Intended to
        be called from a Celery beat task every 60 seconds. The deleted
        rows are returned so the caller can revoke any approval prompt
        tied to the now-gone resumable state.
        """
        # clock_timestamp() — not now() — since the latter is frozen to the
        # start of the transaction, which would let state that has just
        # expired survive one more cleanup tick.
        result = self._conn.execute(
            text(
                "DELETE FROM pending_tool_state WHERE expires_at < clock_timestamp() "
                "RETURNING conversation_id, user_id, agent_config"
            )
        )
        return [row_to_dict(r) for r in result.fetchall()]
