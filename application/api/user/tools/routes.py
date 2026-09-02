"""Tool management routes."""

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from application.agents.tools import tool_manager
from application.api import api
from application.storage.db.repositories.user_tools import UserToolsRepository
from application.storage.db.session import db_readonly, db_session
from application.utils import check_required_fields

tools_ns = Namespace("tools", description="Tool management operations", path="/api")


def transform_actions(actions_metadata):
    """Set default flags on action metadata for storage.

    Marks each action as active, sets ``filled_by_llm`` and ``value`` on every
    parameter property. Used by both the generic create_tool and MCP save routes.
    """
    transformed = []
    for action in actions_metadata:
        action["active"] = True
        if "parameters" in action:
            props = action["parameters"].get("properties", {})
            for param_details in props.values():
                if not isinstance(param_details, dict):
                    continue
                param_details["filled_by_llm"] = True
                param_details["value"] = ""
        transformed.append(action)
    return transformed


@tools_ns.route("/available_tools")
class AvailableTools(Resource):
    @api.doc(description="Get available tools for a user")
    def get(self):
        if not request.decoded_token:
            return make_response(jsonify({"success": False}), 401)
        try:
            tools_metadata = []
            for tool_name, tool_instance in tool_manager.tools.items():
                doc = tool_instance.__doc__.strip()
                lines = doc.split("\n", 1)
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                config_req = tool_instance.get_config_requirements()
                actions = tool_instance.get_actions_metadata()
                tools_metadata.append(
                    {
                        "name": tool_name,
                        "displayName": name,
                        "description": description,
                        "configRequirements": config_req,
                        "actions": actions,
                    }
                )
            return make_response(jsonify({"tools": tools_metadata}), 200)
        except Exception as e:
            current_app.logger.error(f"Error getting available tools: {e}")
            return make_response(jsonify({"error": str(e)}), 500)


@tools_ns.route("/tools")
class UserTools(Resource):
    @api.doc(description="Get tools for the current user")
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                repo = UserToolsRepository(conn)
                tools = repo.list_for_user(user)
            return make_response(jsonify({"tools": tools}), 200)
        except Exception as e:
            current_app.logger.error(f"Error getting user tools: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @api.expect(
        api.model(
            "CreateToolModel",
            {
                "name": fields.String(required=True, description="Tool name"),
                "displayName": fields.String(
                    required=True, description="Display name for the tool"
                ),
                "config": fields.Raw(required=True, description="Tool configuration"),
                "status": fields.Boolean(
                    required=False, default=True, description="Tool status"
                ),
            },
        )
    )
    @api.doc(description="Create a new tool for the current user")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()

        required_fields = ["name", "displayName", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields

        tool_name = data["name"]
        if tool_name not in tool_manager.tools:
            return make_response(
                jsonify({"success": False, "error": f"Tool {tool_name} not found"}),
                404,
            )

        try:
            tool_instance = tool_manager.tools[tool_name]
            config = data["config"]
            actions_metadata = tool_instance.get_actions_metadata()
            transformed_actions = transform_actions(actions_metadata)

            display_name = data["displayName"]
            description = data.get("description", "")
            status_bool = bool(data.get("status", True))

            with db_session() as conn:
                repo = UserToolsRepository(conn)
                created = repo.create(
                    user,
                    tool_name,
                    config=config,
                    custom_name=display_name,
                    display_name=display_name,
                    description=description,
                    config_requirements=tool_instance.get_config_requirements(),
                    actions=transformed_actions,
                    status=status_bool,
                )
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "id": str(created["id"]),
                        "message": "Tool created successfully",
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(f"Error creating tool: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Failed to create tool"}), 500
            )


@tools_ns.route("/tools/<string:tool_id>")
class UserTool(Resource):
    @api.doc(description="Get a specific tool")
    def get(self, tool_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_readonly() as conn:
                repo = UserToolsRepository(conn)
                tool = repo.get(tool_id, user)
            if not tool:
                return make_response(
                    jsonify({"success": False, "error": "Tool not found"}), 404
                )
            return make_response(jsonify(tool), 200)
        except Exception as e:
            current_app.logger.error(f"Error getting tool: {e}")
            return make_response(jsonify({"error": str(e)}), 500)

    @api.doc(description="Update a tool")
    def put(self, tool_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        try:
            update_data = {}
            if "displayName" in data:
                update_data["display_name"] = data["displayName"]
                update_data["custom_name"] = data["displayName"]
            if "config" in data:
                update_data["config"] = data["config"]
            if "status" in data:
                update_data["status"] = bool(data["status"])
            if "actions" in data:
                update_data["actions"] = data["actions"]

            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool = repo.get(tool_id, user)
                if not tool:
                    return make_response(
                        jsonify({"success": False, "error": "Tool not found"}), 404
                    )

                if "config" in data and tool.get("name") in tool_manager.tools:
                    tool_instance = tool_manager.tools[tool["name"]]
                    actions_metadata = tool_instance.get_actions_metadata()
                    update_data["actions"] = transform_actions(actions_metadata)

                repo.update(tool_id, user, update_data)

            return make_response(
                jsonify({"success": True, "message": "Tool updated successfully"}), 200
            )
        except Exception as e:
            current_app.logger.error(f"Error updating tool: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Failed to update tool"}), 500
            )

    @api.doc(description="Delete a tool")
    def delete(self, tool_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool = repo.get(tool_id, user)
                if not tool:
                    return make_response(
                        jsonify({"success": False, "error": "Tool not found"}), 404
                    )
                repo.delete(tool_id, user)
            return make_response(
                jsonify({"success": True, "message": "Tool deleted successfully"}), 200
            )
        except Exception as e:
            current_app.logger.error(f"Error deleting tool: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Failed to delete tool"}), 500
            )


@tools_ns.route("/tools/<string:tool_id>/toggle")
class ToggleTool(Resource):
    @api.doc(description="Toggle tool status")
    def post(self, tool_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                tool = repo.get(tool_id, user)
                if not tool:
                    return make_response(
                        jsonify({"success": False, "error": "Tool not found"}), 404
                    )
                new_status = not bool(tool.get("status", True))
                repo.update(tool_id, user, {"status": new_status})
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "status": new_status,
                        "message": f"Tool {'enabled' if new_status else 'disabled'} successfully",
                    }
                ),
                200,
            )
        except Exception as e:
            current_app.logger.error(f"Error toggling tool: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Failed to toggle tool"}), 500
            )
