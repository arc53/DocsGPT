import logging
import traceback

from flask import make_response, request
from flask_restx import fields, Resource
from application.api import api

from application.api.answer.routes.base import answer_ns, BaseAnswerResource
from application.api.answer.services.stream_processor import StreamProcessor
from application.api.answer.services.multimodal_service import (
    normalize_question_payload,
    run_multimodal_completion,
)

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
            "save_conversation": fields.Boolean(
                required=False,
                default=True,
                description="Whether to save the conversation",
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
        data = request.get_json() or {}
        data = normalize_question_payload(data)
        has_image = bool(data.get("image_base64"))
        if not data.get("question") and not has_image:
            return make_response({"error": "question is required"}, 400)
        if error := self.validate_request({"question": data.get("question", " ")}):
            return error
        decoded_token = getattr(request, "decoded_token", None)
        processor = StreamProcessor(data, decoded_token)
        try:
            processor.initialize()
            if not processor.decoded_token:
                return make_response({"error": "Unauthorized"}, 401)

            docs_together, docs_list = processor.pre_fetch_docs(
                data.get("question", "")
            )
            tools_data = processor.pre_fetch_tools()

            if error := self.check_usage(processor.agent_config):
                return error

            # Scenario 1: direct user upload for multimodal vision requests.
            image_base64 = data.get("image_base64")
            if image_base64:
                response = run_multimodal_completion(
                    question=data["question"],
                    image_base64=image_base64,
                    docs_together=docs_together,
                    model_id=data.get("model_id") or "gpt-4o",
                    image_mime_type=data.get("image_mime_type"),
                )
                return make_response(
                    {
                        "conversation_id": processor.conversation_id,
                        "answer": response,
                        "sources": docs_list or [],
                        "tool_calls": [],
                        "thought": "",
                    },
                    200,
                )

            agent = processor.create_agent(
                docs_together=docs_together,
                docs=docs_list,
                tools_data=tools_data,
            )

            stream = self.complete_stream(
                question=data["question"],
                agent=agent,
                conversation_id=processor.conversation_id,
                user_api_key=processor.agent_config.get("user_api_key"),
                decoded_token=processor.decoded_token,
                isNoneDoc=data.get("isNoneDoc"),
                index=None,
                should_save_conversation=data.get("save_conversation", True),
                agent_id=processor.agent_id,
                is_shared_usage=processor.is_shared_usage,
                shared_token=processor.shared_token,
                model_id=processor.model_id,
            )
            stream_result = self.process_response_stream(stream)

            if len(stream_result) == 7:
                (
                    conversation_id,
                    response,
                    sources,
                    tool_calls,
                    thought,
                    error,
                    structured_info,
                ) = stream_result
            else:
                conversation_id, response, sources, tool_calls, thought, error = (
                    stream_result
                )
                structured_info = None

            if error:
                return make_response({"error": error}, 400)
            result = {
                "conversation_id": conversation_id,
                "answer": response,
                "sources": sources,
                "tool_calls": tool_calls,
                "thought": thought,
            }

            if structured_info:
                result.update(structured_info)
        except Exception as e:
            logger.error(
                f"/api/answer - error: {str(e)} - traceback: {traceback.format_exc()}",
                extra={"error": str(e), "traceback": traceback.format_exc()},
            )
            return make_response({"error": "An error occurred processing your request"}, 500)
        return make_response(result, 200)
