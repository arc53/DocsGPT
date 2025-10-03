"""Conversation management routes."""

import datetime

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import (
    attachments_collection,
    conversations_collection,
    db,
)
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
        try:
            conversations_collection.delete_one(
                {"_id": ObjectId(conversation_id), "user": decoded_token["sub"]}
            )
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
            conversations_collection.delete_many({"user": user_id})
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
        try:
            conversations = (
                conversations_collection.find(
                    {
                        "$or": [
                            {"api_key": {"$exists": False}},
                            {"agent_id": {"$exists": True}},
                        ],
                        "user": decoded_token.get("sub"),
                    }
                )
                .sort("date", -1)
                .limit(30)
            )

            list_conversations = [
                {
                    "id": str(conversation["_id"]),
                    "name": conversation["name"],
                    "agent_id": conversation.get("agent_id", None),
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
        try:
            conversation = conversations_collection.find_one(
                {"_id": ObjectId(conversation_id), "user": decoded_token.get("sub")}
            )
            if not conversation:
                return make_response(jsonify({"status": "not found"}), 404)
            # Process queries to include attachment names

            queries = conversation["queries"]
            for query in queries:
                if "attachments" in query and query["attachments"]:
                    attachment_details = []
                    for attachment_id in query["attachments"]:
                        try:
                            attachment = attachments_collection.find_one(
                                {"_id": ObjectId(attachment_id)}
                            )
                            if attachment:
                                attachment_details.append(
                                    {
                                        "id": str(attachment["_id"]),
                                        "fileName": attachment.get(
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
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving conversation: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        data = {
            "queries": queries,
            "agent_id": conversation.get("agent_id"),
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
        try:
            conversations_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": decoded_token.get("sub")},
                {"$set": {"name": data["name"]}},
            )
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
        try:
            if data["feedback"] is None:
                # Remove feedback and feedback_timestamp if feedback is null

                conversations_collection.update_one(
                    {
                        "_id": ObjectId(data["conversation_id"]),
                        "user": decoded_token.get("sub"),
                        f"queries.{data['question_index']}": {"$exists": True},
                    },
                    {
                        "$unset": {
                            f"queries.{data['question_index']}.feedback": "",
                            f"queries.{data['question_index']}.feedback_timestamp": "",
                        }
                    },
                )
            else:
                # Set feedback and feedback_timestamp if feedback has a value

                conversations_collection.update_one(
                    {
                        "_id": ObjectId(data["conversation_id"]),
                        "user": decoded_token.get("sub"),
                        f"queries.{data['question_index']}": {"$exists": True},
                    },
                    {
                        "$set": {
                            f"queries.{data['question_index']}.feedback": data[
                                "feedback"
                            ],
                            f"queries.{data['question_index']}.feedback_timestamp": datetime.datetime.now(
                                datetime.timezone.utc
                            ),
                        }
                    },
                )
        except Exception as err:
            current_app.logger.error(f"Error submitting feedback: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)
