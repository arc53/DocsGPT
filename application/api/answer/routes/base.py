import datetime
import json
import logging
import threading
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
from application.storage.db.repositories.conversations import (
    HeartbeatState,
    MessageUpdateOutcome,
)
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

# Seconds between liveness stamps on an in-flight message row. 30 s keeps
# three stamps inside the reconciler's 5-minute staleness window and inside
# the replay watchdog's 90 s producer-idle window, so a single missed tick is
# never enough to trip either.
STREAM_HEARTBEAT_INTERVAL = 30
# Ceiling on how long the ticker will keep a row alive. Above the realistic
# worst case for a 25-round tool loop, but finite, so a wedged-but-alive
# stream still gets swept eventually.
STREAM_HEARTBEAT_MAX_SECONDS = 3600


class StreamSuperseded(Exception):
    """Raised to unwind a stream whose message row was deleted mid-flight.

    Not an error condition: the user replaced this turn (retry or edited
    question) and `truncate_after` removed the row. Carries the message id
    purely for logging.
    """


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
        # Set when a workflow agent run emits its ``workflow_run`` event; persisted
        # onto the message metadata so the chat can render the run's produced
        # artifacts on reload.
        workflow_run_id: Optional[str] = None
        is_structured = False
        schema_info = None
        structured_chunks = []
        query_metadata: Dict[str, Any] = {}
        paused = False
        # Set when the agent *yields* a terminal ``error`` event instead of
        # raising. Workflow node failures take that route (the engine catches
        # the node exception and reports it as an event), so the generator
        # returns normally and the ``except`` handler below never runs. Without
        # this flag the turn was finalized ``complete`` with an empty response:
        # the live client showed an error bubble, but on reload history mapped
        # the row to a blank answer with no error text and no retry.
        stream_error: Optional[str] = None
        # A ``tool_calls_pending`` event is held back and only flushed after
        # continuation state is committed (or the stateless finalize path is
        # reached): the v1 translator turns it into ``finish_reason:"tool_calls"``,
        # and a client that resumes on that signal would otherwise race
        # ``save_state``, miss the pending state, and fall back to the
        # transcript-rebuild round. That fallback still persists the final
        # answer when a conversation is mapped, but only as an appended
        # empty-prompt turn — it cannot finalize the reserved WAL row, which
        # would be stranded non-terminal for the reconciler.
        pending_pause_event: Optional[dict] = None

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
        # Input controls have to run before the question is stored, not only
        # inside ``gen``: this frame is what writes ``conversation_messages``
        # and ``user_logs``, so a redaction that reached the model prompt alone
        # would still leave the raw text — the PII the control exists to keep
        # out of storage — in both. ``gen`` re-runs the stage against the
        # original question and hits the agent's stage cache, so the scan is
        # paid for once.
        raw_question = question
        guard_input = getattr(agent, "apply_input_guardrails", None)
        if callable(guard_input) and not _continuation:
            try:
                question, _ = guard_input(question)
            except Exception:
                logger.exception(
                    "Input guardrail scan failed; persisting the question unredacted"
                )

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

        # Bind the row now so an audit flush that happens before the ``finally``
        # below — an input block returns from ``gen`` immediately and flushes
        # there — still writes rows linked to their message instead of orphans.
        bind_message_id = getattr(agent, "bind_guardrail_message_id", None)
        if callable(bind_message_id):
            try:
                bind_message_id(reserved_message_id)
            except Exception:
                logger.exception("Could not bind guardrail audit to the message row")

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
        # ``updated_at``, which reconciler-side writes share).
        # ``heartbeat_message`` only touches non-terminal rows, so stamping a
        # still-``pending`` row is safe and does NOT change its status.
        heartbeat_stop: Optional[threading.Event] = None
        # Set by the heartbeat ticker when it finds the row gone. Checked by
        # the emit loop, which is where the stream regains control.
        stream_cancelled = threading.Event()

        def _mark_streaming_once() -> None:
            """Flip the reserved row ``pending → streaming`` exactly once.

            Status-only: called on the first ``answer``/``sources`` chunk so
            the reconciler can distinguish "never started" from "in flight".
            It also re-stamps the heartbeat here for good measure, but the
            heartbeat liveness no longer depends on this transition (see
            ``_heartbeat_streaming``), so a thought-only reasoning phase that
            never reaches this point still stays live.
            """
            nonlocal streaming_marked
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
            # the seed at generation start and the background ticker below.
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

        def _start_heartbeat_ticker() -> "Optional[threading.Event]":
            """Stamp the liveness heartbeat on a timer for the stream's life.

            This replaces a per-chunk pump that could only stamp when a chunk
            flowed, which made liveness a function of *output* rather than of
            the stream actually being alive. Four windows are routinely silent
            — a provider round that emits only tool-call deltas, the body of a
            tool call, a same-primary retry or cross-provider fallback, and
            mid-execution compression — and any of them longer than the
            reconciler's threshold got a healthy stream swept and its answer
            discarded. The old pump was also interval-gated against the *last
            stamp*, so bursty output could leave the row 60 s staler than the
            last chunk suggested.

            Liveness stays honest because the ticker is an in-process daemon
            thread: every real death mode we see in production (gunicorn
            SIGKILL, worker OOM, ``max_requests`` recycle, host freeze) takes
            the thread with it, so the row goes stale on schedule and the
            reconciler still does its job. ``STREAM_HEARTBEAT_MAX_SECONDS``
            bounds the other direction — a hung-but-alive stream cannot keep a
            row alive forever.

            Returns:
                The stop event for the ticker, or None when there is no
                reserved row to stamp (headless/``/v1`` continuation rounds).
            """
            if not reserved_message_id:
                return None
            stop = threading.Event()
            message_id = reserved_message_id
            service = self.conversation_service
            cancelled = stream_cancelled

            def _tick() -> None:
                deadline = time.monotonic() + STREAM_HEARTBEAT_MAX_SECONDS
                while not stop.wait(STREAM_HEARTBEAT_INTERVAL):
                    if time.monotonic() > deadline:
                        logger.warning(
                            "stream heartbeat ticker hit its %ss ceiling for "
                            "message_id=%s; stopping",
                            STREAM_HEARTBEAT_MAX_SECONDS,
                            message_id,
                        )
                        return
                    try:
                        state = service.heartbeat_message_state(message_id)
                    except Exception:
                        # Swallowed deliberately: a transient DB blip must not
                        # kill the stream, and must never be mistaken for the
                        # row being gone. The reconciler is the backstop.
                        logger.exception(
                            "stream heartbeat update failed for %s", message_id,
                        )
                        continue
                    if state is HeartbeatState.MISSING:
                        # The row was deleted mid-stream — a retry or an
                        # edited question truncated this position away. Nothing
                        # this stream produces can ever be read, so stop the
                        # work instead of burning tool calls and LLM rounds
                        # into a void. Production saw a superseded stream run
                        # 4 further minutes and 12 further rounds.
                        logger.info(
                            "stream superseded: message row %s was deleted "
                            "mid-stream; cancelling",
                            message_id,
                            extra={
                                "alert": "stream_superseded",
                                "message_id": message_id,
                            },
                        )
                        cancelled.set()
                        return
                    if state is HeartbeatState.TERMINAL:
                        # Row exists but is complete/failed — usually the
                        # reconciler having swept it. Deliberately NOT
                        # cancelled: if this stream finishes, finalize is
                        # allowed to reclaim the row and land the real answer.
                        return

            threading.Thread(
                target=_tick,
                daemon=True,
                name=f"stream-heartbeat-{message_id[:8]}",
            ).start()
            return stop

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
                # The original text: ``gen`` runs the input stage itself and
                # applies the redaction to what it sends the model. Handing it
                # the already-redacted question would make that a second scan
                # over different text, and a remote check would be paid twice.
                gen_iter = agent.gen(query=raw_question)

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

            # The seed above covers t=0; the ticker takes over from the first
            # interval onwards, independently of whether anything is flowing.
            heartbeat_stop = _start_heartbeat_ticker()

            for line in gen_iter:
                # The emit loop is where the stream regains control between
                # rounds, so this is the cheapest place to honour a cancel.
                # Bound: a stream sitting inside one long tool call emits
                # nothing and is only cancelled when that call returns.
                if stream_cancelled.is_set():
                    raise StreamSuperseded(reserved_message_id or "")
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
                    # Emit even when empty. Suppressing it made "searched your
                    # sources and found nothing" indistinguishable from "no
                    # source was attached" — the client cannot tell a grounded
                    # answer from an ungrounded one, which is what hid a
                    # retrieval outage behind a confident, fabricated answer.
                    yield _emit({"type": "source", "source": truncated_sources})
                elif "tool_calls" in line:
                    tool_calls = line["tool_calls"]
                    yield _emit({"type": "tool_calls", "tool_calls": tool_calls})
                elif "thought" in line:
                    thought += line["thought"]
                    yield _emit({"type": "thought", "thought": line["thought"]})
                elif "type" in line:
                    if line.get("type") == "tool_calls_pending":
                        # Hold the pause event; it is flushed in the ``paused``
                        # block below only once continuation state is durable,
                        # so a fast client's resume can never arrive before
                        # the state it needs to claim.
                        paused = True
                        pending_pause_event = line
                    elif line.get("type") == "error":
                        # An event flagged ``user_facing`` already carries a curated,
                        # actionable message (e.g. an artifact-quota notice). Passing it
                        # through sanitize_api_error would substring-match words like
                        # "quota" and rewrite it into a misleading rate-limit message, so
                        # emit it verbatim; sanitize only raw/technical errors.
                        error_text = line.get("error", "An error occurred")
                        if not line.get("user_facing"):
                            error_text = sanitize_api_error(error_text)
                        stream_error = error_text
                        guardrail_meta = line.get("guardrail")
                        if guardrail_meta:
                            # A guardrail tripped mid-stream. Tokens already on
                            # the wire cannot be recalled, but the persisted
                            # message must not keep them — otherwise reloading
                            # the page redisplays exactly what was just blocked.
                            # ``thought`` counts: a reasoning model states its
                            # intent before acting on it, so the trace is where
                            # the blocked material appears first. The client
                            # clears it live, so leaving it here would surface
                            # it only on reload.
                            response_full = error_text
                            thought = ""
                            structured_chunks.clear()
                            is_structured = False
                            query_metadata["guardrail"] = guardrail_meta
                            yield _emit(
                                {
                                    "type": "guardrail",
                                    "guardrail": guardrail_meta,
                                    "retract": True,
                                }
                            )
                        yield _emit({"type": "error", "error": error_text})
                    elif line.get("type") == "notice":
                        # Non-fatal, non-terminal notice (e.g. some workflow input
                        # documents were dropped). Forwarded verbatim so the client can
                        # surface it without failing the turn; never sanitized as an error.
                        yield _emit({"type": "notice", "notice": line.get("notice", "")})
                    elif line.get("type") == "workflow_run":
                        # Stash the run id in the message metadata so every
                        # persistence path (finalize / save / abort / error) records
                        # it — the chat renders the run's produced artifacts from it
                        # on reload. Still forwarded so the live client captures it.
                        workflow_run_id = line.get("workflow_run_id")
                        if workflow_run_id:
                            query_metadata["workflow_run_id"] = workflow_run_id
                        yield _emit(line)
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

            # Record a yielded error before any early return so the pause /
            # stateless-tool-round paths persist it too. No producer currently
            # emits a non-terminal error and then pauses, but leaving the only
            # write below the pause blocks would make that combination lose the
            # error silently — the exact shape of the bug being fixed here.
            if stream_error:
                query_metadata.setdefault("error", stream_error)

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
                # calls from the ``tool_calls_pending`` event flushed below.
                if finalize_tool_pause_as_complete:
                    # No continuation state is written on this path; flush the
                    # held pause event now, in its original position ahead of
                    # the terminal id/end events.
                    if pending_pause_event is not None:
                        yield _emit(pending_pause_event)
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
                                    # Guardrails must survive the pause: a
                                    # resumed turn is still the same turn.
                                    "guardrails": (
                                        agent.guardrails_config.model_dump(mode="json")
                                        if getattr(agent, "guardrails_config", None)
                                        else None
                                    ),
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
                                    # OpenAI Responses continuity. This contains
                                    # only upstream ids and encrypted reasoning
                                    # blobs, never plaintext chain-of-thought.
                                    "responses_state": (
                                        agent.llm.export_responses_state()
                                        if callable(
                                            getattr(
                                                agent.llm,
                                                "export_responses_state",
                                                None,
                                            )
                                        )
                                        else None
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

                # Continuation state (and any first-turn conversation row) is
                # committed above; only now flush the held pause event so the
                # client's resume request can never beat the saved state.
                if pending_pause_event is not None:
                    yield _emit(pending_pause_event)
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
            # Hidden API conversations keep the deterministic fallback title.
            # Do not put an extra (potentially high-reasoning) LLM request on
            # their response critical path.
            llm = None
            if visibility == "listed":
                title_model_id = settings.TITLE_MODEL_ID or model_id
                provider = (
                    get_provider_from_model_id(
                        title_model_id,
                        user_id=model_user_id
                        or (decoded_token.get("sub") if decoded_token else None),
                    )
                    if title_model_id
                    else settings.LLM_PROVIDER
                )
                system_api_key = get_api_key_for_provider(
                    provider or settings.LLM_PROVIDER
                )
                llm = LLMCreator.create_llm(
                    provider or settings.LLM_PROVIDER,
                    api_key=system_api_key,
                    user_api_key=user_api_key,
                    decoded_token=decoded_token,
                    model_id=title_model_id,
                    agent_id=agent_id,
                    model_user_id=model_user_id,
                )
                llm._token_usage_source = "title"

            # The error was recorded above so the failure stays greppable, but
            # it only *fails* the turn when nothing was produced. An error
            # arriving after partial output (e.g. a later workflow node) must
            # stay ``complete``, since the client only renders ``response`` for
            # complete rows — failing it would discard text the user already
            # saw. ``structured_chunks`` counts as output for the same reason:
            # a structured answer lives there, not in ``response_full``.
            errored_empty = (
                bool(stream_error)
                and not response_full.strip()
                and not structured_chunks
            )

            if should_persist:
                if reserved_message_id is not None:
                    finalize_outcome = self.conversation_service.finalize_message(
                        reserved_message_id,
                        response_full,
                        thought=thought,
                        sources=source_log_docs,
                        tool_calls=tool_calls,
                        model_id=model_id or self.default_model_id,
                        metadata=query_metadata if query_metadata else None,
                        status="failed" if errored_empty else "complete",
                        title_inputs={
                            "llm": llm,
                            "question": question,
                            "response": response_full,
                            "model_id": model_id or self.default_model_id,
                            "fallback_name": (
                                question[:50] if question else "New Conversation"
                            ),
                        } if llm is not None else None,
                        async_title_generation=llm is not None,
                    )
                    # The outcome used to be discarded here, which is how a
                    # finished answer could vanish silently: if the row was
                    # deleted mid-stream (retry/edit truncation) the write
                    # lands nowhere and `activity_finished` still reports
                    # `ok`, because activity logging never observes the DB.
                    # Emit a distinct, countable signal instead.
                    if finalize_outcome is MessageUpdateOutcome.NOT_FOUND:
                        # The row can be gone for two very different reasons.
                        # A retry/edit deliberately replaced this turn — the
                        # user asked for the answer to be discarded, and the
                        # cancel flag could not reach us because the ticker
                        # that sets it lives in the superseding request's own
                        # process. That is routine and must not page anyone.
                        # Anything else is a genuinely orphaned answer.
                        superseded = self.conversation_service.was_superseded(
                            reserved_message_id
                        )
                        if superseded:
                            logger.info(
                                "stream superseded: message row %s was replaced "
                                "by a newer turn after %d chars; discarding "
                                "(conversation=%s)",
                                reserved_message_id,
                                len(response_full or ""),
                                conversation_id,
                                extra={
                                    "alert": "stream_superseded",
                                    "message_id": reserved_message_id,
                                    "conversation_id": (
                                        str(conversation_id) if conversation_id else None
                                    ),
                                    "answer_length": len(response_full or ""),
                                },
                            )
                        else:
                            logger.error(
                                "answer_persist_failed: message row %s no longer "
                                "exists; %d chars of answer were produced and "
                                "could not be saved (conversation=%s)",
                                reserved_message_id,
                                len(response_full or ""),
                                conversation_id,
                                extra={
                                    "alert": "answer_persist_failed",
                                    "message_id": reserved_message_id,
                                    "conversation_id": (
                                        str(conversation_id) if conversation_id else None
                                    ),
                                    "answer_length": len(response_full or ""),
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
                        status="failed" if errored_empty else "complete",
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
                    llm = None
                    if visibility == "listed":
                        title_model_id = settings.TITLE_MODEL_ID or model_id
                        provider = (
                            get_provider_from_model_id(
                                title_model_id,
                                user_id=model_user_id
                                or (
                                    decoded_token.get("sub")
                                    if decoded_token
                                    else None
                                ),
                            )
                            if title_model_id
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
                            model_id=title_model_id,
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
                            } if llm is not None else None,
                            async_title_generation=llm is not None,
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
        except StreamSuperseded as e:
            # Deliberately ahead of the generic handler below: this is not a
            # failure and must not be finalized as one. The row is gone, so
            # there is nothing to write and nothing to journal (the writer has
            # already latched on the same FK violation). The client that
            # replaced this turn is watching a different stream.
            logger.info(
                "stream superseded mid-flight for message_id=%s after "
                "%d chars; abandoning without persisting",
                str(e),
                len(response_full or ""),
                extra={
                    "alert": "stream_superseded",
                    "message_id": str(e),
                    "answer_length": len(response_full or ""),
                },
            )
            if journal_writer is not None:
                journal_writer.close()
            return
        except Exception as e:
            logger.error(f"Error in stream: {str(e)}", exc_info=True)
            # This process took the resume claim, so it owns releasing it. The
            # only other way back is ``revert_stale_resuming``'s 600 s grace,
            # which leaves the user locked out of their own conversation for
            # ten minutes after a resume that errored: ``load_state`` sees
            # only ``pending`` rows, so the paused turn is still resumable but
            # invisible, and every retry inside the window gets another 409.
            # Not on the ``StreamSuperseded`` path above — there the turn was
            # deliberately replaced and the row is legitimately gone.
            if _continuation and conversation_id:
                try:
                    ContinuationService().release_claim(
                        str(conversation_id),
                        decoded_token.get("sub", "local"),
                    )
                except Exception as release_err:
                    logger.error(
                        f"Failed to release resume claim after a failed "
                        f"resume: {release_err}",
                        exc_info=True,
                    )
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
        finally:
            # Every exit path — normal, client abort, error — must stop the
            # ticker, or a leaked thread keeps stamping a row nobody owns.
            # Harmless if it ever does leak (``heartbeat_message`` no-ops on
            # terminal rows) but the thread would live until the worker
            # recycles.
            if heartbeat_stop is not None:
                heartbeat_stop.set()
            # The audit trail must survive an aborted or failed turn — a
            # guardrail that fired on a stream the client dropped is exactly
            # the event an operator needs to see.
            flush_guardrails = getattr(agent, "flush_guardrail_audit", None)
            if callable(flush_guardrails):
                try:
                    flush_guardrails(reserved_message_id)
                except Exception:
                    logger.exception("Guardrail audit flush failed")

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
