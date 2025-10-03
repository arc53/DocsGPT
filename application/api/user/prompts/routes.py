"""Prompt management routes."""

import os

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.api import api
from application.api.user.base import current_dir, prompts_collection
from application.utils import check_required_fields

prompts_ns = Namespace(
    "prompts", description="Prompt management operations", path="/api"
)


@prompts_ns.route("/create_prompt")
class CreatePrompt(Resource):
    create_prompt_model = api.model(
        "CreatePromptModel",
        {
            "content": fields.String(
                required=True, description="Content of the prompt"
            ),
            "name": fields.String(required=True, description="Name of the prompt"),
        },
    )

    @api.expect(create_prompt_model)
    @api.doc(description="Create a new prompt")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        data = request.get_json()
        required_fields = ["content", "name"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        user = decoded_token.get("sub")
        try:

            resp = prompts_collection.insert_one(
                {
                    "name": data["name"],
                    "content": data["content"],
                    "user": user,
                }
            )
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


@prompts_ns.route("/get_prompts")
class GetPrompts(Resource):
    @api.doc(description="Get all prompts for the user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            prompts = prompts_collection.find({"user": user})
            list_prompts = [
                {"id": "default", "name": "default", "type": "public"},
                {"id": "creative", "name": "creative", "type": "public"},
                {"id": "strict", "name": "strict", "type": "public"},
            ]

            for prompt in prompts:
                list_prompts.append(
                    {
                        "id": str(prompt["_id"]),
                        "name": prompt["name"],
                        "type": "private",
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompts: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify(list_prompts), 200)


@prompts_ns.route("/get_single_prompt")
class GetSinglePrompt(Resource):
    @api.doc(params={"id": "ID of the prompt"}, description="Get a single prompt by ID")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        prompt_id = request.args.get("id")
        if not prompt_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        try:
            if prompt_id == "default":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_default.txt"),
                    "r",
                ) as f:
                    chat_combine_template = f.read()
                return make_response(jsonify({"content": chat_combine_template}), 200)
            elif prompt_id == "creative":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_creative.txt"),
                    "r",
                ) as f:
                    chat_reduce_creative = f.read()
                return make_response(jsonify({"content": chat_reduce_creative}), 200)
            elif prompt_id == "strict":
                with open(
                    os.path.join(current_dir, "prompts", "chat_combine_strict.txt"), "r"
                ) as f:
                    chat_reduce_strict = f.read()
                return make_response(jsonify({"content": chat_reduce_strict}), 200)
            prompt = prompts_collection.find_one(
                {"_id": ObjectId(prompt_id), "user": user}
            )
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"content": prompt["content"]}), 200)


@prompts_ns.route("/delete_prompt")
class DeletePrompt(Resource):
    delete_prompt_model = api.model(
        "DeletePromptModel",
        {"id": fields.String(required=True, description="Prompt ID to delete")},
    )

    @api.expect(delete_prompt_model)
    @api.doc(description="Delete a prompt by ID")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            prompts_collection.delete_one({"_id": ObjectId(data["id"]), "user": user})
        except Exception as err:
            current_app.logger.error(f"Error deleting prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@prompts_ns.route("/update_prompt")
class UpdatePrompt(Resource):
    update_prompt_model = api.model(
        "UpdatePromptModel",
        {
            "id": fields.String(required=True, description="Prompt ID to update"),
            "name": fields.String(required=True, description="New name of the prompt"),
            "content": fields.String(
                required=True, description="New content of the prompt"
            ),
        },
    )

    @api.expect(update_prompt_model)
    @api.doc(description="Update an existing prompt")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "name", "content"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            prompts_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"name": data["name"], "content": data["content"]}},
            )
        except Exception as err:
            current_app.logger.error(f"Error updating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)
