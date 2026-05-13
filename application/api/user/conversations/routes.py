"""Conversation management routes."""

import datetime

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import text as sql_text

from application.api import api
from application.storage.db.base_repository import looks_like_uuid, row_to_dict
from application.storage.db.repositories.attachments import AttachmentsRepository
from application.storage.db.repositories.conversations import ConversationsRepository
from application.storage.db.session import db_readonly, db_session
from application.utils import check_required_fields

conversations_ns = Namespace(
    "conversations", description="Conversation management operations", path="/api"
)


@conversations_ns.route("/delete_conversation")
class DeleteConversation(Resource):
    @api.doc(
        description="Deletes a conversation by ID",
        params={"id": "The ID of the conversation to delete"},
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        user_id = decoded_token["sub"]
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(conversation_id, user_id)
                if conv is not None:
                    repo.delete(str(conv["id"]), user_id)
        except Exception as err:
            current_app.logger.error(
                f"Error deleting conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@conversations_ns.route("/delete_all_conversations")
class DeleteAllConversations(Resource):
    @api.doc(
        description="Deletes all conversations for a specific user",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        try:
            with db_session() as conn:
                ConversationsRepository(conn).delete_all_for_user(user_id)
        except Exception as err:
            current_app.logger.error(
                f"Error deleting all conversations: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@conversations_ns.route("/get_conversations")
class GetConversations(Resource):
    @api.doc(
        description="Retrieve a list of the latest 30 conversations (excluding API key conversations)",
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                conversations = ConversationsRepository(conn).list_for_user(
                    user_id, limit=30
                )
            list_conversations = [
                {
                    "id": str(conversation["id"]),
                    "name": conversation["name"],
                    "agent_id": (
                        str(conversation["agent_id"])
                        if conversation.get("agent_id")
                        else None
                    ),
                    "is_shared_usage": conversation.get("is_shared_usage", False),
                    "shared_token": conversation.get("shared_token", None),
                }
                for conversation in conversations
            ]
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving conversations: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_conversations), 200)


@conversations_ns.route("/search_conversations")
class SearchConversations(Resource):
    @staticmethod
    def _build_match_snippet(text_value: str, query: str, radius: int = 60) -> str:
        if not text_value:
            return ""
        idx = text_value.lower().find(query.lower())
        if idx == -1:
            snippet = text_value[: radius * 2]
            return snippet + ("…" if len(text_value) > len(snippet) else "")
        start = max(0, idx - radius)
        end = min(len(text_value), idx + len(query) + radius)
        snippet = text_value[start:end]
        if start > 0:
            snippet = "…" + snippet
        if end < len(text_value):
            snippet = snippet + "…"
        return snippet

    @api.doc(
        description=(
            "Search the authenticated user's conversations by name or "
            "message content (case-insensitive substring match). Mirrors "
            "the visibility filter and response shape of /get_conversations, "
            "and additionally returns ``match_field`` (``name``, ``prompt`` "
            "or ``response``) and ``match_snippet`` (a short excerpt of the "
            "matched text centered on the query) for each result."
        ),
        params={
            "q": "Search term (required)",
            "limit": "Maximum number of results to return (default 30, max 100)",
        },
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        query = (request.args.get("q") or "").strip()
        if not query:
            return make_response(
                jsonify({"success": False, "message": "q is required"}), 400
            )
        try:
            limit = int(request.args.get("limit", 30))
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 100))
        user_id = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                conversations = ConversationsRepository(conn).search_for_user(
                    user_id, query, limit=limit
                )
            list_conversations = [
                {
                    "id": str(conversation["id"]),
                    "name": conversation["name"],
                    "agent_id": (
                        str(conversation["agent_id"])
                        if conversation.get("agent_id")
                        else None
                    ),
                    "is_shared_usage": conversation.get("is_shared_usage", False),
                    "shared_token": conversation.get("shared_token", None),
                    "match_field": conversation.get("match_field"),
                    "match_snippet": self._build_match_snippet(
                        conversation.get("match_text") or "", query
                    ),
                }
                for conversation in conversations
            ]
        except Exception as err:
            current_app.logger.error(
                f"Error searching conversations: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_conversations), 200)


@conversations_ns.route("/get_single_conversation")
class GetSingleConversation(Resource):
    @api.doc(
        description="Retrieve a single conversation by ID",
        params={"id": "The conversation ID"},
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        conversation_id = request.args.get("id")
        if not conversation_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        user_id = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                repo = ConversationsRepository(conn)
                conversation = repo.get_any(conversation_id, user_id)
                if not conversation:
                    return make_response(jsonify({"status": "not found"}), 404)
                conv_pg_id = str(conversation["id"])
                messages = repo.get_messages(conv_pg_id)

                # Resolve attachment details (id, fileName) for each message.
                attachments_repo = AttachmentsRepository(conn)
                queries = []
                for msg in messages:
                    metadata = msg.get("metadata") or {}
                    query = {
                        "prompt": msg.get("prompt"),
                        "response": msg.get("response"),
                        "thought": msg.get("thought"),
                        "sources": msg.get("sources") or [],
                        "tool_calls": msg.get("tool_calls") or [],
                        "timestamp": msg.get("timestamp"),
                        "model_id": msg.get("model_id"),
                        # Lets the client distinguish placeholder rows from
                        # finalised answers and tail-poll in-flight ones.
                        "message_id": str(msg["id"]) if msg.get("id") else None,
                        "status": msg.get("status"),
                        "request_id": msg.get("request_id"),
                        "last_heartbeat_at": metadata.get("last_heartbeat_at"),
                    }
                    if metadata:
                        query["metadata"] = metadata
                    # Feedback on conversation_messages is a JSONB blob with
                    # shape {"text": <str>, "timestamp": <iso>}. The legacy
                    # frontend consumed a flat scalar feedback string, so
                    # unwrap the ``text`` field for compat.
                    feedback = msg.get("feedback")
                    if feedback is not None:
                        if isinstance(feedback, dict):
                            query["feedback"] = feedback.get("text")
                            if feedback.get("timestamp"):
                                query["feedback_timestamp"] = feedback["timestamp"]
                        else:
                            query["feedback"] = feedback
                    attachments = msg.get("attachments") or []
                    if attachments:
                        attachment_details = []
                        for attachment_id in attachments:
                            try:
                                att = attachments_repo.get_any(
                                    str(attachment_id), user_id
                                )
                                if att:
                                    attachment_details.append(
                                        {
                                            "id": str(att["id"]),
                                            "fileName": att.get(
                                                "filename", "Unknown file"
                                            ),
                                        }
                                    )
                            except Exception as e:
                                current_app.logger.error(
                                    f"Error retrieving attachment {attachment_id}: {e}",
                                    exc_info=True,
                                )
                        query["attachments"] = attachment_details
                    queries.append(query)
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        data = {
            "queries": queries,
            "agent_id": (
                str(conversation["agent_id"]) if conversation.get("agent_id") else None
            ),
            "is_shared_usage": conversation.get("is_shared_usage", False),
            "shared_token": conversation.get("shared_token", None),
        }
        return make_response(jsonify(data), 200)


@conversations_ns.route("/update_conversation_name")
class UpdateConversationName(Resource):
    @api.expect(
        api.model(
            "UpdateConversationModel",
            {
                "id": fields.String(required=True, description="Conversation ID"),
                "name": fields.String(
                    required=True, description="New name of the conversation"
                ),
            },
        )
    )
    @api.doc(
        description="Updates the name of a conversation",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["id", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        user_id = decoded_token.get("sub")
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(data["id"], user_id)
                if conv is not None:
                    repo.rename(str(conv["id"]), user_id, data["name"])
        except Exception as err:
            current_app.logger.error(
                f"Error updating conversation name: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@conversations_ns.route("/feedback")
class SubmitFeedback(Resource):
    @api.expect(
        api.model(
            "FeedbackModel",
            {
                "question": fields.String(
                    required=False, description="The user question"
                ),
                "answer": fields.String(required=False, description="The AI answer"),
                "feedback": fields.String(required=True, description="User feedback"),
                "question_index": fields.Integer(
                    required=True,
                    description="The question number in that particular conversation",
                ),
                "conversation_id": fields.String(
                    required=True, description="id of the particular conversation"
                ),
                "api_key": fields.String(description="Optional API key"),
            },
        )
    )
    @api.doc(
        description="Submit feedback for a conversation",
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["feedback", "conversation_id", "question_index"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        user_id = decoded_token.get("sub")
        feedback_value = data["feedback"]
        question_index = int(data["question_index"])
        # Normalize string feedback to lowercase so analytics queries
        # (which match 'like'/'dislike') count rows correctly. Tolerate
        # legacy uppercase clients on ingest. Non-string values pass through.
        if isinstance(feedback_value, str):
            feedback_value = feedback_value.lower()
        feedback_payload = (
            None
            if feedback_value is None
            else {
                "text": feedback_value,
                "timestamp": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(),
            }
        )
        try:
            with db_session() as conn:
                repo = ConversationsRepository(conn)
                conv = repo.get_any(data["conversation_id"], user_id)
                if conv is None:
                    return make_response(
                        jsonify({"success": False, "message": "Not found"}), 404
                    )
                repo.set_feedback(str(conv["id"]), question_index, feedback_payload)
        except Exception as err:
            current_app.logger.error(f"Error submitting feedback: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@conversations_ns.route("/messages/<string:message_id>/tail")
class GetMessageTail(Resource):
    @api.doc(
        description=(
            "Current state of one conversation_messages row, scoped to the "
            "authenticated user. Used to reconnect to an in-flight stream "
            "after a refresh."
        ),
        params={"message_id": "Message UUID"},
    )
    def get(self, message_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        if not looks_like_uuid(message_id):
            return make_response(
                jsonify({"success": False, "message": "Invalid message id"}), 400
            )
        user_id = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                # Owner-or-shared, matching ``ConversationsRepository.get``.
                row = conn.execute(
                    sql_text(
                        "SELECT m.* FROM conversation_messages m "
                        "JOIN conversations c ON c.id = m.conversation_id "
                        "WHERE m.id = CAST(:mid AS uuid) "
                        "AND (c.user_id = :uid OR :uid = ANY(c.shared_with))"
                    ),
                    {"mid": message_id, "uid": user_id},
                ).fetchone()
                if row is None:
                    return make_response(jsonify({"status": "not found"}), 404)
                msg = row_to_dict(row)
        except Exception as err:
            current_app.logger.error(
                f"Error tailing message {message_id}: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        metadata = msg.get("message_metadata") or {}
        return make_response(
            jsonify(
                {
                    "message_id": str(msg["id"]),
                    "status": msg.get("status"),
                    "response": msg.get("response"),
                    "thought": msg.get("thought"),
                    "sources": msg.get("sources") or [],
                    "tool_calls": msg.get("tool_calls") or [],
                    "request_id": msg.get("request_id"),
                    "last_heartbeat_at": metadata.get("last_heartbeat_at"),
                    "error": metadata.get("error"),
                }
            ),
            200,
        )
