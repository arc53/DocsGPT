import logging
import traceback

from flask import request, Response
from flask_restx import fields, Resource

from application.api import api

from application.api.answer.routes.base import answer_ns, BaseAnswerResource

from application.api.answer.services.stream_processor import StreamProcessor
from application.api.answer.services.multimodal_service import (
    normalize_question_payload,
    run_multimodal_completion,
)

logger = logging.getLogger(__name__)


@answer_ns.route("/stream")
class StreamResource(Resource, BaseAnswerResource):
    def __init__(self, *args, **kwargs):
        Resource.__init__(self, *args, **kwargs)
        BaseAnswerResource.__init__(self)

    stream_model = answer_ns.model(
        "StreamModel",
        {
            "question": fields.String(
                required=False, description="Question to be asked"
            ),
            "imageBase64": fields.String(
                required=False,
                description="Optional base64-encoded user image for multimodal requests",
            ),
            "imageMimeType": fields.String(
                required=False,
                description="Optional MIME type for imageBase64 (e.g. image/png)",
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
                required=False, default=2, description="Number of chunks"
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
            "index": fields.Integer(
                required=False, description="Index of the query to update"
            ),
            "save_conversation": fields.Boolean(
                required=False,
                default=True,
                description="Whether to save the conversation",
            ),
            "model_id": fields.String(
                required=False,
                description="Model ID to use for this request",
            ),
            "attachments": fields.List(
                fields.String, required=False, description="List of attachment IDs"
            ),
            "passthrough": fields.Raw(
                required=False,
                description="Dynamic parameters to inject into prompt template",
            ),
        },
    )

    @api.expect(stream_model)
    @api.doc(description="Stream a response based on the question and retriever")
    def post(self):
        data = normalize_question_payload(request.get_json() or {})
        has_image = bool(data.get("image_base64"))

        if not data.get("question") and not has_image:
            return Response(
                self.error_stream_generate("question is required"),
                status=400,
                mimetype="text/event-stream",
            )

        if error := self.validate_request(
            {"question": data.get("question", " ")}, "index" in data
        ):
            return error
        decoded_token = getattr(request, "decoded_token", None)
        processor = StreamProcessor(data, decoded_token)

        try:
            # ---- Continuation mode ----
            if data.get("tool_actions"):
                (
                    agent,
                    messages,
                    tools_dict,
                    pending_tool_calls,
                    tool_actions,
                ) = processor.resume_from_tool_actions(
                    data["tool_actions"], data["conversation_id"]
                )
                if not processor.decoded_token:
                    return Response(
                        self.error_stream_generate("Unauthorized"),
                        status=401,
                        mimetype="text/event-stream",
                    )
                if error := self.check_usage(processor.agent_config):
                    return error
                return Response(
                    self.complete_stream(
                        question="",
                        agent=agent,
                        conversation_id=processor.conversation_id,
                        user_api_key=processor.agent_config.get("user_api_key"),
                        decoded_token=processor.decoded_token,
                        agent_id=processor.agent_id,
                        model_id=processor.model_id,
                        _continuation={
                            "messages": messages,
                            "tools_dict": tools_dict,
                            "pending_tool_calls": pending_tool_calls,
                            "tool_actions": tool_actions,
                        },
                    ),
                    mimetype="text/event-stream",
                )

            # ---- Normal mode ----
            agent = processor.build_agent(data["question"])
            if not processor.decoded_token:
                return Response(
                    self.error_stream_generate("Unauthorized"),
                    status=401,
                    mimetype="text/event-stream",
                )

            docs_together, docs_list = processor.pre_fetch_docs(data.get("question", ""))
            tools_data = processor.pre_fetch_tools()

            if error := self.check_usage(processor.agent_config):
                return error

            if has_image:
                response_text = run_multimodal_completion(
                    question=data.get("question", ""),
                    image_base64=data["image_base64"],
                    docs_together=docs_together,
                    model_id=data.get("model_id") or processor.model_id,
                    image_mime_type=data.get("image_mime_type"),
                )

                def multimodal_stream():
                    import json

                    yield f"data: {json.dumps({'type': 'answer', 'answer': response_text})}\n\n"
                    yield "data: {\"type\": \"end\"}\n\n"

                return Response(multimodal_stream(), mimetype="text/event-stream")

            agent = processor.create_agent(
                docs_together=docs_together, docs=docs_list, tools_data=tools_data
            )

            if error := self.check_usage(processor.agent_config):
                return error
            return Response(
                self.complete_stream(
                    question=data["question"],
                    agent=agent,
                    conversation_id=processor.conversation_id,
                    user_api_key=processor.agent_config.get("user_api_key"),
                    decoded_token=processor.decoded_token,
                    isNoneDoc=data.get("isNoneDoc"),
                    index=data.get("index"),
                    should_save_conversation=data.get("save_conversation", True),
                    attachment_ids=data.get("attachments", []),
                    agent_id=processor.agent_id,
                    is_shared_usage=processor.is_shared_usage,
                    shared_token=processor.shared_token,
                    model_id=processor.model_id,
                ),
                mimetype="text/event-stream",
            )
        except ValueError as e:
            message = "Malformed request body"
            logger.error(
                f"/stream - error: {message} - specific error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return Response(
                self.error_stream_generate(message),
                status=400,
                mimetype="text/event-stream",
            )
        except Exception as e:
            logger.error(
                f"/stream - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return Response(
                self.error_stream_generate("Unknown error occurred"),
                status=400,
                mimetype="text/event-stream",
            )
