"""Tool management routes."""

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource

from application.agents.tools.tool_manager import ToolManager
from application.api import api
from application.api.user.base import user_tools_collection
from application.security.encryption import decrypt_credentials, encrypt_credentials
from application.utils import check_required_fields, validate_function_name

tool_config = {}
tool_manager = ToolManager(config=tool_config)


tools_ns = Namespace("tools", description="Tool management operations", path="/api")


@tools_ns.route("/available_tools")
class AvailableTools(Resource):
    @api.doc(description="Get available tools for a user")
    def get(self):
        try:
            tools_metadata = []
            for tool_name, tool_instance in tool_manager.tools.items():
                doc = tool_instance.__doc__.strip()
                lines = doc.split("\n", 1)
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                tools_metadata.append(
                    {
                        "name": tool_name,
                        "displayName": name,
                        "description": description,
                        "configRequirements": tool_instance.get_config_requirements(),
                    }
                )
        except Exception as err:
            current_app.logger.error(
                f"Error getting available tools: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "data": tools_metadata}), 200)


@tools_ns.route("/get_tools")
class GetTools(Resource):
    @api.doc(description="Get tools created by a user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user = decoded_token.get("sub")
            tools = user_tools_collection.find({"user": user})
            user_tools = []
            for tool in tools:
                tool["id"] = str(tool["_id"])
                tool.pop("_id")
                user_tools.append(tool)
        except Exception as err:
            current_app.logger.error(f"Error getting user tools: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "tools": user_tools}), 200)


@tools_ns.route("/create_tool")
class CreateTool(Resource):
    @api.expect(
        api.model(
            "CreateToolModel",
            {
                "name": fields.String(required=True, description="Name of the tool"),
                "displayName": fields.String(
                    required=True, description="Display name for the tool"
                ),
                "description": fields.String(
                    required=True, description="Tool description"
                ),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
                "customName": fields.String(
                    required=False, description="Custom name for the tool"
                ),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Create a new tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = [
            "name",
            "displayName",
            "description",
            "config",
            "status",
        ]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            tool_instance = tool_manager.tools.get(data["name"])
            if not tool_instance:
                return make_response(
                    jsonify({"success": False, "message": "Tool not found"}), 404
                )
            actions_metadata = tool_instance.get_actions_metadata()
            transformed_actions = []
            for action in actions_metadata:
                action["active"] = True
                if "parameters" in action:
                    if "properties" in action["parameters"]:
                        for param_name, param_details in action["parameters"][
                            "properties"
                        ].items():
                            param_details["filled_by_llm"] = True
                            param_details["value"] = ""
                transformed_actions.append(action)
        except Exception as err:
            current_app.logger.error(
                f"Error getting tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        try:
            new_tool = {
                "user": user,
                "name": data["name"],
                "displayName": data["displayName"],
                "description": data["description"],
                "customName": data.get("customName", ""),
                "actions": transformed_actions,
                "config": data["config"],
                "status": data["status"],
            }
            resp = user_tools_collection.insert_one(new_tool)
            new_id = str(resp.inserted_id)
        except Exception as err:
            current_app.logger.error(f"Error creating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


@tools_ns.route("/update_tool")
class UpdateTool(Resource):
    @api.expect(
        api.model(
            "UpdateToolModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "name": fields.String(description="Name of the tool"),
                "displayName": fields.String(description="Display name for the tool"),
                "customName": fields.String(description="Custom name for the tool"),
                "description": fields.String(description="Tool description"),
                "config": fields.Raw(description="Configuration of the tool"),
                "actions": fields.List(
                    fields.Raw, description="Actions the tool can perform"
                ),
                "status": fields.Boolean(description="Status of the tool"),
            },
        )
    )
    @api.doc(description="Update a tool by ID")
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
            update_data = {}
            if "name" in data:
                update_data["name"] = data["name"]
            if "displayName" in data:
                update_data["displayName"] = data["displayName"]
            if "customName" in data:
                update_data["customName"] = data["customName"]
            if "description" in data:
                update_data["description"] = data["description"]
            if "actions" in data:
                update_data["actions"] = data["actions"]
            if "config" in data:
                if "actions" in data["config"]:
                    for action_name in list(data["config"]["actions"].keys()):
                        if not validate_function_name(action_name):
                            return make_response(
                                jsonify(
                                    {
                                        "success": False,
                                        "message": f"Invalid function name '{action_name}'. Function names must match pattern '^[a-zA-Z0-9_-]+$'.",
                                        "param": "tools[].function.name",
                                    }
                                ),
                                400,
                            )
                tool_doc = user_tools_collection.find_one(
                    {"_id": ObjectId(data["id"]), "user": user}
                )
                if tool_doc and tool_doc.get("name") == "mcp_tool":
                    config = data["config"]
                    existing_config = tool_doc.get("config", {})
                    storage_config = existing_config.copy()

                    storage_config.update(config)
                    existing_credentials = {}
                    if "encrypted_credentials" in existing_config:
                        existing_credentials = decrypt_credentials(
                            existing_config["encrypted_credentials"], user
                        )
                    auth_credentials = existing_credentials.copy()
                    auth_type = storage_config.get("auth_type", "none")
                    if auth_type == "api_key":
                        if "api_key" in config and config["api_key"]:
                            auth_credentials["api_key"] = config["api_key"]
                        if "api_key_header" in config:
                            auth_credentials["api_key_header"] = config[
                                "api_key_header"
                            ]
                    elif auth_type == "bearer":
                        if "bearer_token" in config and config["bearer_token"]:
                            auth_credentials["bearer_token"] = config["bearer_token"]
                        elif "encrypted_token" in config and config["encrypted_token"]:
                            auth_credentials["bearer_token"] = config["encrypted_token"]
                    elif auth_type == "basic":
                        if "username" in config and config["username"]:
                            auth_credentials["username"] = config["username"]
                        if "password" in config and config["password"]:
                            auth_credentials["password"] = config["password"]
                    if auth_type != "none" and auth_credentials:
                        encrypted_credentials_string = encrypt_credentials(
                            auth_credentials, user
                        )
                        storage_config["encrypted_credentials"] = (
                            encrypted_credentials_string
                        )
                    elif auth_type == "none":
                        storage_config.pop("encrypted_credentials", None)
                    for field in [
                        "api_key",
                        "bearer_token",
                        "encrypted_token",
                        "username",
                        "password",
                        "api_key_header",
                    ]:
                        storage_config.pop(field, None)
                    update_data["config"] = storage_config
                else:
                    update_data["config"] = data["config"]
            if "status" in data:
                update_data["status"] = data["status"]
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": update_data},
            )
        except Exception as err:
            current_app.logger.error(f"Error updating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_config")
class UpdateToolConfig(Resource):
    @api.expect(
        api.model(
            "UpdateToolConfigModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "config": fields.Raw(
                    required=True, description="Configuration of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the configuration of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"config": data["config"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool config: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_actions")
class UpdateToolActions(Resource):
    @api.expect(
        api.model(
            "UpdateToolActionsModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "actions": fields.List(
                    fields.Raw,
                    required=True,
                    description="Actions the tool can perform",
                ),
            },
        )
    )
    @api.doc(description="Update the actions of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "actions"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"actions": data["actions"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/update_tool_status")
class UpdateToolStatus(Resource):
    @api.expect(
        api.model(
            "UpdateToolStatusModel",
            {
                "id": fields.String(required=True, description="Tool ID"),
                "status": fields.Boolean(
                    required=True, description="Status of the tool"
                ),
            },
        )
    )
    @api.doc(description="Update the status of a tool")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "status"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            user_tools_collection.update_one(
                {"_id": ObjectId(data["id"]), "user": user},
                {"$set": {"status": data["status"]}},
            )
        except Exception as err:
            current_app.logger.error(
                f"Error updating tool status: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/delete_tool")
class DeleteTool(Resource):
    @api.expect(
        api.model(
            "DeleteToolModel",
            {"id": fields.String(required=True, description="Tool ID")},
        )
    )
    @api.doc(description="Delete a tool by ID")
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
            result = user_tools_collection.delete_one(
                {"_id": ObjectId(data["id"]), "user": user}
            )
            if result.deleted_count == 0:
                return {"success": False, "message": "Tool not found"}, 404
        except Exception as err:
            current_app.logger.error(f"Error deleting tool: {err}", exc_info=True)
            return {"success": False}, 400
        return {"success": True}, 200
