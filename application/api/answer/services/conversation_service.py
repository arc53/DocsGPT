"""Conversation persistence service backed by Postgres.

Handles create / append / update / compression for conversations during
the answer-streaming path. Connections are opened per-operation rather
than held for the duration of a stream.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text

from application.core.settings import settings
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


# Shown to the user if the worker dies mid-stream and the response is never finalised.
TERMINATED_RESPONSE_PLACEHOLDER = (
    "Response was terminated prior to completion, try regenerating."
)


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

            # ``model_id`` here is the registry id (a UUID for BYOM
            # records). The LLM's own ``model_id`` is the upstream name
            # LLMCreator resolved at construction time — that's what
            # the provider's API expects. Built-ins are unaffected.
            completion = llm.gen(
                model=getattr(llm, "model_id", None) or model_id,
                messages=messages_summary,
                max_tokens=500,
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

    def save_user_question(
        self,
        conversation_id: Optional[str],
        question: str,
        decoded_token: Dict[str, Any],
        *,
        attachment_ids: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
        model_id: Optional[str] = None,
        request_id: Optional[str] = None,
        status: str = "pending",
        index: Optional[int] = None,
    ) -> Dict[str, str]:
        """Reserve the placeholder message row before the LLM call.

        ``index`` carries the regenerate semantics: when supplied with an
        existing ``conversation_id``, every message at ``position >=
        index`` is deleted before the new placeholder is reserved. The
        placeholder then lands at ``position = index`` (since
        ``reserve_message`` picks ``MAX(position) + 1`` and the truncate
        leaves ``MAX = index - 1``). Without this, the WAL path appended
        a new row at the end and the original answer at ``index`` was
        never replaced.

        Returns ``{"conversation_id", "message_id", "request_id"}``.
        """
        if decoded_token is None:
            raise ValueError("Invalid or missing authentication token")
        user_id = decoded_token.get("sub")
        if not user_id:
            raise ValueError("User ID not found in token")

        request_id = request_id or str(uuid.uuid4())

        resolved_api_key: Optional[str] = None
        resolved_agent_id: Optional[str] = None
        if api_key and not conversation_id:
            with db_readonly() as conn:
                agent = AgentsRepository(conn).find_by_key(api_key)
            if agent:
                resolved_api_key = agent.get("key")
            if agent_id:
                resolved_agent_id = agent_id

        with db_session() as conn:
            repo = ConversationsRepository(conn)
            if conversation_id:
                conv = repo.get_any(conversation_id, user_id)
                if conv is None:
                    raise ValueError("Conversation not found or unauthorized")
                conv_pg_id = str(conv["id"])
                # Regenerate / edit-prior-question: drop the message at
                # ``index`` and everything after it so the new
                # ``reserve_message`` lands at ``position=index`` rather
                # than appending at the end of the conversation.
                if isinstance(index, int) and index >= 0:
                    repo.truncate_after(conv_pg_id, keep_up_to=index - 1)
            else:
                fallback_name = (question[:50] if question else "New Conversation")
                conv = repo.create(
                    user_id,
                    fallback_name,
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

            row = repo.reserve_message(
                conv_pg_id,
                prompt=question,
                placeholder_response=TERMINATED_RESPONSE_PLACEHOLDER,
                request_id=request_id,
                status=status,
                attachments=attachment_ids,
                model_id=model_id,
            )
            message_id = str(row["id"])

        return {
            "conversation_id": conv_pg_id,
            "message_id": message_id,
            "request_id": request_id,
        }

    def update_message_status(self, message_id: str, status: str) -> bool:
        """Cheap status-only transition (e.g. ``pending → streaming``)."""
        if not message_id:
            return False
        with db_session() as conn:
            return ConversationsRepository(conn).update_message_status(
                message_id, status,
            )

    def heartbeat_message(self, message_id: str) -> bool:
        """Bump ``message_metadata.last_heartbeat_at`` so the reconciler's
        staleness sweep counts the row as alive. No-ops on terminal rows.
        """
        if not message_id:
            return False
        with db_session() as conn:
            return ConversationsRepository(conn).heartbeat_message(message_id)

    def finalize_message(
        self,
        message_id: str,
        response: str,
        *,
        thought: str = "",
        sources: Optional[List[Dict[str, Any]]] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        model_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "complete",
        error: Optional[BaseException] = None,
        title_inputs: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Commit the response and tool_call confirms in one transaction.

        ``token_usage`` is no longer written here — the per-call
        decorator in ``application.usage`` writes one row per LLM call
        directly, so finalize-time persistence would double-count.
        """
        if not message_id:
            return False
        sources = sources or []
        for source in sources:
            if "text" in source and isinstance(source["text"], str):
                source["text"] = source["text"][:1000]

        merged_metadata: Dict[str, Any] = dict(metadata or {})
        if status == "failed" and error is not None:
            merged_metadata.setdefault(
                "error", f"{type(error).__name__}: {str(error)}"
            )

        update_fields: Dict[str, Any] = {
            "response": response,
            "status": status,
            "thought": thought,
            "sources": sources,
            "tool_calls": tool_calls or [],
            "metadata": merged_metadata,
        }
        if model_id is not None:
            update_fields["model_id"] = model_id

        # Single transaction for the data-integrity write — message
        # update and tool_call_attempts confirm share atomicity. The
        # message update is first so a failed match short-circuits
        # before the confirm runs. ``only_if_non_terminal`` keeps a
        # reconciler-set ``failed`` row from being silently retracted
        # by a late successful stream.
        with db_session() as conn:
            repo = ConversationsRepository(conn)
            ok = repo.update_message_by_id(
                message_id, update_fields,
                only_if_non_terminal=True,
            )
            if not ok:
                logger.warning(
                    f"finalize_message: no row updated for message_id={message_id} "
                    f"(possibly already terminal — reconciler may have escalated)"
                )
                return False
            repo.confirm_executed_tool_calls(message_id)

        # Title generation is a multi-second LLM round trip; doing it
        # outside the data-integrity txn avoids holding row locks across
        # network I/O. Failures here don't roll back the finalize.
        if title_inputs and status == "complete":
            try:
                with db_session() as conn:
                    self._maybe_generate_title(conn, message_id, title_inputs)
            except Exception as e:
                logger.error(
                    f"finalize_message title generation failed: {e}",
                    exc_info=True,
                )
        return True

    def _maybe_generate_title(
        self,
        conn,
        message_id: str,
        title_inputs: Dict[str, Any],
    ) -> None:
        """Generate an LLM-summarised conversation name if one isn't set yet."""
        llm = title_inputs.get("llm")
        question = title_inputs.get("question") or ""
        response = title_inputs.get("response") or ""
        fallback_name = title_inputs.get("fallback_name") or question[:50]
        if llm is None:
            return

        row = conn.execute(
            sql_text(
                "SELECT c.id, c.name FROM conversation_messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.id = CAST(:mid AS uuid)"
            ),
            {"mid": message_id},
        ).fetchone()
        if row is None:
            return
        conv_id, current_name = str(row[0]), row[1]
        if current_name and current_name != fallback_name:
            return

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
            model=getattr(llm, "model_id", None) or title_inputs.get("model_id"),
            messages=messages_summary,
            max_tokens=500,
        )
        if not completion or not completion.strip():
            completion = fallback_name or "New Conversation"
        conn.execute(
            sql_text(
                "UPDATE conversations SET name = :name, updated_at = now() "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": conv_id, "name": completion.strip()},
        )

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
                    # id from the streaming path. Gate on id shape so a
                    # non-UUID (legacy ObjectId that wasn't backfilled)
                    # doesn't reach CAST — the cast raises and spams the
                    # logs with a stack trace on every call.
                    if not looks_like_uuid(conversation_id):
                        return None
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
