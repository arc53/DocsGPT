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
from application.api.answer.services.stream_processor import StreamProcessor
from application.api.v1 import idempotency as v1_idempotency
from application.api.v1.translator import (
    translate_request,
    translate_response,
    translate_stream_event,
)
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.session import db_readonly

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

    try:
        processor = StreamProcessor(internal_data, decoded_token)

        if internal_data.get("tool_actions"):
            # Continuation mode — coherent Option B: the v1 tool round-trip is
            # fully stateless. The pause finalized the prior turn's row as
            # ``complete`` and wrote NO ``pending_tool_state`` (see
            # ``complete_stream(finalize_tool_pause_as_complete=True)``), so we
            # ALWAYS rebuild the agent + pending calls from the re-POSTed
            # message history — even when the client threads back the
            # ``conversation_id`` it got from the first response.
            #
            # We deliberately do NOT call ``resume_from_tool_actions`` here:
            # its ``load_state`` would find no pending state and raise (→ HTTP
            # 400), since OpenAI clients resume statelessly rather than via a
            # native resume. ``resume_from_tool_actions`` stays in place for
            # the native ``/stream`` + ``/api/answer`` routes, which are
            # unchanged.
            conversation_id = internal_data.get("conversation_id")
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
            # When a conversation_id is carried, target it for persistence so
            # the final answer appends as a NEW terminal turn in that
            # conversation (``save_conversation`` keys off ``conversation_id``)
            # rather than creating an orphan sibling. ``build_continuation_from_messages``
            # leaves the processor's ``conversation_id`` (set from the request
            # in ``__init__``) intact; pin it explicitly for clarity.
            if conversation_id:
                processor.conversation_id = conversation_id
            continuation = {
                "messages": messages,
                "tools_dict": tools_dict,
                "pending_tool_calls": pending_tool_calls,
                "tool_actions": tool_actions,
                "reasoning_content": reasoning_content,
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
        # tool round); the agent owner's sidebar only lists it on explicit
        # ``docsgpt.save_conversation: true``.
        should_persist, visibility = resolve_persistence(
            display_flag=internal_data.get("save_conversation"),
            api_key=internal_data.get("api_key"),
            persist_flag=internal_data.get("persist"),
        )
        # Only strip leaked reasoning from content for structured requests -- the
        # only path where models echo reasoning into content -- so legitimate
        # answers that mention the marker text are never corrupted.
        strip_reasoning_leak = bool(
            internal_data.get("json_schema") or internal_data.get("json_object")
        )

        if is_stream:
            # Idempotency replay is NOT supported for streaming: there is no
            # safe way to re-emit a recorded SSE stream (and the regression /
            # b2b client is non-streaming), so a streaming request never
            # claims a key. This is a known, accepted limitation.
            return Response(
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
        )

        # Cache only successful (2xx) responses; ``finalize`` releases the
        # claim on a non-2xx so a real retry can still succeed (matches OpenAI).
        if idem_key:
            v1_idempotency.finalize(idem_key, response)
        return response

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
        # OpenAI clients resume tool calls statelessly (no slot for our
        # reserved_message_id), so a tool pause must finalize the row as
        # ``complete`` here rather than stranding it for a native resume.
        finalize_tool_pause_as_complete=True,
    )

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

        # Translate to standard format
        translated = translate_stream_event(
            event_data, completion_id, model_name, strip_reasoning_leak
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
        # OpenAI clients resume tool calls statelessly (no slot for our
        # reserved_message_id), so a tool pause must finalize the row as
        # ``complete`` here rather than stranding it for a native resume.
        finalize_tool_pause_as_complete=True,
    )

    result = helper.process_response_stream(stream)

    if result["error"]:
        return make_response(
            jsonify({"error": {"message": result["error"], "type": "server_error"}}),
            500,
        )

    extra = result.get("extra")
    pending = extra.get("pending_tool_calls") if isinstance(extra, dict) else None

    response = translate_response(
        conversation_id=result["conversation_id"],
        answer=result["answer"] or "",
        sources=result["sources"],
        tool_calls=result["tool_calls"],
        thought=result["thought"] or "",
        model_name=model_name,
        pending_tool_calls=pending,
        strip_reasoning_leak=strip_reasoning_leak,
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
