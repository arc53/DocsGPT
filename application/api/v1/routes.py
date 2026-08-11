"""Standard chat completions API routes.

Exposes ``/v1/chat/completions`` and ``/v1/models`` endpoints that
follow the widely-adopted chat completions protocol so external tools
(opencode, continue, etc.) can connect to DocsGPT agents.
"""

import json
import logging
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Generator, Optional

from flask import Blueprint, jsonify, make_response, request, Response

from application.api.answer.routes.base import BaseAnswerResource
from application.api.answer.services.persistence_policy import resolve_persistence
from application.api.answer.services.continuation_service import (
    ContinuationService,
    ResumeInProgressError,
)
from application.api.answer.services.stream_processor import StreamProcessor
from application.api.v1 import idempotency as v1_idempotency
from application.api.v1.session_store import (
    V1Session,
    delete_conversation,
    identify_session,
    load_conversation,
    save_conversation,
)
from application.api.v1.translator import (
    StreamTranslationState,
    make_usage_chunk,
    translate_request,
    translate_response,
    translate_stream_event,
)
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.session import db_readonly
from application.streaming.sse_keepalive import with_sse_keepalive

logger = logging.getLogger(__name__)

v1_bp = Blueprint("v1", __name__, url_prefix="/v1")


def _extract_bearer_token() -> Optional[str]:
    """Extract API key from Authorization: Bearer header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _lookup_agent(api_key: str) -> Optional[Dict]:
    """Look up the agent document for this API key."""
    try:
        with db_readonly() as conn:
            return AgentsRepository(conn).find_by_key(api_key)
    except Exception:
        logger.warning("Failed to look up agent for API key", exc_info=True)
        return None


def _get_model_name(agent: Optional[Dict], api_key: str) -> str:
    """Return agent name for display as model name."""
    if agent:
        return agent.get("name", api_key)
    return api_key


def _invalid_request(message: str, code: Optional[str] = None) -> Response:
    """Return an OpenAI-shaped invalid-request response."""
    return make_response(
        jsonify({
            "error": {
                "message": message,
                "type": "invalid_request_error",
                **({"code": code} if code else {}),
            }
        }),
        400,
    )


def _validate_request_options(data: Dict[str, Any], agent: Dict[str, Any]) -> Optional[Response]:
    """Reject unsupported options instead of silently changing semantics."""
    # The API key, not the OpenAI ``model`` placeholder, selects the agent.
    # Keep accepting arbitrary model strings as documented for compatibility
    # with clients that require a locally configured model alias.
    if data.get("n") not in (None, 1):
        return _invalid_request("DocsGPT currently supports only n=1.")
    if data.get("logprobs") not in (None, False):
        return _invalid_request("logprobs is not supported by this endpoint.")
    stream_options = data.get("stream_options")
    if stream_options is not None and not isinstance(stream_options, dict):
        return _invalid_request("stream_options must be an object.")
    return None


def _conversation_belongs_to_agent(
    conversation_id: str, user_id: str, agent_id: str
) -> bool:
    """Return whether a conversation is accessible and bound to this agent."""
    if not conversation_id or not user_id or not agent_id:
        return False
    try:
        with db_readonly() as conn:
            conversation = ConversationsRepository(conn).get_any(
                str(conversation_id), str(user_id)
            )
    except Exception:
        logger.warning("Failed to authorize v1 conversation", exc_info=True)
        return False
    return bool(
        conversation
        and conversation.get("agent_id")
        and str(conversation["agent_id"]) == str(agent_id)
    )


def _response_usage(agent: Any) -> Dict[str, Any]:
    """Return the turn's cumulative usage in Chat Completions shape.

    Reads the per-instance accumulator so multi-round tool turns report
    the sum of every LLM call, matching what ``token_usage`` rows bill;
    the accumulator carries provider-exact counts whenever the upstream
    reported them (see ``_prefer_provider_usage``).
    """
    tokens = getattr(getattr(agent, "llm", None), "token_usage", {}) or {}
    prompt = int(tokens.get("prompt_tokens", 0) or 0)
    completion = int(tokens.get("generated_tokens", 0) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _response_finish_reason(agent: Any) -> str:
    """Return the upstream terminal reason understood by Chat Completions."""
    reason = getattr(getattr(agent, "llm", None), "_last_finish_reason", None)
    return reason if reason in {"stop", "length"} else "stop"


class _V1AnswerHelper(BaseAnswerResource):
    """Thin wrapper to access complete_stream / process_response_stream."""
    pass


@v1_bp.route("/chat/completions", methods=["POST"])
def chat_completions():
    """Handle POST /v1/chat/completions."""
    api_key = _extract_bearer_token()
    if not api_key:
        return make_response(
            jsonify({"error": {"message": "Missing Authorization header", "type": "auth_error"}}),
            401,
        )

    data = request.get_json()
    if not data or not data.get("messages"):
        return make_response(
            jsonify({"error": {"message": "messages field is required", "type": "invalid_request"}}),
            400,
        )

    is_stream = data.get("stream", False)
    agent_doc = _lookup_agent(api_key)
    if not agent_doc:
        return make_response(
            jsonify({"error": {"message": "Invalid API key", "type": "auth_error"}}),
            401,
        )
    options_error = _validate_request_options(data, agent_doc)
    if options_error is not None:
        return options_error
    model_name = _get_model_name(agent_doc, api_key)

    # ---- Layer-1 idempotency (opt-in, non-streaming only) ----
    # An ``Idempotency-Key`` header makes a retried non-streaming request
    # return the stored first response instead of re-running the agent
    # (restoring the guard lost when the v1 tool round dropped the native
    # ``resume_from_tool_actions`` / ``mark_resuming`` path → would otherwise
    # duplicate the answer row and double-bill tokens). Streaming replay is
    # intentionally NOT supported (see the ``is_stream`` branch below), so we
    # only resolve a key for non-streaming requests. No header → byte-for-byte
    # today's behavior.
    idem_key: Optional[str] = None
    if not is_stream:
        raw_key, key_error = v1_idempotency.read_idempotency_key()
        if key_error is not None:
            return key_error
        # Scope per tenant: ``{agent_id}:{key}`` so two agents using the same
        # key value never collide. Fall back to api_key scoping when the agent
        # has no resolvable id (idempotency still keyed, just per api_key).
        agent_scope = None
        if agent_doc is not None:
            agent_scope = str(agent_doc.get("id") or agent_doc.get("_id") or "") or None
        idem_key = v1_idempotency.scoped_key(raw_key, agent_scope or api_key)

    try:
        internal_data = translate_request(data, api_key)
    except Exception as e:
        logger.error(f"/v1/chat/completions translate error: {e}", exc_info=True)
        return make_response(
            jsonify({"error": {"message": "Failed to process request", "type": "invalid_request"}}),
            400,
        )

    agent_id_value = str(agent_doc.get("id") or agent_doc.get("_id") or "")
    client_session = identify_session(request.headers, data, agent_id_value)
    explicit_conversation = (
        request.headers.get("X-DocsGPT-Conversation-ID")
        or internal_data.get("conversation_id")
    )
    conversation_from_session = False
    if explicit_conversation:
        internal_data["conversation_id"] = explicit_conversation
    elif not internal_data.get("conversation_id"):
        correlated_conversation = load_conversation(client_session)
        if correlated_conversation:
            internal_data["conversation_id"] = correlated_conversation
            conversation_from_session = True

    # Link decoded_token to the agent's owner so continuation state,
    # logs, and tool execution use the correct user identity. The PG
    # ``agents`` row exposes the owner via ``user_id`` (``user`` is the
    # legacy Mongo field name kept in ``row_to_dict`` only for the
    # mapping ``id``/``_id``).
    agent_user = (
        (agent_doc.get("user_id") or agent_doc.get("user"))
        if agent_doc else None
    )
    decoded_token = {"sub": agent_user or "api_key_user"}

    conversation_id = internal_data.get("conversation_id")
    if conversation_id and not _conversation_belongs_to_agent(
        str(conversation_id), str(decoded_token["sub"]), agent_id_value
    ):
        if conversation_from_session:
            # A deleted or reassigned conversation must not poison this client
            # session for the remainder of its Redis TTL. Start a fresh hidden
            # conversation and replace the mapping after the request succeeds.
            delete_conversation(client_session)
            internal_data.pop("conversation_id", None)
        else:
            return _invalid_request(
                "Conversation not found for the authenticated agent.",
                code="conversation_not_found",
            )

    if internal_data.get("tool_actions") and internal_data.get("conversation_id"):
        internal_data["persist"] = True

    try:
        processor = StreamProcessor(internal_data, decoded_token)

        if internal_data.get("tool_actions"):
            conversation_id = internal_data.get("conversation_id")
            pending_state = (
                ContinuationService().claim_state(
                    conversation_id, decoded_token["sub"]
                )
                if conversation_id
                else None
            )
            if conversation_id and pending_state:
                (
                    agent,
                    messages,
                    tools_dict,
                    pending_tool_calls,
                    tool_actions,
                    reasoning_content,
                ) = processor.resume_from_tool_actions(
                    internal_data["tool_actions"],
                    conversation_id,
                    claimed_state=pending_state,
                )
                processor.conversation_id = conversation_id
            else:
                # Compatibility fallback for old/completed conversations and
                # clients that resend the full transcript without resumable
                # server state. StreamProcessor still enforces conversation
                # ownership while loading history.
                (
                    agent,
                    messages,
                    tools_dict,
                    pending_tool_calls,
                    tool_actions,
                    reasoning_content,
                ) = processor.build_continuation_from_messages(
                    internal_data.get("messages", []),
                    internal_data["tool_actions"],
                )
                # A missing/expired durable continuation has no reserved WAL
                # row to finalize, so nothing mid-loop is persisted — but the
                # FINAL turn of this round must still land in the mapped
                # conversation, else a loop whose first resume produces the
                # answer (one pause, then stop — the common single-search
                # shape) persists only the empty tool-call row and the answer
                # is lost upstream. With persist on, the finished answer is
                # APPENDED as a new empty-prompt turn (there is no reserved
                # row to finalize into); that's the accepted shape here. No
                # worthless rows appear along the way: continuation rounds
                # reserve no WAL row and the pause path never appends. Only a
                # round with no mapped conversation at all stays stateless.
                internal_data["persist"] = bool(internal_data.get("conversation_id"))
            continuation = {
                "messages": messages,
                "tools_dict": tools_dict,
                "pending_tool_calls": pending_tool_calls,
                "tool_actions": tool_actions,
                "reasoning_content": reasoning_content,
                # Stateful compatibility resumes must finalize the original
                # WAL placeholder and keep its request attribution. Omitting
                # these made OpenCode rounds append an orphan response while
                # leaving the initial message permanently ``streaming``.
                "reserved_message_id": processor.reserved_message_id,
                "request_id": processor.request_id,
            }
            question = ""
        else:
            # Normal mode
            question = internal_data.get("question", "")
            agent = processor.build_agent(question)
            continuation = None

        if not processor.decoded_token:
            return make_response(
                jsonify({"error": {"message": "Unauthorized", "type": "auth_error"}}),
                401,
            )

        helper = _V1AnswerHelper()
        usage_error = helper.check_usage(processor.agent_config)
        if usage_error:
            return usage_error

        # v1 always persists (unless the translator opted out for a stateless
        # tool round) and never lists in the agent owner's sidebar — only the
        # first-party UI opts a conversation into ``visibility: "listed"``.
        should_persist, visibility = resolve_persistence(
            persist_flag=internal_data.get("persist"),
        )
        # Only strip leaked reasoning from content for structured requests -- the
        # only path where models echo reasoning into content -- so legitimate
        # answers that mention the marker text are never corrupted.
        strip_reasoning_leak = bool(
            internal_data.get("json_schema") or internal_data.get("json_object")
        )
        finalize_stateless_tool_pause = bool(
            client_session is None and not internal_data.get("conversation_id")
        )

        if is_stream:
            # Idempotency replay is NOT supported for streaming: there is no
            # safe way to re-emit a recorded SSE stream (and the regression /
            # b2b client is non-streaming), so a streaming request never
            # claims a key. This is a known, accepted limitation.
            return Response(
                with_sse_keepalive(
                    _stream_response(
                        helper,
                        question,
                        agent,
                        processor,
                        model_name,
                        continuation,
                        should_persist,
                        visibility,
                        strip_reasoning_leak,
                        bool((data.get("stream_options") or {}).get("include_usage")),
                        client_session,
                        finalize_stateless_tool_pause,
                    ),
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        # ---- Non-streaming: claim-before-process, then finalize/release ----
        # Claim happens here (after auth + agent resolution + continuation
        # build, immediately before running the agent) so a duplicate retry
        # short-circuits to the cached body / 409 instead of re-running.
        if idem_key:
            claimed, replay = v1_idempotency.claim_or_replay(idem_key)
            if not claimed:
                # ``completed`` cache hit, or a 409 for an in-flight same-key
                # request — either way return without re-running the agent.
                return replay

        # An exception from the agent run propagates to the ``except`` handlers
        # below, which release the claim so a genuine retry can re-claim.
        response = _non_stream_response(
            helper,
            question,
            agent,
            processor,
            model_name,
            continuation,
            should_persist,
            visibility,
            strip_reasoning_leak,
            client_session,
            finalize_stateless_tool_pause,
        )

        # Cache only successful (2xx) responses; ``finalize`` releases the
        # claim on a non-2xx so a real retry can still succeed (matches OpenAI).
        if idem_key:
            v1_idempotency.finalize(idem_key, response)
        return response

    except ResumeInProgressError:
        if idem_key:
            v1_idempotency.release(idem_key)
        return make_response(
            jsonify({
                "error": {
                    "message": "Resume already in progress for this conversation.",
                    "type": "conflict_error",
                    "code": "resume_in_progress",
                }
            }),
            409,
        )
    except ValueError as e:
        if idem_key:
            v1_idempotency.release(idem_key)
        logger.error(
            f"/v1/chat/completions error: {e} - {traceback.format_exc()}",
            extra={"error": str(e)},
        )
        return make_response(
            jsonify({"error": {"message": "Failed to process request", "type": "invalid_request"}}),
            400,
        )
    except Exception as e:
        if idem_key:
            v1_idempotency.release(idem_key)
        logger.error(
            f"/v1/chat/completions error: {e} - {traceback.format_exc()}",
            extra={"error": str(e)},
        )
        return make_response(
            jsonify({"error": {"message": "Internal server error", "type": "server_error"}}),
            500,
        )


def _stream_response(
    helper: _V1AnswerHelper,
    question: str,
    agent: Any,
    processor: StreamProcessor,
    model_name: str,
    continuation: Optional[Dict],
    should_persist: bool,
    visibility: str,
    strip_reasoning_leak: bool = False,
    include_usage: bool = False,
    client_session: Optional[V1Session] = None,
    finalize_stateless_tool_pause: bool = False,
) -> Generator[str, None, None]:
    """Generate translated SSE chunks for streaming response."""
    completion_id = f"chatcmpl-{int(time.time())}"

    internal_stream = helper.complete_stream(
        question=question,
        agent=agent,
        conversation_id=processor.conversation_id,
        user_api_key=processor.agent_config.get("user_api_key"),
        decoded_token=processor.decoded_token,
        agent_id=processor.agent_id,
        model_id=processor.model_id,
        model_user_id=processor.model_user_id,
        should_persist=should_persist,
        visibility=visibility,
        _continuation=continuation,
        finalize_tool_pause_as_complete=finalize_stateless_tool_pause,
    )

    translation_state = StreamTranslationState()

    for line in internal_stream:
        if not line.strip():
            continue
        # ``complete_stream`` prefixes each frame with ``id: <seq>\n``
        # before the ``data:`` line. Extract just the data line so JSON
        # decode doesn't choke on the SSE framing.
        event_str = ""
        for raw in line.split("\n"):
            if raw.startswith("data:"):
                event_str = raw[len("data:") :].lstrip()
                break
        if not event_str:
            continue
        try:
            event_data = json.loads(event_str)
        except (json.JSONDecodeError, TypeError):
            continue

        # Skip the informational ``message_id`` event — it has no v1 /
        # OpenAI-compatible analog.
        if event_data.get("type") == "message_id":
            continue

        # Update completion_id when we get the conversation id
        if event_data.get("type") == "id":
            conv_id = event_data.get("id", "")
            if conv_id and conv_id != "None":
                completion_id = f"chatcmpl-{conv_id}"
                save_conversation(client_session, conv_id)

        # Translate to standard format
        if event_data.get("type") == "end":
            event_data["finish_reason"] = _response_finish_reason(agent)
        if event_data.get("type") == "end" and include_usage:
            yield make_usage_chunk(completion_id, model_name, _response_usage(agent))
        translated = translate_stream_event(
            event_data,
            completion_id,
            model_name,
            strip_reasoning_leak,
            translation_state,
        )
        for chunk in translated:
            yield chunk


def _non_stream_response(
    helper: _V1AnswerHelper,
    question: str,
    agent: Any,
    processor: StreamProcessor,
    model_name: str,
    continuation: Optional[Dict],
    should_persist: bool,
    visibility: str,
    strip_reasoning_leak: bool = False,
    client_session: Optional[V1Session] = None,
    finalize_stateless_tool_pause: bool = False,
) -> Response:
    """Collect full response and return as single JSON."""
    stream = helper.complete_stream(
        question=question,
        agent=agent,
        conversation_id=processor.conversation_id,
        user_api_key=processor.agent_config.get("user_api_key"),
        decoded_token=processor.decoded_token,
        agent_id=processor.agent_id,
        model_id=processor.model_id,
        model_user_id=processor.model_user_id,
        should_persist=should_persist,
        visibility=visibility,
        _continuation=continuation,
        finalize_tool_pause_as_complete=finalize_stateless_tool_pause,
    )

    result = helper.process_response_stream(stream)

    if result["error"]:
        return make_response(
            jsonify({"error": {"message": result["error"], "type": "server_error"}}),
            500,
        )

    extra = result.get("extra")
    pending = extra.get("pending_tool_calls") if isinstance(extra, dict) else None
    save_conversation(client_session, result.get("conversation_id"))

    response = translate_response(
        conversation_id=result["conversation_id"],
        answer=result["answer"] or "",
        sources=result["sources"],
        tool_calls=result["tool_calls"],
        thought=result["thought"] or "",
        model_name=model_name,
        pending_tool_calls=pending,
        strip_reasoning_leak=strip_reasoning_leak,
        usage=_response_usage(agent),
        finish_reason_override=_response_finish_reason(agent),
    )
    return make_response(jsonify(response), 200)


@v1_bp.route("/models", methods=["GET"])
def list_models():
    """Handle GET /v1/models — return agents as models."""
    api_key = _extract_bearer_token()
    if not api_key:
        return make_response(
            jsonify({"error": {"message": "Missing Authorization header", "type": "auth_error"}}),
            401,
        )

    try:
        with db_readonly() as conn:
            agents_repo = AgentsRepository(conn)
            agent = agents_repo.find_by_key(api_key)
            if not agent:
                return make_response(
                    jsonify({"error": {"message": "Invalid API key", "type": "auth_error"}}),
                    401,
                )

        # Repository rows now go through ``coerce_pg_native`` at SELECT
        # time, so timestamps arrive as ISO 8601 strings. Parse before
        # taking ``.timestamp()``; fall back to ``time.time()`` only when
        # the value is genuinely missing or unparseable.
        created = agent.get("created_at") or agent.get("createdAt")
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
            except (ValueError, TypeError):
                created = None
        created_ts = (
            int(created.timestamp()) if hasattr(created, "timestamp")
            else int(time.time())
        )
        model_id = str(agent.get("id") or agent.get("_id") or "")
        model = {
            "id": model_id,
            "object": "model",
            "created": created_ts,
            "owned_by": "docsgpt",
            "name": agent.get("name", ""),
            "description": agent.get("description", ""),
        }

        return make_response(
            jsonify({"object": "list", "data": [model]}),
            200,
        )
    except Exception as e:
        logger.error(f"/v1/models error: {e}", exc_info=True)
        return make_response(
            jsonify({"error": {"message": "Internal server error", "type": "server_error"}}),
            500,
        )
