"""Service for saving and restoring tool-call continuation state.

When a stream pauses (tool needs approval or client-side execution),
the full execution state is persisted to Postgres so the client can
resume later by sending tool_actions.
"""

import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId

from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.repositories.pending_tool_state import (
    PendingToolStateRepository,
)
from application.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

# TTL for pending states — auto-cleaned after this period
PENDING_STATE_TTL_SECONDS = 30 * 60  # 30 minutes


def _make_serializable(obj: Any) -> Any:
    """Recursively convert MongoDB ObjectIds and other non-JSON types."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


class ContinuationService:
    """Manages pending tool-call state in Postgres."""

    def __init__(self):
        # No-op constructor retained for call-site compatibility. State
        # lives in Postgres now; each operation opens its own short-lived
        # session rather than holding a connection on the service.
        pass

    def save_state(
        self,
        conversation_id: str,
        user: str,
        messages: List[Dict],
        pending_tool_calls: List[Dict],
        tools_dict: Dict,
        tool_schemas: List[Dict],
        agent_config: Dict,
        client_tools: Optional[List[Dict]] = None,
    ) -> str:
        """Save execution state for later continuation.

        ``conversation_id`` may be a Postgres UUID or the legacy Mongo
        ``ObjectId`` string — the latter is resolved via
        ``conversations.legacy_mongo_id`` to find the matching row.

        Args:
            conversation_id: The conversation this state belongs to.
            user: Owner user ID.
            messages: Full messages array at the pause point.
            pending_tool_calls: Tool calls awaiting client action.
            tools_dict: Serializable tools configuration dict.
            tool_schemas: LLM-formatted tool schemas (agent.tools).
            agent_config: Config needed to recreate the agent on resume.
            client_tools: Client-provided tool schemas for client-side execution.

        Returns:
            The string ID (conversation_id as provided) of the saved state.
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            pg_conv_id = conv["id"] if conv is not None else conversation_id
            PendingToolStateRepository(conn).save_state(
                pg_conv_id,
                user,
                messages=_make_serializable(messages),
                pending_tool_calls=_make_serializable(pending_tool_calls),
                tools_dict=_make_serializable(tools_dict),
                tool_schemas=_make_serializable(tool_schemas),
                agent_config=_make_serializable(agent_config),
                client_tools=_make_serializable(client_tools) if client_tools else None,
            )

        logger.info(
            f"Saved continuation state for conversation {conversation_id} "
            f"with {len(pending_tool_calls)} pending tool call(s)"
        )
        return conversation_id

    def load_state(
        self, conversation_id: str, user: str
    ) -> Optional[Dict[str, Any]]:
        """Load pending continuation state.

        Returns:
            The state dict, or None if no pending state exists.
        """
        with db_readonly() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            pg_conv_id = conv["id"] if conv is not None else conversation_id
            doc = PendingToolStateRepository(conn).load_state(pg_conv_id, user)
        if not doc:
            return None
        return doc

    def delete_state(self, conversation_id: str, user: str) -> bool:
        """Delete pending state after successful resumption.

        Returns:
            True if a row was deleted.
        """
        with db_session() as conn:
            conv = ConversationsRepository(conn).get_by_legacy_id(conversation_id)
            pg_conv_id = conv["id"] if conv is not None else conversation_id
            deleted = PendingToolStateRepository(conn).delete_state(pg_conv_id, user)
        if deleted:
            logger.info(
                f"Deleted continuation state for conversation {conversation_id}"
            )
        return deleted
