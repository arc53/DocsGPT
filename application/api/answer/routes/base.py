import datetime
import json
import logging
import time
import uuid
from typing import Any, Dict, Generator, List, Optional

from flask import jsonify, make_response, Response
from flask_restx import Namespace

from application.api.answer.services.continuation_service import ContinuationService
from application.api.answer.services.conversation_service import (
    ConversationService,
    TERMINATED_RESPONSE_PLACEHOLDER,
)
from application.core.model_utils import (
    get_api_key_for_provider,
    get_default_model_id,
    get_provider_from_model_id,
)

from application.core.settings import settings
from application.error import sanitize_api_error
from application.llm.llm_creator import LLMCreator
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import MessageUpdateOutcome
from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.repositories.user_logs import UserLogsRepository
from application.storage.db.session import db_readonly, db_session
from application.events.publisher import publish_user_event
from application.streaming.event_replay import format_sse_event
from application.streaming.message_journal import (
    BatchedJournalWriter,
    record_event,
)
from application.utils import check_required_fields

logger = logging.getLogger(__name__)


answer_ns = Namespace("answer", description="Answer related operations", path="/")


class BaseAnswerResource:
    """Shared base class for answer endpoints"""

    def __init__(self):
        self.default_model_id = get_default_model_id()
        self.conversation_service = ConversationService()

    def validate_request(
        self, data: Dict[str, Any], require_conversation_id: bool = False
    ) -> Optional[Response]:
        """Common request validation.

        Continuation requests (``tool_actions`` present) require
        ``conversation_id`` but not ``question``.
        """
        if data.get("tool_actions"):
            # Continuation mode — question is not required
            if missing := check_required_fields(data, ["conversation_id"]):
                return missing
            return None
        required_fields = ["question"]
        if require_conversation_id:
            required_fields.append("conversation_id")
        if missing_fields := check_required_fields(data, required_fields):
            return missing_fields
        return None

    @staticmethod
    def _prepare_tool_calls_for_logging(
        tool_calls: Optional[List[Dict[str, Any]]], max_chars: int = 10000
    ) -> List[Dict[str, Any]]:
        if not tool_calls:
            return []

        prepared = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                prepared.append({"result": str(tool_call)[:max_chars]})
                continue

            item = dict(tool_call)
            for key in ("result", "result_full"):
                value = item.get(key)
                if isinstance(value, str) and len(value) > max_chars:
                    item[key] = value[:max_chars]
            prepared.append(item)
        return prepared

    def check_usage(self, agent_config: Dict) -> Optional[Response]:
        """Check if there is a usage limit and if it is exceeded

        Args:
            agent_config: The config dict of agent instance

        Returns:
            None or Response if either of limits exceeded.

        """
        api_key = agent_config.get("user_api_key")
        if not api_key:
            return None
        with db_readonly() as conn:
            agent = AgentsRepository(conn).find_by_key(api_key)

        if not agent:
            return make_response(
                jsonify({"success": False, "message": "Invalid API key."}), 401
            )
        limited_token_mode_raw = agent.get("limited_token_mode", False)
        limited_request_mode_raw = agent.get("limited_request_mode", False)

        limited_token_mode = (
            limited_token_mode_raw
            if isinstance(limited_token_mode_raw, bool)
            else limited_token_mode_raw == "True"
        )
        limited_request_mode = (
            limited_request_mode_raw
            if isinstance(limited_request_mode_raw, bool)
            else limited_request_mode_raw == "True"
        )

        token_limit = int(
            agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"]
        )
        request_limit = int(
            agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"]
        )

        end_date = datetime.datetime.now(datetime.timezone.utc)
        start_date = end_date - datetime.timedelta(hours=24)

        if limited_token_mode or limited_request_mode:
            with db_readonly() as conn:
                token_repo = TokenUsageRepository(conn)
                if limited_token_mode:
                    daily_token_usage = token_repo.sum_tokens_in_range(
                        start=start_date, end=end_date, api_key=api_key,
                    )
                else:
                    daily_token_usage = 0
                if limited_request_mode:
                    daily_request_usage = token_repo.count_in_range(
                        start=start_date, end=end_date, api_key=api_key,
                    )
                else:
                    daily_request_usage = 0
        else:
            daily_token_usage = 0
            daily_request_usage = 0
        if not limited_token_mode and not limited_request_mode:
            return None
        token_exceeded = (
            limited_token_mode and token_limit > 0 and daily_token_usage >= token_limit
        )
        request_exceeded = (
            limited_request_mode
            and request_limit > 0
            and daily_request_usage >= request_limit
        )

        if token_exceeded or request_exceeded:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Exceeding usage limit, please try again later.",
                    }
                ),
                429,
            )
        return None

    def complete_stream(
        self,
        question: str,
        agent: Any,
        conversation_id: Optional[str],
        user_api_key: Optional[str],
        decoded_token: Dict[str, Any],
        isNoneDoc: bool = False,
        index: Optional[int] = None,
        should_save_conversation: bool = True,
        attachment_ids: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
        model_id: Optional[str] = None,
        model_user_id: Optional[str] = None,
        _continuation: Optional[Dict] = None,
    ) -> Generator[str, None, None]:
        """
        Generator function that streams the complete conversation response.

        Args:
            question: The user's question
            agent: The agent instance
            retriever: The retriever instance
            conversation_id: Existing conversation ID
            user_api_key: User's API key if any
            decoded_token: Decoded JWT token
            isNoneDoc: Flag for document-less responses
            index: Index of message to update
            should_save_conversation: Whether to persist the conversation
            attachment_ids: List of attachment IDs
            agent_id: ID of agent used
            is_shared_usage: Flag for shared agent usage
            shared_token: Token for shared agent
            model_id: Model ID used for the request
            retrieved_docs: Pre-fetched documents for sources (optional)

        Yields:
            Server-sent event strings
        """
        response_full, thought, source_log_docs, tool_calls = "", "", [], []
        is_structured = False
        schema_info = None
        structured_chunks = []
        query_metadata: Dict[str, Any] = {}
        paused = False

        # One id shared across the WAL row, primary LLM (token_usage
        # attribution), the SSE event, and resumed continuations.
        request_id = (
            _continuation.get("request_id") if _continuation else None
        ) or str(uuid.uuid4())

        # Reserve the placeholder row before the LLM call so a crash
        # mid-stream still leaves the question queryable. Continuations
        # reuse the original placeholder.
        reserved_message_id: Optional[str] = None
        wal_eligible = should_save_conversation and not _continuation
        if wal_eligible:
            try:
                reservation = self.conversation_service.save_user_question(
                    conversation_id=conversation_id,
                    question=question,
                    decoded_token=decoded_token,
                    attachment_ids=attachment_ids,
                    api_key=user_api_key,
                    agent_id=agent_id,
                    is_shared_usage=is_shared_usage,
                    shared_token=shared_token,
                    model_id=model_id or self.default_model_id,
                    request_id=request_id,
                    index=index,
                )
                conversation_id = reservation["conversation_id"]
                reserved_message_id = reservation["message_id"]
            except Exception as e:
                logger.error(
                    f"Failed to reserve message row before stream: {e}",
                    exc_info=True,
                )
        elif _continuation and _continuation.get("reserved_message_id"):
            reserved_message_id = _continuation["reserved_message_id"]

        primary_llm = getattr(agent, "llm", None)
        if primary_llm is not None:
            primary_llm._request_id = request_id

        # Flipped to ``streaming`` on first chunk; reconciler uses this
        # to tell "never started" from "in flight".
        streaming_marked = False
        # Heartbeat goes into ``metadata.last_heartbeat_at`` (not
        # ``updated_at``, which reconciler-side writes share) and uses
        # ``time.monotonic`` so a blocked event loop can't fake fresh.
        STREAM_HEARTBEAT_INTERVAL = 60
        last_heartbeat_at = time.monotonic()

        def _mark_streaming_once() -> None:
            nonlocal streaming_marked, last_heartbeat_at
            if streaming_marked or not reserved_message_id:
                return
            try:
                self.conversation_service.update_message_status(
                    reserved_message_id, "streaming",
                )
            except Exception:
                logger.exception(
                    "update_message_status streaming failed for %s",
                    reserved_message_id,
                )
            # Seed last_heartbeat_at so watchdog doesn't fall back to `timestamp`
            # (creation time) before the first STREAM_HEARTBEAT_INTERVAL tick.
            try:
                self.conversation_service.heartbeat_message(
                    reserved_message_id,
                )
            except Exception:
                logger.exception(
                    "initial heartbeat seed failed for %s",
                    reserved_message_id,
                )
            streaming_marked = True
            last_heartbeat_at = time.monotonic()

        def _heartbeat_streaming() -> None:
            nonlocal last_heartbeat_at
            if not reserved_message_id or not streaming_marked:
                return
            now_mono = time.monotonic()
            if now_mono - last_heartbeat_at < STREAM_HEARTBEAT_INTERVAL:
                return
            try:
                self.conversation_service.heartbeat_message(
                    reserved_message_id,
                )
            except Exception:
                logger.exception(
                    "stream heartbeat update failed for %s",
                    reserved_message_id,
                )
            last_heartbeat_at = now_mono

        # Correlates tool_call_attempts rows with this message.
        if reserved_message_id and getattr(agent, "tool_executor", None):
            try:
                agent.tool_executor.message_id = reserved_message_id
            except Exception:
                logger.debug(
                    "Could not set tool_executor.message_id; tool-call correlation will be missing for message_id=%s",
                    reserved_message_id,
                )

        # Per-stream monotonic SSE event id. Allocated by ``_emit`` and
        # threaded through both the wire format (``id: <seq>\\n``) and
        # the journal write so a reconnecting client can ``Last-Event-
        # ID`` past anything they already saw. Continuations resume
        # against the original ``reserved_message_id`` — seed the
        # allocator from the journal's high-water mark so we don't
        # collide on the duplicate-PK and silently lose every emit
        # past the resume point.
        sequence_no = -1
        if _continuation and reserved_message_id:
            try:
                from application.storage.db.repositories.message_events import (
                    MessageEventsRepository,
                )

                with db_readonly() as conn:
                    latest = MessageEventsRepository(conn).latest_sequence_no(
                        reserved_message_id
                    )
                if latest is not None:
                    sequence_no = latest
            except Exception:
                logger.exception(
                    "Continuation seq seed lookup failed for message_id=%s; "
                    "falling back to seq=-1 (duplicate-PK collisions will "
                    "be swallowed)",
                    reserved_message_id,
                )

        # One batched journal writer per stream.
        journal_writer: Optional[BatchedJournalWriter] = (
            BatchedJournalWriter(reserved_message_id)
            if reserved_message_id
            else None
        )

        def _emit(payload: dict) -> str:
            """Format-and-journal one SSE event.

            With a reserved ``message_id``, buffers into the journal and
            emits ``id: <seq>``-tagged SSE frames; otherwise falls back to
            legacy ``data: ...\\n\\n`` framing.
            """
            nonlocal sequence_no
            if not reserved_message_id or journal_writer is None:
                return f"data: {json.dumps(payload)}\n\n"
            sequence_no += 1
            seq = sequence_no
            event_type = (
                payload.get("type", "data")
                if isinstance(payload, dict)
                else "data"
            )
            normalised = payload if isinstance(payload, dict) else {"value": payload}
            journal_writer.record(seq, event_type, normalised)
            return format_sse_event(normalised, seq)

        try:
            # Surface the placeholder id before any LLM tokens so a
            # mid-handshake disconnect still has a row to tail-poll.
            if reserved_message_id:
                yield _emit(
                    {
                        "type": "message_id",
                        "message_id": reserved_message_id,
                        "conversation_id": (
                            str(conversation_id) if conversation_id else None
                        ),
                        "request_id": request_id,
                    }
                )

            if _continuation:
                gen_iter = agent.gen_continuation(
                    messages=_continuation["messages"],
                    tools_dict=_continuation["tools_dict"],
                    pending_tool_calls=_continuation["pending_tool_calls"],
                    tool_actions=_continuation["tool_actions"],
                )
            else:
                gen_iter = agent.gen(query=question)

            for line in gen_iter:
                # Cheap closure check that only hits the DB when the
                # heartbeat interval has elapsed.
                _heartbeat_streaming()
                if "metadata" in line:
                    query_metadata.update(line["metadata"])
                elif "answer" in line:
                    _mark_streaming_once()
                    response_full += str(line["answer"])
                    if line.get("structured"):
                        is_structured = True
                        schema_info = line.get("schema")
                        structured_chunks.append(line["answer"])
                    else:
                        yield _emit(
                            {"type": "answer", "answer": line["answer"]}
                        )
                elif "sources" in line:
                    _mark_streaming_once()
                    truncated_sources = []
                    source_log_docs = line["sources"]
                    for source in line["sources"]:
                        truncated_source = source.copy()
                        if "text" in truncated_source:
                            truncated_source["text"] = (
                                truncated_source["text"][:100].strip() + "..."
                            )
                        truncated_sources.append(truncated_source)
                    if truncated_sources:
                        yield _emit(
                            {"type": "source", "source": truncated_sources}
                        )
                elif "tool_calls" in line:
                    tool_calls = line["tool_calls"]
                    yield _emit({"type": "tool_calls", "tool_calls": tool_calls})
                elif "thought" in line:
                    thought += line["thought"]
                    yield _emit({"type": "thought", "thought": line["thought"]})
                elif "type" in line:
                    if line.get("type") == "tool_calls_pending":
                        # Save continuation state and end the stream
                        paused = True
                        yield _emit(line)
                    elif line.get("type") == "error":
                        yield _emit(
                            {
                                "type": "error",
                                "error": sanitize_api_error(
                                    line.get("error", "An error occurred")
                                ),
                            }
                        )
                    else:
                        yield _emit(line)
            if is_structured and structured_chunks:
                yield _emit(
                    {
                        "type": "structured_answer",
                        "answer": response_full,
                        "structured": True,
                        "schema": schema_info,
                    }
                )

            # ---- Paused: save continuation state and end stream early ----
            if paused:
                continuation = getattr(agent, "_pending_continuation", None)
                if continuation:
                    # First-turn pause needs a conversation row to attach to.
                    if not conversation_id and should_save_conversation:
                        try:
                            provider = (
                                get_provider_from_model_id(
                                    model_id,
                                    user_id=model_user_id
                                    or (
                                        decoded_token.get("sub")
                                        if decoded_token
                                        else None
                                    ),
                                )
                                if model_id
                                else settings.LLM_PROVIDER
                            )
                            sys_api_key = get_api_key_for_provider(
                                provider or settings.LLM_PROVIDER
                            )
                            llm = LLMCreator.create_llm(
                                provider or settings.LLM_PROVIDER,
                                api_key=sys_api_key,
                                user_api_key=user_api_key,
                                decoded_token=decoded_token,
                                model_id=model_id,
                                agent_id=agent_id,
                                model_user_id=model_user_id,
                            )
                            conversation_id = (
                                self.conversation_service.save_conversation(
                                    None,
                                    question,
                                    response_full,
                                    thought,
                                    source_log_docs,
                                    tool_calls,
                                    llm,
                                    model_id or self.default_model_id,
                                    decoded_token,
                                    api_key=user_api_key,
                                    agent_id=agent_id,
                                    is_shared_usage=is_shared_usage,
                                    shared_token=shared_token,
                                )
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to create conversation for continuation: {e}",
                                exc_info=True,
                            )

                    state_saved = False
                    if conversation_id:
                        try:
                            cont_service = ContinuationService()
                            cont_service.save_state(
                                conversation_id=str(conversation_id),
                                user=decoded_token.get("sub", "local"),
                                messages=continuation["messages"],
                                pending_tool_calls=continuation["pending_tool_calls"],
                                tools_dict=continuation["tools_dict"],
                                tool_schemas=getattr(agent, "tools", []),
                                agent_config={
                                    "model_id": model_id or self.default_model_id,
                                    # BYOM scope; without it resume falls
                                    # back to caller's layer.
                                    "model_user_id": model_user_id,
                                    "llm_name": getattr(agent, "llm_name", settings.LLM_PROVIDER),
                                    "api_key": getattr(agent, "api_key", None),
                                    "user_api_key": user_api_key,
                                    "agent_id": agent_id,
                                    "agent_type": agent.__class__.__name__,
                                    "prompt": getattr(agent, "prompt", ""),
                                    "json_schema": getattr(agent, "json_schema", None),
                                    "retriever_config": getattr(agent, "retriever_config", None),
                                    # Reused on resume so the same WAL row
                                    # is finalised and request_id stays
                                    # consistent across token_usage rows.
                                    "reserved_message_id": reserved_message_id,
                                    "request_id": request_id,
                                },
                                client_tools=getattr(
                                    agent.tool_executor, "client_tools", None
                                ),
                            )
                            state_saved = True
                        except Exception as e:
                            logger.error(
                                f"Failed to save continuation state: {str(e)}",
                                exc_info=True,
                            )

                    # Notify the user out-of-band so they can navigate
                    # back to the conversation and decide on the
                    # pending tool calls. Gated on ``state_saved``: a
                    # missing pending_tool_state row would 404 the
                    # resume endpoint, so an unfulfillable notification
                    # is worse than no notification.
                    user_id_for_event = (
                        decoded_token.get("sub") if decoded_token else None
                    )
                    if state_saved and user_id_for_event and conversation_id:
                        pending_calls = continuation.get(
                            "pending_tool_calls", []
                        ) if continuation else []
                        # Trim each pending tool call to its identifying
                        # metadata so a tool with a multi-MB argument
                        # doesn't blow out the per-event payload size
                        # cap. The resume page fetches full args from
                        # ``pending_tool_state`` regardless.
                        pending_summaries = [
                            {
                                k: tc.get(k)
                                for k in (
                                    "call_id",
                                    "tool_name",
                                    "action_name",
                                    "name",
                                )
                                if isinstance(tc, dict) and tc.get(k) is not None
                            }
                            for tc in (pending_calls or [])
                            if isinstance(tc, dict)
                        ]
                        publish_user_event(
                            user_id_for_event,
                            "tool.approval.required",
                            {
                                "conversation_id": str(conversation_id),
                                "message_id": reserved_message_id,
                                "pending_tool_calls": pending_summaries,
                            },
                            scope={
                                "kind": "conversation",
                                "id": str(conversation_id),
                            },
                        )

                yield _emit({"type": "id", "id": str(conversation_id)})
                yield _emit({"type": "end"})
                # Drain the terminal ``end`` so a reconnecting client
                # sees it on snapshot — same reason as the main exit.
                if journal_writer is not None:
                    journal_writer.close()
                return

            if isNoneDoc:
                for doc in source_log_docs:
                    doc["source"] = "None"
            # Model-owner scope so title-gen uses owner's BYOM key.
            provider = (
                get_provider_from_model_id(
                    model_id,
                    user_id=model_user_id
                    or (decoded_token.get("sub") if decoded_token else None),
                )
                if model_id
                else settings.LLM_PROVIDER
            )
            system_api_key = get_api_key_for_provider(provider or settings.LLM_PROVIDER)

            llm = LLMCreator.create_llm(
                provider or settings.LLM_PROVIDER,
                api_key=system_api_key,
                user_api_key=user_api_key,
                decoded_token=decoded_token,
                model_id=model_id,
                agent_id=agent_id,
                model_user_id=model_user_id,
            )
            # Title-gen only; agent stream tokens live on ``agent.llm``.
            llm._token_usage_source = "title"

            if should_save_conversation:
                if reserved_message_id is not None:
                    self.conversation_service.finalize_message(
                        reserved_message_id,
                        response_full,
                        thought=thought,
                        sources=source_log_docs,
                        tool_calls=tool_calls,
                        model_id=model_id or self.default_model_id,
                        metadata=query_metadata if query_metadata else None,
                        status="complete",
                        title_inputs={
                            "llm": llm,
                            "question": question,
                            "response": response_full,
                            "model_id": model_id or self.default_model_id,
                            "fallback_name": (
                                question[:50] if question else "New Conversation"
                            ),
                        },
                    )
                else:
                    conversation_id = self.conversation_service.save_conversation(
                        conversation_id,
                        question,
                        response_full,
                        thought,
                        source_log_docs,
                        tool_calls,
                        llm,
                        model_id or self.default_model_id,
                        decoded_token,
                        index=index,
                        api_key=user_api_key,
                        agent_id=agent_id,
                        is_shared_usage=is_shared_usage,
                        shared_token=shared_token,
                        attachment_ids=attachment_ids,
                        metadata=query_metadata if query_metadata else None,
                    )
                # Persist compression metadata/summary if it exists and wasn't saved mid-execution
                compression_meta = getattr(agent, "compression_metadata", None)
                compression_saved = getattr(agent, "compression_saved", False)
                if conversation_id and compression_meta and not compression_saved:
                    try:
                        self.conversation_service.update_compression_metadata(
                            conversation_id, compression_meta
                        )
                        self.conversation_service.append_compression_message(
                            conversation_id, compression_meta
                        )
                        agent.compression_saved = True
                        logger.info(
                            f"Persisted compression metadata for conversation {conversation_id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to persist compression metadata: {str(e)}",
                            exc_info=True,
                        )
            else:
                conversation_id = None
            # Resume finished cleanly; drop the continuation row.
            # Crash-paths leave it ``resuming`` for the janitor to revert.
            if _continuation and conversation_id:
                try:
                    cont_service = ContinuationService()
                    cont_service.delete_state(
                        str(conversation_id),
                        decoded_token.get("sub", "local"),
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to delete continuation state on resume "
                        f"completion: {e}",
                        exc_info=True,
                    )
            yield _emit({"type": "id", "id": str(conversation_id)})

            tool_calls_for_logging = self._prepare_tool_calls_for_logging(
                getattr(agent, "tool_calls", tool_calls) or tool_calls
            )

            log_data = {
                "action": "stream_answer",
                "level": "info",
                "user": decoded_token.get("sub"),
                "api_key": user_api_key,
                "agent_id": agent_id,
                "question": question,
                "response": response_full,
                "sources": source_log_docs,
                "tool_calls": tool_calls_for_logging,
                "attachments": attachment_ids,
                "timestamp": datetime.datetime.now(datetime.timezone.utc),
            }
            if is_structured:
                log_data["structured_output"] = True
                if schema_info:
                    log_data["schema"] = schema_info
            # Clean up text fields to be no longer than 10000 characters

            for key, value in log_data.items():
                if isinstance(value, str) and len(value) > 10000:
                    log_data[key] = value[:10000]
            try:
                with db_session() as conn:
                    UserLogsRepository(conn).insert(
                        user_id=log_data.get("user"),
                        endpoint="stream_answer",
                        data=log_data,
                    )
            except Exception as log_err:
                logger.error(
                    f"Failed to persist stream_answer user log: {log_err}",
                    exc_info=True,
                )

            yield _emit({"type": "end"})
            # Drain the journal buffer so the terminal ``end`` event is
            # visible to any reconnecting client. Without this the
            # client could snapshot up to the last flush boundary and
            # then live-tail waiting for an ``end`` that's still
            # sitting in memory.
            if journal_writer is not None:
                journal_writer.close()
        except GeneratorExit:
            logger.info(f"Stream aborted by client for question: {question[:50]}... ")
            # Drain any buffered events before the terminal one-shot
            # ``record_event`` below — keeps the journal's seq order
            # contiguous (buffered events ... terminal event). ``close``
            # is idempotent; pairing it with ``flush`` matches the
            # normal-exit and error branches so any future ``record()``
            # past this point would log instead of silently buffering.
            if journal_writer is not None:
                journal_writer.flush()
                journal_writer.close()
            # Save partial response

            # Whether the DB row was flipped to ``complete`` during this
            # abort handler. Drives the choice of terminal journal event
            # below: journal ``end`` only when the row actually matches,
            # else journal ``error`` so a reconnecting client sees a
            # failed terminal state instead of a blank "success".
            finalized_complete = False
            if should_save_conversation and response_full:
                try:
                    if isNoneDoc:
                        for doc in source_log_docs:
                            doc["source"] = "None"
                    # Resolve under model-owner scope so shared-agent
                    # title-gen uses owner BYOM, not deployment default.
                    provider = (
                        get_provider_from_model_id(
                            model_id,
                            user_id=model_user_id
                            or (
                                decoded_token.get("sub")
                                if decoded_token
                                else None
                            ),
                        )
                        if model_id
                        else settings.LLM_PROVIDER
                    )
                    sys_api_key = get_api_key_for_provider(
                        provider or settings.LLM_PROVIDER
                    )
                    llm = LLMCreator.create_llm(
                        provider or settings.LLM_PROVIDER,
                        api_key=sys_api_key,
                        user_api_key=user_api_key,
                        decoded_token=decoded_token,
                        model_id=model_id,
                        agent_id=agent_id,
                        model_user_id=model_user_id,
                    )
                    llm._token_usage_source = "title"
                    if reserved_message_id is not None:
                        outcome = self.conversation_service.finalize_message(
                            reserved_message_id,
                            response_full,
                            thought=thought,
                            sources=source_log_docs,
                            tool_calls=tool_calls,
                            model_id=model_id or self.default_model_id,
                            metadata=query_metadata if query_metadata else None,
                            status="complete",
                            title_inputs={
                                "llm": llm,
                                "question": question,
                                "response": response_full,
                                "model_id": model_id or self.default_model_id,
                                "fallback_name": (
                                    question[:50] if question else "New Conversation"
                                ),
                            },
                        )
                        # ``ALREADY_COMPLETE`` means the normal-path
                        # finalize at line 632 won the race: the DB row
                        # is already at ``complete`` and the reconnect
                        # journal should reflect that with ``end``,
                        # not a spurious ``error``.
                        finalized_complete = outcome in (
                            MessageUpdateOutcome.UPDATED,
                            MessageUpdateOutcome.ALREADY_COMPLETE,
                        )
                    else:
                        self.conversation_service.save_conversation(
                            conversation_id,
                            question,
                            response_full,
                            thought,
                            source_log_docs,
                            tool_calls,
                            llm,
                            model_id or self.default_model_id,
                            decoded_token,
                            index=index,
                            api_key=user_api_key,
                            agent_id=agent_id,
                            is_shared_usage=is_shared_usage,
                            shared_token=shared_token,
                            attachment_ids=attachment_ids,
                            metadata=query_metadata if query_metadata else None,
                        )
                        # No journal row to gate, but flag the save as
                        # successful for symmetry with the WAL path.
                        finalized_complete = True
                    compression_meta = getattr(agent, "compression_metadata", None)
                    compression_saved = getattr(agent, "compression_saved", False)
                    if conversation_id and compression_meta and not compression_saved:
                        try:
                            self.conversation_service.update_compression_metadata(
                                conversation_id, compression_meta
                            )
                            self.conversation_service.append_compression_message(
                                conversation_id, compression_meta
                            )
                            agent.compression_saved = True
                            logger.info(
                                f"Persisted compression metadata for conversation {conversation_id} (partial stream)"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to persist compression metadata (partial stream): {str(e)}",
                                exc_info=True,
                            )
                except Exception as e:
                    logger.error(
                        f"Error saving partial response: {str(e)}", exc_info=True
                    )
            # Journal a terminal event so reconnecting clients stop tailing;
            # ``end`` only when the row is ``complete``, else ``error``.
            if reserved_message_id is not None:
                try:
                    sequence_no += 1
                    if finalized_complete:
                        # Match the wire shape ``_emit({"type": "end"})``
                        # uses on the normal path — the replay terminal
                        # check at ``event_replay._payload_is_terminal``
                        # reads ``payload.type``, and the frontend parses
                        # the same key off ``data:``.
                        record_event(
                            reserved_message_id,
                            sequence_no,
                            "end",
                            {"type": "end"},
                        )
                    else:
                        # Nothing was persisted under the complete status
                        # — mark the row failed so the reconciler doesn't
                        # need to sweep it, and journal an ``error`` so a
                        # reconnecting client surfaces the same failure
                        # the UI would show on a live error.
                        try:
                            self.conversation_service.finalize_message(
                                reserved_message_id,
                                response_full or TERMINATED_RESPONSE_PLACEHOLDER,
                                thought=thought,
                                sources=source_log_docs,
                                tool_calls=tool_calls,
                                model_id=model_id or self.default_model_id,
                                metadata=query_metadata if query_metadata else None,
                                status="failed",
                                error=ConnectionError(
                                    "client disconnected before response was persisted"
                                ),
                            )
                        except Exception as fin_err:
                            logger.error(
                                f"Failed to mark aborted message failed: {fin_err}",
                                exc_info=True,
                            )
                        record_event(
                            reserved_message_id,
                            sequence_no,
                            "error",
                            {
                                "type": "error",
                                "error": "Stream aborted before any response was produced.",
                                "code": "client_disconnect",
                            },
                        )
                except Exception as journal_err:
                    logger.error(
                        f"Failed to journal terminal event on abort: {journal_err}",
                        exc_info=True,
                    )
            raise
        except Exception as e:
            logger.error(f"Error in stream: {str(e)}", exc_info=True)
            if reserved_message_id is not None:
                try:
                    self.conversation_service.finalize_message(
                        reserved_message_id,
                        response_full or TERMINATED_RESPONSE_PLACEHOLDER,
                        thought=thought,
                        sources=source_log_docs,
                        tool_calls=tool_calls,
                        model_id=model_id or self.default_model_id,
                        metadata=query_metadata if query_metadata else None,
                        status="failed",
                        error=e,
                    )
                except Exception as fin_err:
                    logger.error(
                        f"Failed to finalize errored message: {fin_err}",
                        exc_info=True,
                    )
            yield _emit(
                {
                    "type": "error",
                    "error": "Please try again later. We apologize for any inconvenience.",
                }
            )
            # Drain the terminal ``error`` event we just yielded so a
            # reconnecting client sees it on snapshot.
            if journal_writer is not None:
                journal_writer.close()
            return

    def process_response_stream(self, stream) -> Dict[str, Any]:
        """Process the stream response for non-streaming endpoint.

        Returns:
            Dict with keys: conversation_id, answer, sources, tool_calls,
            thought, error, and optional extra.
        """
        conversation_id = ""
        response_full = ""
        source_log_docs = []
        tool_calls = []
        thought = ""
        stream_ended = False
        is_structured = False
        schema_info = None
        pending_tool_calls = None

        for line in stream:
            try:
                # Each chunk may carry an ``id: <seq>`` header before
                # the ``data:`` line. Pull just the ``data:`` body so
                # the JSON decode doesn't choke on the SSE framing.
                event_data = ""
                for raw in line.split("\n"):
                    if raw.startswith("data:"):
                        event_data = raw[len("data:") :].lstrip()
                        break
                if not event_data:
                    continue
                event = json.loads(event_data)
                # The ``message_id`` event is informational for the
                # streaming consumer and has no synchronous-API field;
                # skip it so the type-switch below doesn't KeyError.
                if event.get("type") == "message_id":
                    continue

                if event["type"] == "id":
                    conversation_id = event["id"]
                elif event["type"] == "answer":
                    response_full += event["answer"]
                elif event["type"] == "structured_answer":
                    response_full = event["answer"]
                    is_structured = True
                    schema_info = event.get("schema")
                elif event["type"] == "source":
                    source_log_docs = event["source"]
                elif event["type"] == "tool_calls":
                    tool_calls = event["tool_calls"]
                elif event["type"] == "tool_calls_pending":
                    pending_tool_calls = event.get("data", {}).get(
                        "pending_tool_calls", []
                    )
                elif event["type"] == "thought":
                    thought = event["thought"]
                elif event["type"] == "error":
                    logger.error(f"Error from stream: {event['error']}")
                    return {
                        "conversation_id": None,
                        "answer": None,
                        "sources": None,
                        "tool_calls": None,
                        "thought": None,
                        "error": event["error"],
                    }
                elif event["type"] == "end":
                    stream_ended = True
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Error parsing stream event: {e}, line: {line}")
                continue
        if not stream_ended:
            logger.error("Stream ended unexpectedly without an 'end' event.")
            return {
                "conversation_id": None,
                "answer": None,
                "sources": None,
                "tool_calls": None,
                "thought": None,
                "error": "Stream ended unexpectedly",
            }

        result: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "answer": response_full,
            "sources": source_log_docs,
            "tool_calls": tool_calls,
            "thought": thought,
            "error": None,
        }

        if pending_tool_calls is not None:
            result["extra"] = {"pending_tool_calls": pending_tool_calls}

        if is_structured:
            result["extra"] = {"structured": True, "schema": schema_info}

        return result

    def error_stream_generate(self, err_response):
        data = json.dumps({"type": "error", "error": err_response})
        yield f"data: {data}\n\n"
