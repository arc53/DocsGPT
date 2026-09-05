"""Conversation persistence service backed by Postgres.

Handles create / append / update / compression for conversations during
the answer-streaming path. Connections are opened per-operation rather
than held for the duration of a stream.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sql_text

from application.core.settings import settings
from application.api.answer.services.compression.types import (
    COMPRESSION_SUMMARY_MARKER,
    COMPRESSION_SUMMARY_PROMPT,
)
from application.storage.db.base_repository import looks_like_uuid
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import (
    ConversationsRepository,
    HeartbeatState,
    MessageUpdateOutcome,
)
from application.storage.db.session import db_readonly, db_session
from application.utils import strip_null_bytes


logger = logging.getLogger(__name__)


# Shown to the user if the worker dies mid-stream and the response is never finalised.
TERMINATED_RESPONSE_PLACEHOLDER = (
    "Response was terminated prior to completion, try regenerating."
)


def _final_finish_reason(llm: Any) -> Optional[str]:
    """Best-effort finish_reason of the round that actually produced the answer.

    Read from the responding provider — the fallback instance when a fallback
    served the stream, else the primary. Set by the Responses path, the
    non-streaming path, and (now) the chat-completions stream. ``None`` when
    unavailable (e.g. the stream was cut before any finish frame).
    """
    if llm is None:
        return None
    fallback = getattr(llm, "_fallback_llm", None)
    responding = getattr(llm, "_responding_provider", None)
    if fallback is not None and responding == getattr(fallback, "provider_name", None):
        fr = getattr(fallback, "_last_finish_reason", None)
        if fr is not None:
            return fr
    return getattr(llm, "_last_finish_reason", None)


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
        visibility: str = "hidden",
        status: str = "complete",
    ) -> str:
        """Save or update a conversation in Postgres.

        ``status`` lets a caller record a turn that failed without producing
        an answer. It defaults to ``complete``, matching the column default
        this path relied on before; passing ``failed`` is what stops a blank
        errored turn from rendering as an empty bubble with no retry.

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
            "status": status,
        }
        if metadata:
            message_payload["metadata"] = metadata

        # Classify empty answers at the point of persistence. A tool-request
        # turn (finish_reason=tool_calls — the /v1 client-tool loop) and a
        # genuine dead-end (finish_reason=stop with no visible content) both
        # persist an empty ``response`` and are otherwise indistinguishable in
        # the stored row; log the discriminators so they can be told apart.
        if not (response or "").strip():
            logger.info(
                "empty_answer_persisted",
                extra={
                    "model": model_id,
                    "finish_reason": _final_finish_reason(llm),
                    "has_tool_calls": bool(tool_calls),
                    "tool_call_count": len(tool_calls or []),
                    "thought_len": len(thought or ""),
                    "responding_provider": getattr(llm, "_responding_provider", None),
                    "conversation_id": conversation_id,
                },
            )

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
            completion = None
            if llm is not None:
                completion = llm.gen(
                    model=getattr(llm, "model_id", None) or model_id,
                    messages=messages_summary,
                    max_tokens=2000,
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
                    visibility=visibility,
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
        visibility: str = "hidden",
        status: str = "pending",
        index: Optional[int] = None,
    ) -> Dict[str, str]:
        """Reserve the placeholder message row before the LLM call.

        ``index`` triggers regenerate semantics: messages at
        ``position >= index`` are truncated so the new placeholder
        lands at ``position = index`` rather than appending.

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
                    visibility=visibility,
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

    def was_superseded(self, message_id: str) -> bool:
        """True when a retry/edit truncation deleted this message's row.

        Args:
            message_id: The reserved message id the stream was writing to.

        Returns:
            True if the row was deliberately superseded rather than lost.
        """
        if not message_id:
            return False
        with db_readonly() as conn:
            return ConversationsRepository(conn).was_superseded(message_id)

    def heartbeat_message(self, message_id: str) -> bool:
        """Bump ``message_metadata.last_heartbeat_at`` so the reconciler's
        staleness sweep counts the row as alive. No-ops on terminal rows.
        """
        if not message_id:
            return False
        with db_session() as conn:
            return ConversationsRepository(conn).heartbeat_message(message_id)

    def heartbeat_message_state(self, message_id: str) -> HeartbeatState:
        """Heartbeat, reporting whether the row is live, terminal, or gone.

        Args:
            message_id: UUID of the message row.

        Returns:
            HeartbeatState: What the row was at stamp time.
        """
        if not message_id:
            return HeartbeatState.MISSING
        with db_session() as conn:
            return ConversationsRepository(conn).heartbeat_message_state(
                message_id
            )

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
        async_title_generation: bool = False,
    ) -> MessageUpdateOutcome:
        """Commit the response and tool_call confirms in one transaction.

        The outcome propagates directly from ``update_message_by_id`` so
        callers (notably the SSE abort handler) can tell a fresh
        finalize from "the row was already terminal" — the latter must
        still be treated as success when the prior state was
        ``complete``.
        """
        if not message_id:
            return MessageUpdateOutcome.INVALID
        sources = sources or []
        for source in sources:
            if "text" in source and isinstance(source["text"], str):
                source["text"] = source["text"][:1000]

        merged_metadata: Dict[str, Any] = dict(metadata or {})
        if status == "failed" and error is not None:
            merged_metadata.setdefault(
                "error", f"{type(error).__name__}: {str(error)}"
            )

        # Postgres rejects NUL in text and jsonb; a NUL-laden tool result
        # reaching this transaction would lose the whole conversation save.
        update_fields: Dict[str, Any] = strip_null_bytes(
            {
                "response": response,
                "status": status,
                "thought": thought,
                "sources": sources,
                "tool_calls": tool_calls or [],
                "metadata": merged_metadata,
            }
        )
        if model_id is not None:
            update_fields["model_id"] = model_id

        # Atomic message update + tool_call_attempts confirm; the
        # ``only_if_non_terminal`` guard prevents a late stream from
        # retracting a row the reconciler already escalated.
        #
        # Exception: a *successful* finalize is allowed to reclaim a row the
        # reconciler failed for staleness. A stream that reaches this point
        # with an answer was self-evidently not stuck, so refusing it throws
        # away real output and leaves the user staring at "Response was
        # terminated prior to completion". Only on success — a late failure
        # must never overwrite the reconciler's failure with a different one.
        reclaim = status == "complete"
        with db_session() as conn:
            repo = ConversationsRepository(conn)
            outcome = repo.update_message_by_id(
                message_id, update_fields,
                only_if_non_terminal=True,
                reclaim_reconciler_failed=reclaim,
            )
            if outcome is not MessageUpdateOutcome.UPDATED:
                logger.warning(
                    f"finalize_message: no row updated for message_id={message_id} "
                    f"(outcome={outcome.value} — possibly already terminal)"
                )
                return outcome
            repo.confirm_executed_tool_calls(message_id)

        # Outside the txn — title-gen is a multi-second LLM round trip.
        # ``failed`` counts too: the conversation is still listed, and
        # ``_maybe_generate_title`` only regenerates while the name is still
        # the question-prefix fallback. Skipping it here would strand a
        # conversation whose first turn failed with the raw prompt as its
        # name forever, because by turn two the fallback no longer matches.
        if title_inputs and status in ("complete", "failed"):
            if async_title_generation:
                threading.Thread(
                    target=self._generate_title_safely,
                    args=(message_id, title_inputs),
                    name="docsgpt-title-generation",
                    daemon=True,
                ).start()
            else:
                self._generate_title_safely(message_id, title_inputs)
        return MessageUpdateOutcome.UPDATED

    def _generate_title_safely(
        self, message_id: str, title_inputs: Dict[str, Any]
    ) -> None:
        """Generate a title in its own DB transaction without surfacing errors."""
        try:
            with db_session() as conn:
                self._maybe_generate_title(conn, message_id, title_inputs)
        except Exception as e:
            logger.error(
                f"finalize_message title generation failed: {e}",
                exc_info=True,
            )

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
            # Reasoning-capable default models spend the whole budget inside
            # reasoning_content before emitting any title, so 500 came back empty
            # (finish_reason=length). Give room to finish and still produce the
            # 3-word title; non-reasoning models stop far short of this cap.
            max_tokens=2000,
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
                    "prompt": COMPRESSION_SUMMARY_PROMPT,
                    # Durable marker: replay filters on this, not on the label.
                    "metadata": {COMPRESSION_SUMMARY_MARKER: True},
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
