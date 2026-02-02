"""Tool management MCP server integration."""

import json
from urllib.parse import unquote, urlencode

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import fields, Namespace, Resource

from application.agents.tools.mcp_tool import MCPOAuthManager, MCPTool
from application.api import api
from application.api.user.base import user_tools_collection
from application.cache import get_redis_instance
from application.security.encryption import encrypt_credentials
from application.utils import check_required_fields

tools_mcp_ns = Namespace("tools", description="Tool management operations", path="/api")


@tools_mcp_ns.route("/mcp_server/test")
class TestMCPServerConfig(Resource):
    @api.expect(
        api.model(
            "MCPServerTestModel",
            {
                "config": fields.Raw(
                    required=True, description="MCP server configuration to test"
                ),
            },
        )
    )
    @api.doc(description="Test MCP server connection with provided configuration")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()

        required_fields = ["config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = data["config"]
            transport_type = (config.get("transport_type") or "auto").lower()
            allowed_transports = {"auto", "sse", "http"}
            if transport_type not in allowed_transports:
                return make_response(
                    jsonify({"success": False, "error": "Unsupported transport_type"}),
                    400,
                )
            config.pop("command", None)
            config.pop("args", None)
            config["transport_type"] = transport_type

            auth_credentials = {}
            auth_type = config.get("auth_type", "none")

            if auth_type == "api_key" and "api_key" in config:
                auth_credentials["api_key"] = config["api_key"]
                if "api_key_header" in config:
                    auth_credentials["api_key_header"] = config["api_key_header"]
            elif auth_type == "bearer" and "bearer_token" in config:
                auth_credentials["bearer_token"] = config["bearer_token"]
            elif auth_type == "basic":
                if "username" in config:
                    auth_credentials["username"] = config["username"]
                if "password" in config:
                    auth_credentials["password"] = config["password"]
            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(config=test_config, user_id=user)
            result = mcp_tool.test_connection()

            # Sanitize the response to avoid exposing internal error details
            if not result.get("success") and "message" in result:
                current_app.logger.error(f"MCP connection test failed: {result.get('message')}")
                result["message"] = "Connection test failed"

            return make_response(jsonify(result), 200)
        except Exception as e:
            current_app.logger.error(f"Error testing MCP server: {e}", exc_info=True)
            return make_response(
                jsonify(
                    {"success": False, "error": "Connection test failed"}
                ),
                500,
            )


@tools_mcp_ns.route("/mcp_server/save")
class MCPServerSave(Resource):
    @api.expect(
        api.model(
            "MCPServerSaveModel",
            {
                "id": fields.String(
                    required=False, description="Tool ID for updates (optional)"
                ),
                "displayName": fields.String(
                    required=True, description="Display name for the MCP server"
                ),
                "config": fields.Raw(
                    required=True, description="MCP server configuration"
                ),
                "status": fields.Boolean(
                    required=False, default=True, description="Tool status"
                ),
            },
        )
    )
    @api.doc(description="Create or update MCP server with automatic tool discovery")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()

        required_fields = ["displayName", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        try:
            config = data["config"]
            transport_type = (config.get("transport_type") or "auto").lower()
            allowed_transports = {"auto", "sse", "http"}
            if transport_type not in allowed_transports:
                return make_response(
                    jsonify({"success": False, "error": "Unsupported transport_type"}),
                    400,
                )
            config.pop("command", None)
            config.pop("args", None)
            config["transport_type"] = transport_type

            auth_credentials = {}
            auth_type = config.get("auth_type", "none")
            if auth_type == "api_key":
                if "api_key" in config and config["api_key"]:
                    auth_credentials["api_key"] = config["api_key"]
                if "api_key_header" in config:
                    auth_credentials["api_key_header"] = config["api_key_header"]
            elif auth_type == "bearer":
                if "bearer_token" in config and config["bearer_token"]:
                    auth_credentials["bearer_token"] = config["bearer_token"]
            elif auth_type == "basic":
                if "username" in config and config["username"]:
                    auth_credentials["username"] = config["username"]
                if "password" in config and config["password"]:
                    auth_credentials["password"] = config["password"]
            mcp_config = config.copy()
            mcp_config["auth_credentials"] = auth_credentials

            if auth_type == "oauth":
                if not config.get("oauth_task_id"):
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "Connection not authorized. Please complete the OAuth authorization first.",
                            }
                        ),
                        400,
                    )
                redis_client = get_redis_instance()
                manager = MCPOAuthManager(redis_client)
                result = manager.get_oauth_status(config["oauth_task_id"])
                if not result.get("status") == "completed":
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "OAuth failed or not completed. Please try authorizing again.",
                            }
                        ),
                        400,
                    )
                actions_metadata = result.get("tools", [])
            elif auth_type == "none" or auth_credentials:
                mcp_tool = MCPTool(config=mcp_config, user_id=user)
                mcp_tool.discover_tools()
                actions_metadata = mcp_tool.get_actions_metadata()
            else:
                raise Exception(
                    "No valid credentials provided for the selected authentication type"
                )
            storage_config = config.copy()
            if auth_credentials:
                encrypted_credentials_string = encrypt_credentials(
                    auth_credentials, user
                )
                storage_config["encrypted_credentials"] = encrypted_credentials_string
            for field in [
                "api_key",
                "bearer_token",
                "username",
                "password",
                "api_key_header",
            ]:
                storage_config.pop(field, None)
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
            tool_data = {
                "name": "mcp_tool",
                "displayName": data["displayName"],
                "customName": data["displayName"],
                "description": f"MCP Server: {storage_config.get('server_url', 'Unknown')}",
                "config": storage_config,
                "actions": transformed_actions,
                "status": data.get("status", True),
                "user": user,
            }

            tool_id = data.get("id")
            if tool_id:
                result = user_tools_collection.update_one(
                    {"_id": ObjectId(tool_id), "user": user, "name": "mcp_tool"},
                    {"$set": {k: v for k, v in tool_data.items() if k != "user"}},
                )
                if result.matched_count == 0:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "Tool not found or access denied",
                            }
                        ),
                        404,
                    )
                response_data = {
                    "success": True,
                    "id": tool_id,
                    "message": f"MCP server updated successfully! Discovered {len(transformed_actions)} tools.",
                    "tools_count": len(transformed_actions),
                }
            else:
                result = user_tools_collection.insert_one(tool_data)
                tool_id = str(result.inserted_id)
                response_data = {
                    "success": True,
                    "id": tool_id,
                    "message": f"MCP server created successfully! Discovered {len(transformed_actions)} tools.",
                    "tools_count": len(transformed_actions),
                }
            return make_response(jsonify(response_data), 200)
        except Exception as e:
            current_app.logger.error(f"Error saving MCP server: {e}", exc_info=True)
            return make_response(
                jsonify(
                    {"success": False, "error": "Failed to save MCP server"}
                ),
                500,
            )


@tools_mcp_ns.route("/mcp_server/callback")
class MCPOAuthCallback(Resource):
    @api.expect(
        api.model(
            "MCPServerCallbackModel",
            {
                "code": fields.String(required=True, description="Authorization code"),
                "state": fields.String(required=True, description="State parameter"),
                "error": fields.String(
                    required=False, description="Error message (if any)"
                ),
            },
        )
    )
    @api.doc(
        description="Handle OAuth callback by providing the authorization code and state"
    )
    def get(self):
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            params = {
                "status": "error",
                "message": f"OAuth error: {error}. Please try again and make sure to grant all requested permissions, including offline access.",
                "provider": "mcp_tool"
            }
            return redirect(f"/api/connectors/callback-status?{urlencode(params)}")
        if not code or not state:
            return redirect(
                "/api/connectors/callback-status?status=error&message=Authorization+code+or+state+not+provided.+Please+complete+the+authorization+process+and+make+sure+to+grant+offline+access.&provider=mcp_tool"
            )
        try:
            redis_client = get_redis_instance()
            if not redis_client:
                return redirect(
                    "/api/connectors/callback-status?status=error&message=Internal+server+error:+Redis+not+available.&provider=mcp_tool"
                )
            code = unquote(code)
            manager = MCPOAuthManager(redis_client)
            success = manager.handle_oauth_callback(state, code, error)
            if success:
                return redirect(
                    "/api/connectors/callback-status?status=success&message=Authorization+code+received+successfully.+You+can+close+this+window.&provider=mcp_tool"
                )
            else:
                return redirect(
                    "/api/connectors/callback-status?status=error&message=OAuth+callback+failed.&provider=mcp_tool"
                )
        except Exception as e:
            current_app.logger.error(
                f"Error handling MCP OAuth callback: {str(e)}", exc_info=True
            )
            return redirect(
                "/api/connectors/callback-status?status=error&message=Internal+server+error.&provider=mcp_tool"
            )


@tools_mcp_ns.route("/mcp_server/oauth_status/<string:task_id>")
class MCPOAuthStatus(Resource):
    def get(self, task_id):
        """
        Get current status of OAuth flow.
        Frontend should poll this endpoint periodically.
        """
        try:
            redis_client = get_redis_instance()
            status_key = f"mcp_oauth_status:{task_id}"
            status_data = redis_client.get(status_key)

            if status_data:
                status = json.loads(status_data)
                return make_response(
                    jsonify({"success": True, "task_id": task_id, **status})
                )
            else:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "error": "Task not found or expired",
                            "task_id": task_id,
                        }
                    ),
                    404,
                )
        except Exception as e:
            current_app.logger.error(
                f"Error getting OAuth status for task {task_id}: {str(e)}", exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": "Failed to get OAuth status", "task_id": task_id}), 500
            )
