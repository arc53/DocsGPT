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
        should_persist: bool = True,
        visibility: str = "hidden",
        attachment_ids: Optional[List[str]] = None,
        agent_id: Optional[str] = None,
        is_shared_usage: bool = False,
        shared_token: Optional[str] = None,
        model_id: Optional[str] = None,
        model_user_id: Optional[str] = None,
        _continuation: Optional[Dict] = None,
        finalize_tool_pause_as_complete: bool = False,
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
            should_persist: Whether to persist the conversation
            visibility: ``listed`` (sidebar) or ``hidden`` for a new
                conversation; defaults to ``hidden`` so only callers that
                explicitly opt in (the first-party UI) list rows
            attachment_ids: List of attachment IDs
            agent_id: ID of agent used
            is_shared_usage: Flag for shared agent usage
            shared_token: Token for shared agent
            model_id: Model ID used for the request
            retrieved_docs: Pre-fetched documents for sources (optional)
            finalize_tool_pause_as_complete: Stateless-tool-round mode for
                the OpenAI-compatible ``/v1/chat/completions`` endpoint.
                OpenAI clients resume a tool call by re-POSTing the full
                message history (no slot for our ``reserved_message_id``),
                so the server cannot rely on a *native* resume to finalize
                a paused assistant turn. When ``True`` and the agent pauses
                for a client-executed tool, the reserved row is finalized
                as ``status="complete"`` (recording the emitted
                ``tool_calls``) and the stream ends, instead of writing a
                ``pending_tool_state`` record and early-returning a
                non-terminal row. This guarantees a ``/v1`` tool round
                never strands a ``pending``/``streaming`` row for the
                reconciler to fail. Defaults to ``False``, which preserves
                the native ``/stream`` + ``/api/answer`` pause/resume UX
                byte-for-byte (still writes ``pending_tool_state``, leaves
                the row non-terminal, and resumes natively).

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
        # Intentional: a continuation round reserves no new WAL row, so on the
        # stateless ``/v1`` path the intermediate tool rounds aren't persisted
        # (only the first turn + the final answer turn are). Accepted as-is.
        wal_eligible = should_persist and not _continuation
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
                    visibility=visibility,
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

        # Flipped to ``streaming`` on the first ``answer``/``sources`` chunk;
        # the reconciler reads ``status`` to tell "never started" from "in
        # flight". This is a *status* signal only — it is intentionally
        # decoupled from the heartbeat below, which is an "agent is alive /
        # producing output" signal (a reasoning model can stream ``thought``
        # chunks for minutes before its first answer token, never marking
        # ``streaming``, yet must still count as live).
        streaming_marked = False
        # Heartbeat goes into ``metadata.last_heartbeat_at`` (not
        # ``updated_at``, which reconciler-side writes share) and uses
        # ``time.monotonic`` so a blocked event loop can't fake fresh.
        # ``heartbeat_message`` only touches non-terminal rows, so stamping a
        # still-``pending`` row is safe and does NOT change its status.
        STREAM_HEARTBEAT_INTERVAL = 60
        last_heartbeat_at = time.monotonic()

        def _mark_streaming_once() -> None:
            """Flip the reserved row ``pending → streaming`` exactly once.

            Status-only: called on the first ``answer``/``sources`` chunk so
            the reconciler can distinguish "never started" from "in flight".
            It also re-stamps the heartbeat here for good measure, but the
            heartbeat liveness no longer depends on this transition (see
            ``_heartbeat_streaming``), so a thought-only reasoning phase that
            never reaches this point still stays live.
            """
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
            # Re-stamp last_heartbeat_at on the transition too; harmless given
            # the seed at generation start and the per-interval pump below.
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
            """Pump the liveness heartbeat once per ``STREAM_HEARTBEAT_INTERVAL``.

            Deliberately gated on ``reserved_message_id`` only — NOT on
            ``streaming_marked``. The loop calls this for *every* chunk
            (including ``thought``/``metadata``), so a reasoning model that
            streams only ``thought`` chunks while it "thinks" keeps a still-
            ``pending`` row's ``last_heartbeat_at`` fresh and stays out of the
            reconciler's staleness sweep. ``heartbeat_message`` only updates
            non-terminal rows, so this never resurrects or restatuses a
            terminal row.

            Residual: a model that emits NO chunks at all (not even
            ``thought``) for longer than the reconciler threshold still goes
            stale, because this pump only ticks when a chunk flows. Covering a
            fully-silent stream would require a background-thread heartbeat or
            a higher staleness threshold; both are out of scope here. The
            realistic reasoning case (``thought`` chunks streaming) is covered.
            """
            nonlocal last_heartbeat_at
            if not reserved_message_id:
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
        # The reservation above may create the conversation row (first turn in
        # a new chat). Propagate that fresh id to the tool_executor so tools
        # that need a conversation home (e.g. ``scheduler`` in agentless chats)
        # see it on the very first call instead of waiting for the next turn.
        if conversation_id and getattr(agent, "tool_executor", None):
            try:
                agent.tool_executor.conversation_id = str(conversation_id)
            except Exception:
                logger.debug(
                    "Could not set tool_executor.conversation_id post-reserve",
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
                    reasoning_content=_continuation.get("reasoning_content", ""),
                )
            else:
                gen_iter = agent.gen(query=question)

            # Seed a liveness heartbeat the moment generation starts, before
            # the first chunk. The row is still ``pending`` here; this stamps a
            # fresh ``last_heartbeat_at`` so a model that takes a while to emit
            # its first token (or only streams ``thought`` chunks) is protected
            # from the reconciler's staleness sweep from t=0 — not only from the
            # first interval tick after the first answer chunk.
            if reserved_message_id:
                try:
                    self.conversation_service.heartbeat_message(
                        reserved_message_id,
                    )
                except Exception:
                    logger.exception(
                        "generation-start heartbeat seed failed for %s",
                        reserved_message_id,
                    )
                last_heartbeat_at = time.monotonic()

            for line in gen_iter:
                # Cheap closure check that only hits the DB when the heartbeat
                # interval has elapsed. Runs for *every* chunk (incl. ``thought``
                # / ``metadata``), so a still-``pending`` reasoning stream stays
                # live without waiting for the ``streaming`` status flip.
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

                # ---- Stateless-tool-round mode (OpenAI-compatible /v1) ----
                # OpenAI clients resume by re-POSTing the whole message
                # history with ``{role:"tool"}`` results — there is no slot
                # for our ``reserved_message_id``, so a *native* resume can't
                # finalize this paused turn. Finalize the reserved row as
                # ``complete`` here (recording the emitted tool_calls) and end
                # the stream, so the reconciler never sees a non-terminal row.
                # The client still gets ``finish_reason:"tool_calls"`` + the
                # calls from the ``tool_calls_pending`` event yielded above.
                if finalize_tool_pause_as_complete:
                    yield from self._finalize_stateless_tool_pause(
                        continuation=continuation,
                        reserved_message_id=reserved_message_id,
                        conversation_id=conversation_id,
                        question=question,
                        response_full=response_full,
                        thought=thought,
                        source_log_docs=source_log_docs,
                        tool_calls=tool_calls,
                        query_metadata=query_metadata,
                        model_id=model_id,
                        should_persist=should_persist,
                        emit=_emit,
                    )
                    if journal_writer is not None:
                        journal_writer.close()
                    return

                if continuation:
                    # First-turn pause needs a conversation row to attach to.
                    if not conversation_id and should_persist:
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
                                    visibility=visibility,
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
                                    # Persisted in agent_config (rather than
                                    # a new column) so resume rebuilds the
                                    # paused assistant message with the
                                    # reasoning DeepSeek thinking mode
                                    # requires on the follow-up turn.
                                    "reasoning_content": continuation.get(
                                        "reasoning_content", ""
                                    ),
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

                    # Notify the user out-of-band so they can navigate back and
                    # resolve the pause. Only ``awaiting_approval`` pauses need a
                    # human; ``requires_client_execution`` pauses are resolved by
                    # the client, so notifying for those is non-actionable noise.
                    # Also gated on ``state_saved``: a missing pending_tool_state
                    # row would 404 the resume endpoint.
                    user_id_for_event = (
                        decoded_token.get("sub") if decoded_token else None
                    )
                    approval_calls = [
                        tc
                        for tc in (
                            continuation.get("pending_tool_calls", [])
                            if continuation
                            else []
                        )
                        if isinstance(tc, dict)
                        and tc.get("pause_type") == "awaiting_approval"
                    ]
                    if (
                        state_saved
                        and user_id_for_event
                        and conversation_id
                        and approval_calls
                    ):
                        # Trim each pending tool call to its identifying metadata
                        # so a multi-MB argument can't blow out the per-event
                        # payload cap. Full args come from pending_tool_state.
                        pending_summaries = [
                            {
                                k: tc.get(k)
                                for k in (
                                    "call_id",
                                    "tool_name",
                                    "action_name",
                                    "name",
                                )
                                if tc.get(k) is not None
                            }
                            for tc in approval_calls
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

            if should_persist:
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
                        visibility=visibility,
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
            if should_persist and response_full:
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
                            visibility=visibility,
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

    def _finalize_stateless_tool_pause(
        self,
        *,
        continuation: Optional[Dict[str, Any]],
        reserved_message_id: Optional[str],
        conversation_id: Optional[str],
        question: str,
        response_full: str,
        thought: str,
        source_log_docs: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
        query_metadata: Dict[str, Any],
        model_id: Optional[str],
        should_persist: bool,
        emit: Any,
    ) -> Generator[str, None, None]:
        """Finalize a client-tool pause as ``complete`` for the ``/v1`` path.

        Used only when ``complete_stream`` runs with
        ``finalize_tool_pause_as_complete=True`` (the OpenAI-compatible
        ``/v1/chat/completions`` endpoint). Records the emitted/pending
        ``tool_calls`` on the reserved row and flips it to ``complete`` so the
        reconciler never sweeps it, then yields the terminal ``id``/``end``
        events. No ``pending_tool_state`` is written: an OpenAI client resumes
        statelessly (re-POSTing the full history) rather than via a native
        resume, so there is no server-side continuation record to load.

        Args:
            continuation: The agent's ``_pending_continuation`` (may be None).
            reserved_message_id: WAL placeholder row id, if one was reserved.
            conversation_id: The conversation id to surface to the client.
            question: The user's question for this turn.
            response_full: Any assistant text produced before the pause.
            thought: Reasoning tokens produced before the pause.
            source_log_docs: Retrieval sources gathered before the pause.
            tool_calls: Tool-call events emitted during this turn.
            query_metadata: Accumulated stream metadata.
            model_id: Model id used for the request.
            should_persist: Whether persistence is enabled for this request.
            emit: The stream's ``_emit`` callable for SSE framing/journaling.

        Yields:
            The terminal ``id`` and ``end`` SSE event strings.
        """
        # Prefer the structured pending tool calls (carry call_id / name /
        # arguments) so the persisted row is a coherent record of what the
        # client was asked to execute; fall back to whatever ``tool_calls``
        # events were emitted.
        pending_tool_calls = (
            continuation.get("pending_tool_calls") if continuation else None
        )
        tool_calls_to_persist = pending_tool_calls or tool_calls or []

        if should_persist and reserved_message_id is not None:
            try:
                self.conversation_service.finalize_message(
                    reserved_message_id,
                    response_full,
                    thought=thought,
                    sources=source_log_docs,
                    tool_calls=tool_calls_to_persist,
                    model_id=model_id or self.default_model_id,
                    metadata=query_metadata if query_metadata else None,
                    status="complete",
                )
            except Exception as e:
                logger.error(
                    f"Failed to finalize stateless tool pause as complete "
                    f"for message_id={reserved_message_id}: {e}",
                    exc_info=True,
                )
        # When there is no reserved row (stateless OpenAI round with no
        # conversation_id — the translator sets persist=false), there is
        # nothing durable to finalize and nothing stranded: just end cleanly
        # without writing an empty-prompt orphan conversation.

        yield emit({"type": "id", "id": str(conversation_id)})
        yield emit({"type": "end"})

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
                    thought += event["thought"]
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
