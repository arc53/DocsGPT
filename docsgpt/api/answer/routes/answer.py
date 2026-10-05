import logging
import traceback

from flask import make_response, request
from flask_restx import fields, Resource

from docsgpt.agents.context_overflow import ContextOverflowError
from docsgpt.api import api

from docsgpt.api.answer.routes.base import answer_ns, BaseAnswerResource

from docsgpt.api.answer.services.continuation_service import (
    RESUME_IN_PROGRESS_MESSAGE,
    ResumeInProgressError,
)
from docsgpt.api.answer.services.persistence_policy import resolve_persistence
from docsgpt.api.answer.services.stream_processor import (
    StreamProcessor,
    flush_trace_after_request,
)
from docsgpt.error import bounded_error_text, user_facing_error

logger = logging.getLogger(__name__)


@answer_ns.route("/api/answer")
class AnswerResource(Resource, BaseAnswerResource):
    def __init__(self, *args, **kwargs):
        Resource.__init__(self, *args, **kwargs)
        BaseAnswerResource.__init__(self)

    answer_model = answer_ns.model(
        "AnswerModel",
        {
            "question": fields.String(
                required=True, description="Question to be asked"
            ),
            "history": fields.List(
                fields.String,
                required=False,
                description="Conversation history (only for new conversations)",
            ),
            "conversation_id": fields.String(
                required=False,
                description="Existing conversation ID (loads history)",
            ),
            "prompt_id": fields.String(
                required=False, default="default", description="Prompt ID"
            ),
            "chunks": fields.Integer(
                required=False, default=6, description="Number of chunks"
            ),
            "retriever": fields.String(required=False, description="Retriever type"),
            "api_key": fields.String(required=False, description="API key"),
            "agent_id": fields.String(required=False, description="Agent ID"),
            "active_docs": fields.String(
                required=False, description="Active documents"
            ),
            "isNoneDoc": fields.Boolean(
                required=False, description="Flag indicating if no document is used"
            ),
            "save_conversation": fields.Boolean(
                required=False,
                description=(
                    "Deprecated, no effect: conversations always persist. "
                    "Use `visibility` to control sidebar listing."
                ),
            ),
            "visibility": fields.String(
                required=False,
                default="hidden",
                description=(
                    "'listed' shows the conversation in the owner's sidebar; "
                    "any other value (or omitting it) persists it hidden."
                ),
            ),
            "model_id": fields.String(
                required=False,
                description="Model ID to use for this request",
            ),
            "passthrough": fields.Raw(
                required=False,
                description="Dynamic parameters to inject into prompt template",
            ),
        },
    )

    @api.expect(answer_model)
    @api.doc(description="Provide a response based on the question and retriever")
    def post(self):
        data = request.get_json()
        if error := self.validate_request(data):
            return error
        decoded_token = getattr(request, "decoded_token", None)
        processor = StreamProcessor(data, decoded_token, trace_source="answer")
        # ``complete_stream`` is consumed below and writes the trace itself;
        # this covers requests refused before it runs.
        flush_trace_after_request(processor)
        try:
            # ---- Continuation mode ----
            if data.get("tool_actions"):
                (
                    agent,
                    messages,
                    tools_dict,
                    pending_tool_calls,
                    tool_actions,
                    reasoning_content,
                ) = processor.resume_from_tool_actions(
                    data["tool_actions"], data["conversation_id"]
                )
                if not processor.decoded_token:
                    return make_response({"error": "Unauthorized"}, 401)
                if error := self.check_usage_on_resume(
                    processor, data["conversation_id"]
                ):
                    return error
                stream = self.complete_stream(
                    question="",
                    agent=agent,
                    conversation_id=processor.conversation_id,
                    user_api_key=processor.agent_config.get("user_api_key"),
                    decoded_token=processor.decoded_token,
                    agent_id=processor.agent_id,
                    model_id=processor.model_id,
                    trace=processor.trace,
                    _continuation={
                        "messages": messages,
                        "tools_dict": tools_dict,
                        "pending_tool_calls": pending_tool_calls,
                        "tool_actions": tool_actions,
                        "reserved_message_id": processor.reserved_message_id,
                        "request_id": processor.request_id,
                        "reasoning_content": reasoning_content,
                    },
                )
            else:
                # ---- Normal mode ----
                agent = processor.build_agent(data.get("question", ""))
                if not processor.decoded_token:
                    return make_response({"error": "Unauthorized"}, 401)

                if error := self.check_usage(
                    processor.agent_config,
                    processor.decoded_token,
                    agent_id=processor.agent_id,
                ):
                    return error

                should_persist, visibility = resolve_persistence(
                    visibility_flag=data.get("visibility"),
                    persist_flag=data.get("persist"),
                )
                stream = self.complete_stream(
                    question=data["question"],
                    agent=agent,
                    conversation_id=processor.conversation_id,
                    user_api_key=processor.agent_config.get("user_api_key"),
                    decoded_token=processor.decoded_token,
                    isNoneDoc=data.get("isNoneDoc"),
                    index=None,
                    should_persist=should_persist,
                    visibility=visibility,
                    agent_id=processor.agent_id,
                    is_shared_usage=processor.is_shared_usage,
                    shared_token=processor.shared_token,
                    model_id=processor.model_id,
                    request_id=processor.request_id,
                    trace=processor.trace,
                )

            stream_result = self.process_response_stream(stream)

            if stream_result["error"]:
                body = {"error": stream_result["error"]}
                if stream_result.get("error_code"):
                    body["code"] = stream_result["error_code"]
                if stream_result.get("error_params"):
                    body["params"] = stream_result["error_params"]
                return make_response(body, 400)

            result = {
                "conversation_id": stream_result["conversation_id"],
                "answer": stream_result["answer"],
                "sources": stream_result["sources"],
                "tool_calls": stream_result["tool_calls"],
                "thought": stream_result["thought"],
            }

            extra_info = stream_result.get("extra")
            if extra_info:
                result.update(extra_info)
        except ContextOverflowError as e:
            # A turn too big for the window, found before any provider call.
            logger.info("/api/answer - turn does not fit the context window: %s", bounded_error_text(e))
            public = user_facing_error(e)
            body = {"error": public.message, "code": public.code}
            if public.params:
                body["params"] = public.params
            return make_response(body, 400)
        except ResumeInProgressError as e:
            # Another request already owns this conversation's continuation
            # claim. Same contract as ``/stream`` and ``/v1/chat/completions``:
            # an expected concurrency outcome the caller can retry, not a
            # server fault, so it must not land in the 500 handler below and
            # fill the ERROR channel with tracebacks.
            logger.warning(
                "/api/answer - resume already in progress for conversation %s",
                data.get("conversation_id"),
                extra={"error": str(e)},
            )
            return make_response(
                {"error": RESUME_IN_PROGRESS_MESSAGE, "code": "resume_in_progress"},
                409,
            )
        except Exception as e:
            logger.error(
                f"/api/answer - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return make_response({"error": "An error occurred processing your request"}, 500)
        return make_response(result, 200)
