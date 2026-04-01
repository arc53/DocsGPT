"""Service for saving and restoring tool-call continuation state.

When a stream pauses (tool needs approval or client-side execution),
the full execution state is persisted to MongoDB so the client can
resume later by sending tool_actions.
"""

import datetime
import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId

from application.core.mongo_db import MongoDB
from application.core.settings import settings

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
    """Manages pending tool-call state in MongoDB."""

    def __init__(self):
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        self.collection = db["pending_tool_state"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            self.collection.create_index(
                "expires_at", expireAfterSeconds=0
            )
            self.collection.create_index(
                [("conversation_id", 1), ("user", 1)], unique=True
            )
        except Exception:
            # Indexes may already exist or mongomock doesn't support TTL
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
            The string ID of the saved state document.
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        expires_at = now + datetime.timedelta(seconds=PENDING_STATE_TTL_SECONDS)

        doc = {
            "conversation_id": conversation_id,
            "user": user,
            "messages": _make_serializable(messages),
            "pending_tool_calls": _make_serializable(pending_tool_calls),
            "tools_dict": _make_serializable(tools_dict),
            "tool_schemas": _make_serializable(tool_schemas),
            "agent_config": _make_serializable(agent_config),
            "client_tools": _make_serializable(client_tools) if client_tools else None,
            "created_at": now,
            "expires_at": expires_at,
        }

        # Upsert — only one pending state per conversation per user
        result = self.collection.replace_one(
            {"conversation_id": conversation_id, "user": user},
            doc,
            upsert=True,
        )
        state_id = str(result.upserted_id) if result.upserted_id else conversation_id
        logger.info(
            f"Saved continuation state for conversation {conversation_id} "
            f"with {len(pending_tool_calls)} pending tool call(s)"
        )
        return state_id

    def load_state(
        self, conversation_id: str, user: str
    ) -> Optional[Dict[str, Any]]:
        """Load pending continuation state.

        Returns:
            The state dict, or None if no pending state exists.
        """
        doc = self.collection.find_one(
            {"conversation_id": conversation_id, "user": user}
        )
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        return doc

    def delete_state(self, conversation_id: str, user: str) -> bool:
        """Delete pending state after successful resumption.

        Returns:
            True if a document was deleted.
        """
        result = self.collection.delete_one(
            {"conversation_id": conversation_id, "user": user}
        )
        if result.deleted_count:
            logger.info(
                f"Deleted continuation state for conversation {conversation_id}"
            )
        return result.deleted_count > 0
