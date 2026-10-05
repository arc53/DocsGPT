"""Prompt management routes."""


from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from docsgpt.api import api
from docsgpt.api.pat.rules import filter_listing
from docsgpt.api.user.resource_access import (
    AccessDenied,
    delete_settings,
    payload_for,
    require,
    settings_many,
)
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.prompts.composer import compose_preset, is_composed_preset
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields

prompts_ns = Namespace(
    "prompts", description="Prompt management operations", path="/api"
)


def _denied(err: AccessDenied):
    """JSON response for an :class:`AccessDenied` (403 or 404)."""
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


def _iso(value):
    """ISO-8601 string for a timestamp (``expected_updated_at`` round-trips it)."""
    return value.isoformat() if hasattr(value, "isoformat") else value


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
            with db_session() as conn:
                prompt = PromptsRepository(conn).create(user, data["name"], data["content"])
            new_id = str(prompt["id"])
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
            with db_readonly() as conn:
                repo = PromptsRepository(conn)
                prompts = repo.list_for_user(user)
                owned_ids = {str(p["id"]) for p in prompts}
                team_shared = visible_with_access(conn, user, "prompt")
                shared_ids = [pid for pid in team_shared if pid not in owned_ids]
                shared_prompts = repo.list_by_ids(shared_ids)
                switches = settings_many(
                    conn, "prompt", [*owned_ids, *(str(p["id"]) for p in shared_prompts)]
                )
            list_prompts = [
                {"id": "default", "name": "default", "type": "public"},
                {"id": "creative", "name": "creative", "type": "public"},
                {"id": "strict", "name": "strict", "type": "public"},
            ]
            for prompt in prompts:
                pid = str(prompt["id"])
                list_prompts.append(
                    {
                        "id": pid,
                        "name": prompt["name"],
                        "type": "private",
                        "updated_at": _iso(prompt.get("updated_at")),
                        **payload_for("prompt", "owner", switches.get(pid)),
                    }
                )
            for prompt in shared_prompts:
                pid = str(prompt["id"])
                list_prompts.append(
                    {
                        "id": pid,
                        "name": prompt["name"],
                        "type": "team",
                        "team_access": team_shared.get(pid),
                        "updated_at": _iso(prompt.get("updated_at")),
                        **payload_for("prompt", team_shared.get(pid), switches.get(pid)),
                    }
                )
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompts: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        # Presets (default/creative/strict) have no row id and stay visible to a restricted token.
        return make_response(jsonify(filter_listing(request, "prompts", list_prompts)), 200)


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
            if is_composed_preset(prompt_id):
                return make_response(
                    jsonify({"content": compose_preset(prompt_id)}), 200
                )
            with db_readonly() as conn:
                ra = require(conn, "prompt", prompt_id, user, "use")
                prompt = PromptsRepository(conn).get_any(ra.resource_id, ra.owner_id)
            if not prompt:
                return make_response(
                    jsonify({"success": False, "message": "Prompt not found"}), 404
                )
        except AccessDenied as err:
            return _denied(err)
        except Exception as err:
            current_app.logger.error(f"Error retrieving prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(
            jsonify(
                {
                    "content": prompt["content"],
                    "name": prompt.get("name"),
                    "updated_at": _iso(prompt.get("updated_at")),
                    **ra.payload(),
                }
            ),
            200,
        )


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
            with db_session() as conn:
                ra = require(conn, "prompt", data["id"], user, "delete")
                # Grants go with the row (delete trigger); switches have no FK.
                PromptsRepository(conn).delete(ra.resource_id, ra.owner_id)
                delete_settings(conn, "prompt", ra.resource_id)
        except AccessDenied as err:
            return _denied(err)
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
            with db_session() as conn:
                ra = require(conn, "prompt", data["id"], user, "edit")
                result = PromptsRepository(conn).update_by_id(
                    ra.resource_id,
                    data["name"],
                    data["content"],
                    expected_updated_at=data.get("expected_updated_at"),
                )
                if result is None:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Prompt was modified by someone else",
                                "code": "stale_write",
                            }
                        ),
                        409,
                    )
        except AccessDenied as err:
            return _denied(err)
        except Exception as err:
            current_app.logger.error(f"Error updating prompt: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)
