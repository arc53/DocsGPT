"""Conversation persistence service backed by Postgres.

Handles create / append / update / compression for conversations during
the answer-streaming path. Connections are opened per-operation rather
than held for the duration of a stream.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text

from application.core.settings import settings
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


class ConversationService:
    def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve a conversation with owner-or-shared access control.

        Returns a dict in the legacy Mongo shape — ``queries`` is a list
        of message dicts (prompt/response/...) — for compatibility with
        the streaming pipeline that consumes this shape.
        """
        if not conversation_id or not user_id:
            return None
        try:
            with db_readonly() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(conversation_id, user_id)
                if conv is None:
                    logger.warning(
                        f"Conversation not found or unauthorized - ID: {conversation_id}, User: {user_id}"
                    )
                    return None
                messages = repo.get_messages(str(conv["id"]))
            conv["queries"] = messages
            conv["_id"] = str(conv["id"])
            return conv
        except Exception as e:
            logger.error(f"Error fetching conversation: {str(e)}", exc_info=True)
            return None

    def save_conversation(
        self,
        conversation_id: Optional[str],
        question: str,
        response: str,
        thought: str,
        sources: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
        llm: Any,
        model_id: str,
        decoded_token: Dict[str, Any],
        index: Optional[int] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
        attachment_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Save or update a conversation in Postgres.

        Returns the string conversation id (PG UUID as string, or the
        caller-provided id if it was already a UUID).
        """
        if decoded_token is None:
            raise ValueError("Invalid or missing authentication token")
        user_id = decoded_token.get("sub")
        if not user_id:
            raise ValueError("User ID not found in token")
        current_time = datetime.now(timezone.utc)

        # Trim huge inline source text to a reasonable max before persist.
        for source in sources:
            if "text" in source and isinstance(source["text"], str):
                source["text"] = source["text"][:1000]

        message_payload = {
            "prompt": question,
            "response": response,
            "thought": thought,
            "sources": sources,
            "tool_calls": tool_calls,
            "attachments": attachment_ids,
            "model_id": model_id,
            "timestamp": current_time,
        }
        if metadata:
            message_payload["metadata"] = metadata

        if conversation_id is not None and index is not None:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(conversation_id, user_id)
                if conv is None:
                    raise ValueError("Conversation not found or unauthorized")
                conv_pg_id = str(conv["id"])
                repo.update_message_at(conv_pg_id, index, message_payload)
                repo.truncate_after(conv_pg_id, index)
            return conversation_id
        elif conversation_id:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(conversation_id, user_id)
                if conv is None:
                    raise ValueError("Conversation not found or unauthorized")
                conv_pg_id = str(conv["id"])
                # append_message expects 'metadata' key either way; normalise.
                append_payload = dict(message_payload)
                append_payload.setdefault("metadata", metadata or {})
                repo.append_message(conv_pg_id, append_payload)
            return conversation_id
        else:
            messages_summary = [
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates concise conversation titles. "
                    "Summarize conversations in 3 words or less using the same language as the user.",
                },
                {
                    "role": "user",
                    "content": "Summarise following conversation in no more than 3 words, "
                    "respond ONLY with the summary, use the same language as the "
                    "user query \n\nUser: " + question + "\n\n" + "AI: " + response,
                },
            ]

            completion = llm.gen(
                model=model_id, messages=messages_summary, max_tokens=500
            )

            if not completion or not completion.strip():
                completion = question[:50] if question else "New Conversation"

            resolved_api_key: Optional[str] = None
            resolved_agent_id: Optional[str] = None
            if api_key:
                with db_readonly() as conn:
                    agent = AgentsRepository(conn).find_by_key(api_key)
                if agent:
                    resolved_api_key = agent.get("key")
                if agent_id:
                    resolved_agent_id = agent_id

            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.create(
                    user_id,
                    completion,
                    agent_id=resolved_agent_id,
                    api_key=resolved_api_key,
                    is_shared_usage=bool(resolved_agent_id and is_shared_usage),
                    shared_token=(
                        shared_token
                        if (resolved_agent_id and is_shared_usage)
                        else None
                    ),
                )
                conv_pg_id = str(conv["id"])
                append_payload = dict(message_payload)
                append_payload.setdefault("metadata", metadata or {})
                repo.append_message(conv_pg_id, append_payload)
            return conv_pg_id

    def update_compression_metadata(
        self, conversation_id: str, compression_metadata: Dict[str, Any]
    ) -> None:
        """Persist compression flags and append a compression point.

        Mirrors the Mongo-era ``$set`` + ``$push $slice`` on
        ``compression_metadata`` but goes through the PG repo API.
        """
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                # conversation_id here comes from the streaming pipeline
                # which has already resolved it; accept either UUID or
                # legacy id for safety.
                conv = repo.get_by_legacy_id(conversation_id)
                conv_pg_id = (
                    str(conv["id"]) if conv is not None else conversation_id
                )
                repo.set_compression_flags(
                    conv_pg_id,
                    is_compressed=True,
                    last_compression_at=compression_metadata.get("timestamp"),
                )
                repo.append_compression_point(
                    conv_pg_id,
                    compression_metadata,
                    max_points=settings.COMPRESSION_MAX_HISTORY_POINTS,
                )
            logger.info(
                f"Updated compression metadata for conversation {conversation_id}"
            )
        except Exception as e:
            logger.error(
                f"Error updating compression metadata: {str(e)}", exc_info=True
            )
            raise

    def append_compression_message(
        self, conversation_id: str, compression_metadata: Dict[str, Any]
    ) -> None:
        """Append a synthetic compression summary message to the conversation."""
        try:
            summary = compression_metadata.get("compressed_summary", "")
            if not summary:
                return
            timestamp = compression_metadata.get(
                "timestamp", datetime.now(timezone.utc)
            )

            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_by_legacy_id(conversation_id)
                conv_pg_id = (
                    str(conv["id"]) if conv is not None else conversation_id
                )
                repo.append_message(conv_pg_id, {
                    "prompt": "[Context Compression Summary]",
                    "response": summary,
                    "thought": "",
                    "sources": [],
                    "tool_calls": [],
                    "attachments": [],
                    "model_id": compression_metadata.get("model_used"),
                    "timestamp": timestamp,
                })
            logger.info(
                f"Appended compression summary to conversation {conversation_id}"
            )
        except Exception as e:
            logger.error(
                f"Error appending compression summary: {str(e)}", exc_info=True
            )

    def get_compression_metadata(
        self, conversation_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch the stored compression metadata JSONB blob for a conversation."""
        try:
            with db_readonly() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_by_legacy_id(conversation_id)
                if conv is None:
                    # Fallback to UUID lookup without user scoping — the
                    # caller already holds an authenticated conversation
                    # id from the streaming path.
                    result = conn.execute(
                        sql_text(
                            "SELECT compression_metadata FROM conversations "
                            "WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": conversation_id},
                    )
                    row = result.fetchone()
                    return row[0] if row is not None else None
            return conv.get("compression_metadata") if conv else None
        except Exception as e:
            logger.error(
                f"Error getting compression metadata: {str(e)}", exc_info=True
            )
            return None
