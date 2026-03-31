"""Standard chat completions API routes.

Exposes ``/v1/chat/completions`` and ``/v1/models`` endpoints that
follow the widely-adopted chat completions protocol so external tools
(opencode, continue, etc.) can connect to DocsGPT agents.
"""

import json
import logging
import time
import traceback
from typing import Any, Dict, Generator, Optional

from flask import Blueprint, jsonify, make_response, request, Response

from application.api.answer.routes.base import BaseAnswerResource
from application.api.answer.services.stream_processor import StreamProcessor
from application.api.v1.translator import (
    translate_request,
    translate_response,
    translate_stream_event,
)
from application.core.mongo_db import MongoDB
from application.core.settings import settings

logger = logging.getLogger(__name__)

v1_bp = Blueprint("v1", __name__, url_prefix="/v1")


def _extract_bearer_token() -> Optional[str]:
    """Extract API key from Authorization: Bearer header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _get_model_name(api_key: str) -> str:
    """Look up agent name for display as model name."""
    try:
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        agent = db["agents"].find_one({"key": api_key})
        if agent:
            return agent.get("name", api_key)
    except Exception:
        pass
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
    model_name = _get_model_name(api_key)

    try:
        internal_data = translate_request(data, api_key)
    except Exception as e:
        logger.error(f"/v1/chat/completions translate error: {e}", exc_info=True)
        return make_response(
            jsonify({"error": {"message": "Failed to process request", "type": "invalid_request"}}),
            400,
        )

    # Use the api_key as decoded token for agent auth
    decoded_token = {"sub": "api_key_user"}

    try:
        processor = StreamProcessor(internal_data, decoded_token)

        if internal_data.get("tool_actions"):
            # Continuation mode
            conversation_id = internal_data.get("conversation_id")
            if not conversation_id:
                return make_response(
                    jsonify({"error": {"message": "conversation_id required for tool continuation", "type": "invalid_request"}}),
                    400,
                )
            (
                agent,
                messages,
                tools_dict,
                pending_tool_calls,
                tool_actions,
            ) = processor.resume_from_tool_actions(
                internal_data["tool_actions"], conversation_id
            )
            continuation = {
                "messages": messages,
                "tools_dict": tools_dict,
                "pending_tool_calls": pending_tool_calls,
                "tool_actions": tool_actions,
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

        if is_stream:
            return Response(
                _stream_response(
                    helper, question, agent, processor, model_name, continuation
                ),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            return _non_stream_response(
                helper, question, agent, processor, model_name, continuation
            )

    except ValueError as e:
        logger.error(
            f"/v1/chat/completions error: {e} - {traceback.format_exc()}",
            extra={"error": str(e)},
        )
        return make_response(
            jsonify({"error": {"message": str(e), "type": "invalid_request"}}),
            400,
        )
    except Exception as e:
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
        _continuation=continuation,
    )

    for line in internal_stream:
        if not line.strip():
            continue
        # Parse the internal SSE event
        event_str = line.replace("data: ", "").strip()
        try:
            event_data = json.loads(event_str)
        except (json.JSONDecodeError, TypeError):
            continue

        # Update completion_id when we get the conversation id
        if event_data.get("type") == "id":
            conv_id = event_data.get("id", "")
            if conv_id:
                completion_id = f"chatcmpl-{conv_id}"

        # Translate to standard format
        translated = translate_stream_event(event_data, completion_id, model_name)
        for chunk in translated:
            yield chunk


def _non_stream_response(
    helper: _V1AnswerHelper,
    question: str,
    agent: Any,
    processor: StreamProcessor,
    model_name: str,
    continuation: Optional[Dict],
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
        _continuation=continuation,
    )

    result = helper.process_response_stream(stream)

    if len(result) == 7:
        conversation_id, answer, sources, tool_calls, thought, error, extra = result
    else:
        conversation_id, answer, sources, tool_calls, thought, error = result
        extra = None

    if error:
        return make_response(
            jsonify({"error": {"message": error, "type": "server_error"}}),
            500,
        )

    pending = extra.get("pending_tool_calls") if isinstance(extra, dict) else None

    response = translate_response(
        conversation_id=conversation_id,
        answer=answer or "",
        sources=sources,
        tool_calls=tool_calls,
        thought=thought or "",
        model_name=model_name,
        pending_tool_calls=pending,
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
        mongo = MongoDB.get_client()
        db = mongo[settings.MONGO_DB_NAME]
        agents_collection = db["agents"]

        # Find the agent for this api_key
        agent = agents_collection.find_one({"key": api_key})
        if not agent:
            return make_response(
                jsonify({"error": {"message": "Invalid API key", "type": "auth_error"}}),
                401,
            )

        user = agent.get("user")

        # Return all agents belonging to this user
        user_agents = list(agents_collection.find({"user": user}))

        models = []
        for ag in user_agents:
            created = ag.get("createdAt")
            created_ts = int(created.timestamp()) if created else int(time.time())
            models.append({
                "id": str(ag.get("key", "")),
                "object": "model",
                "created": created_ts,
                "owned_by": "docsgpt",
                "name": ag.get("name", ""),
                "description": ag.get("description", ""),
            })

        return make_response(
            jsonify({"object": "list", "data": models}),
            200,
        )
    except Exception as e:
        logger.error(f"/v1/models error: {e}", exc_info=True)
        return make_response(
            jsonify({"error": {"message": "Internal server error", "type": "server_error"}}),
            500,
        )
