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
from application.storage.db.repositories.token_usage import TokenUsageRepository
from application.storage.db.repositories.user_logs import UserLogsRepository
from application.storage.db.session import db_readonly, db_session
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

        # WAL: reserve the placeholder row before invoking the LLM so a
        # crash mid-stream still leaves the question (and a meaningful
        # placeholder) queryable from PG. Continuation reuses the
        # original placeholder; regenerate (``index`` set) truncates the
        # old answer at that position before reserving so the placeholder
        # *replaces* it instead of appending at the end of the
        # conversation.
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

        # Stream-scoped request id stamped on the agent's primary LLM.
        # The token-usage decorator writes this onto every row produced
        # by the run; ``count_in_range`` DISTINCTs on it so a multi-tool
        # agent run (which produces N rows) counts as one request.
        request_id = str(uuid.uuid4())
        primary_llm = getattr(agent, "llm", None)
        if primary_llm is not None:
            primary_llm._request_id = request_id

        # Flip pending → streaming on the first chunk so the reconciler
        # distinguishes "never started" from "in flight" rows.
        streaming_marked = False
        # Heartbeat extends a long stream's freshness via
        # ``metadata.last_heartbeat_at`` (read by the reconciler's
        # staleness check). It deliberately doesn't bump ``updated_at``
        # because reconciler-side writes share that column — using
        # metadata keeps the producer signal independent. Cadence is
        # wall-clock bounded by ``time.monotonic`` so a paused/blocked
        # event loop can't make the heartbeat appear fresh.
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

        # Stamp the placeholder id on the executor so tool_call_attempts
        # rows are message-correlated at proposed/executed time.
        if reserved_message_id and getattr(agent, "tool_executor", None):
            try:
                agent.tool_executor.message_id = reserved_message_id
            except Exception:
                pass

        try:
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
                        data = json.dumps({"type": "answer", "answer": line["answer"]})
                        yield f"data: {data}\n\n"
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
                        data = json.dumps(
                            {"type": "source", "source": truncated_sources}
                        )
                        yield f"data: {data}\n\n"
                elif "tool_calls" in line:
                    tool_calls = line["tool_calls"]
                    data = json.dumps({"type": "tool_calls", "tool_calls": tool_calls})
                    yield f"data: {data}\n\n"
                elif "thought" in line:
                    thought += line["thought"]
                    data = json.dumps({"type": "thought", "thought": line["thought"]})
                    yield f"data: {data}\n\n"
                elif "type" in line:
                    if line.get("type") == "tool_calls_pending":
                        # Save continuation state and end the stream
                        paused = True
                        data = json.dumps(line)
                        yield f"data: {data}\n\n"
                    elif line.get("type") == "error":
                        sanitized_error = {
                            "type": "error",
                            "error": sanitize_api_error(line.get("error", "An error occurred"))
                        }
                        data = json.dumps(sanitized_error)
                        yield f"data: {data}\n\n"
                    else:
                        data = json.dumps(line)
                        yield f"data: {data}\n\n"
            if is_structured and structured_chunks:
                structured_data = {
                    "type": "structured_answer",
                    "answer": response_full,
                    "structured": True,
                    "schema": schema_info,
                }
                data = json.dumps(structured_data)
                yield f"data: {data}\n\n"

            # ---- Paused: save continuation state and end stream early ----
            if paused:
                continuation = getattr(agent, "_pending_continuation", None)
                if continuation:
                    # Ensure we have a conversation_id — create a partial
                    # conversation if this is the first turn.
                    if not conversation_id and should_save_conversation:
                        try:
                            # Use model-owner scope so shared-agent
                            # owner-BYOM resolves to its registered plugin.
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
                                    # Persist BYOM scope so resume doesn't
                                    # fall back to caller's layer.
                                    "model_user_id": model_user_id,
                                    "llm_name": getattr(agent, "llm_name", settings.LLM_PROVIDER),
                                    "api_key": getattr(agent, "api_key", None),
                                    "user_api_key": user_api_key,
                                    "agent_id": agent_id,
                                    "agent_type": agent.__class__.__name__,
                                    "prompt": getattr(agent, "prompt", ""),
                                    "json_schema": getattr(agent, "json_schema", None),
                                    "retriever_config": getattr(agent, "retriever_config", None),
                                    # Carry the WAL placeholder forward so the
                                    # resumed run finalises the same row
                                    # instead of stranding it for the reconciler.
                                    "reserved_message_id": reserved_message_id,
                                },
                                client_tools=getattr(
                                    agent.tool_executor, "client_tools", None
                                ),
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to save continuation state: {str(e)}",
                                exc_info=True,
                            )

                id_data = {"type": "id", "id": str(conversation_id)}
                data = json.dumps(id_data)
                yield f"data: {data}\n\n"

                data = json.dumps({"type": "end"})
                yield f"data: {data}\n\n"
                return

            if isNoneDoc:
                for doc in source_log_docs:
                    doc["source"] = "None"
            # Run under model-owner scope so title-gen LLM inside
            # save_conversation uses the owner's BYOM provider/key.
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
            # This route-level LLM is used only for title generation
            # (the agent's stream tokens live on ``agent.llm``). Tag the
            # source so its rows land as ``source='title'``.
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
            # Resumed run completed without pausing again — drop the
            # continuation row now that the assistant message is final.
            # On crash/abort the row stays in ``resuming`` for the
            # janitor to revert; on a second pause the ``save_state``
            # branch above resets the row back to ``pending``.
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
            id_data = {"type": "id", "id": str(conversation_id)}
            data = json.dumps(id_data)
            yield f"data: {data}\n\n"

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

            data = json.dumps({"type": "end"})
            yield f"data: {data}\n\n"
        except GeneratorExit:
            logger.info(f"Stream aborted by client for question: {question[:50]}... ")
            # Save partial response

            if should_save_conversation and response_full:
                try:
                    if isNoneDoc:
                        for doc in source_log_docs:
                            doc["source"] = "None"
                    # Mirror the normal-path provider resolution so the
                    # partial-save title LLM uses the model-owner's BYOM
                    # registration (shared-agent dispatch) rather than
                    # the deployment default with the instance api key.
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
                    # See success-path comment: this route-level LLM
                    # only drives title generation. Tag its rows.
                    llm._token_usage_source = "title"
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
            data = json.dumps(
                {
                    "type": "error",
                    "error": "Please try again later. We apologize for any inconvenience.",
                }
            )
            yield f"data: {data}\n\n"
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
                event_data = line.replace("data: ", "").strip()
                event = json.loads(event_data)

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
