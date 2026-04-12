"""Tool management MCP server integration."""

import json
from urllib.parse import urlencode, urlparse

from bson.objectid import ObjectId
from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import Namespace, Resource, fields

from application.agents.tools.mcp_tool import MCPOAuthManager, MCPTool
from application.api import api
from application.api.user.base import user_tools_collection
from application.api.user.tools.routes import transform_actions
from application.cache import get_redis_instance
from application.core.mongo_db import MongoDB
from application.core.settings import settings
from application.core.url_validation import SSRFError, validate_url
from application.security.encryption import decrypt_credentials, encrypt_credentials
from application.utils import check_required_fields

tools_mcp_ns = Namespace("tools", description="Tool management operations", path="/api")

_mongo = MongoDB.get_client()
_db = _mongo[settings.MONGO_DB_NAME]
_connector_sessions = _db["connector_sessions"]

_ALLOWED_TRANSPORTS = {"auto", "sse", "http"}


def _sanitize_mcp_transport(config):
    """Normalise and validate the transport_type field.

    Strips ``command`` / ``args`` keys that are only valid for local STDIO
    transports and returns the cleaned transport type string.
    """
    transport_type = (config.get("transport_type") or "auto").lower()
    if transport_type not in _ALLOWED_TRANSPORTS:
        raise ValueError(f"Unsupported transport_type: {transport_type}")
    config.pop("command", None)
    config.pop("args", None)
    config["transport_type"] = transport_type
    return transport_type


def _extract_auth_credentials(config):
    """Build an ``auth_credentials`` dict from the raw MCP config."""
    auth_credentials = {}
    auth_type = config.get("auth_type", "none")

    if auth_type == "api_key":
        if config.get("api_key"):
            auth_credentials["api_key"] = config["api_key"]
        if config.get("api_key_header"):
            auth_credentials["api_key_header"] = config["api_key_header"]
    elif auth_type == "bearer":
        if config.get("bearer_token"):
            auth_credentials["bearer_token"] = config["bearer_token"]
    elif auth_type == "basic":
        if config.get("username"):
            auth_credentials["username"] = config["username"]
        if config.get("password"):
            auth_credentials["password"] = config["password"]

    return auth_credentials


def _validate_mcp_server_url(config: dict) -> None:
    """Validate the server_url in an MCP config to prevent SSRF.

    Raises:
        ValueError: If the URL is missing or points to a blocked address.
    """
    server_url = (config.get("server_url") or "").strip()
    if not server_url:
        raise ValueError("server_url is required")
    try:
        validate_url(server_url)
    except SSRFError as exc:
        raise ValueError(f"Invalid server URL: {exc}") from exc


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
            try:
                _sanitize_mcp_transport(config)
            except ValueError:
                return make_response(
                    jsonify({"success": False, "error": "Unsupported transport_type"}),
                    400,
                )

            _validate_mcp_server_url(config)

            auth_credentials = _extract_auth_credentials(config)
            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(config=test_config, user_id=user)
            result = mcp_tool.test_connection()

            if result.get("requires_oauth"):
                safe_result = {
                    k: v
                    for k, v in result.items()
                    if k in ("success", "requires_oauth", "auth_url")
                }
                return make_response(jsonify(safe_result), 200)

            if not result.get("success"):
                current_app.logger.error(
                    f"MCP connection test failed: {result.get('message')}"
                )
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Connection test failed",
                            "tools_count": 0,
                        }
                    ),
                    200,
                )

            safe_result = {
                "success": True,
                "message": result.get("message", "Connection successful"),
                "tools_count": result.get("tools_count", 0),
                "tools": result.get("tools", []),
            }
            return make_response(jsonify(safe_result), 200)
        except ValueError as e:
            current_app.logger.warning(f"Invalid MCP server test request: {e}")
            return make_response(
                jsonify({"success": False, "error": "Invalid MCP server configuration"}),
                400,
            )
        except Exception as e:
            current_app.logger.error(f"Error testing MCP server: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Connection test failed"}),
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
            try:
                _sanitize_mcp_transport(config)
            except ValueError:
                return make_response(
                    jsonify({"success": False, "error": "Unsupported transport_type"}),
                    400,
                )

            _validate_mcp_server_url(config)

            auth_credentials = _extract_auth_credentials(config)
            auth_type = config.get("auth_type", "none")
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

            tool_id = data.get("id")
            existing_encrypted = None
            if tool_id:
                existing_doc = user_tools_collection.find_one(
                    {"_id": ObjectId(tool_id), "user": user, "name": "mcp_tool"}
                )
                if existing_doc:
                    existing_encrypted = existing_doc.get("config", {}).get(
                        "encrypted_credentials"
                    )

            if auth_credentials:
                if existing_encrypted:
                    existing_secrets = decrypt_credentials(existing_encrypted, user)
                    existing_secrets.update(auth_credentials)
                    auth_credentials = existing_secrets
                storage_config["encrypted_credentials"] = encrypt_credentials(
                    auth_credentials, user
                )
            elif existing_encrypted:
                storage_config["encrypted_credentials"] = existing_encrypted

            for field in [
                "api_key",
                "bearer_token",
                "username",
                "password",
                "api_key_header",
                "redirect_uri",
            ]:
                storage_config.pop(field, None)
            transformed_actions = transform_actions(actions_metadata)
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
        except ValueError as e:
            current_app.logger.warning(f"Invalid MCP server save request: {e}")
            return make_response(
                jsonify({"success": False, "error": "Invalid MCP server configuration"}),
                400,
            )
        except Exception as e:
            current_app.logger.error(f"Error saving MCP server: {e}", exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "Failed to save MCP server"}),
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
                "provider": "mcp_tool",
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
        try:
            redis_client = get_redis_instance()
            status_key = f"mcp_oauth_status:{task_id}"
            status_data = redis_client.get(status_key)

            if status_data:
                status = json.loads(status_data)
                if "tools" in status and isinstance(status["tools"], list):
                    status["tools"] = [
                        {
                            "name": t.get("name", "unknown"),
                            "description": t.get("description", ""),
                        }
                        for t in status["tools"]
                    ]
                return make_response(
                    jsonify({"success": True, "task_id": task_id, **status})
                )
            else:
                return make_response(
                    jsonify(
                        {
                            "success": True,
                            "task_id": task_id,
                            "status": "pending",
                            "message": "Waiting for OAuth to start...",
                        }
                    ),
                    200,
                )
        except Exception as e:
            current_app.logger.error(
                f"Error getting OAuth status for task {task_id}: {str(e)}",
                exc_info=True,
            )
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "error": "Failed to get OAuth status",
                        "task_id": task_id,
                    }
                ),
                500,
            )


@tools_mcp_ns.route("/mcp_server/auth_status")
class MCPAuthStatus(Resource):
    @api.doc(
        description="Batch check auth status for all MCP tools. "
        "Lightweight DB-only check — no network calls to MCP servers."
    )
    def get(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            mcp_tools = list(
                user_tools_collection.find(
                    {"user": user, "name": "mcp_tool"},
                    {"_id": 1, "config": 1},
                )
            )
            if not mcp_tools:
                return make_response(jsonify({"success": True, "statuses": {}}), 200)

            oauth_server_urls = {}
            statuses = {}
            for tool in mcp_tools:
                tool_id = str(tool["_id"])
                config = tool.get("config", {})
                auth_type = config.get("auth_type", "none")
                if auth_type == "oauth":
                    server_url = config.get("server_url", "")
                    if server_url:
                        parsed = urlparse(server_url)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        oauth_server_urls[tool_id] = base_url
                    else:
                        statuses[tool_id] = "needs_auth"
                else:
                    statuses[tool_id] = "configured"

            if oauth_server_urls:
                unique_urls = list(set(oauth_server_urls.values()))
                sessions = list(
                    _connector_sessions.find(
                        {"user_id": user, "server_url": {"$in": unique_urls}},
                        {"server_url": 1, "tokens": 1},
                    )
                )
                url_has_tokens = {
                    doc["server_url"]: bool(doc.get("tokens", {}).get("access_token"))
                    for doc in sessions
                }
                for tool_id, base_url in oauth_server_urls.items():
                    if url_has_tokens.get(base_url):
                        statuses[tool_id] = "connected"
                    else:
                        statuses[tool_id] = "needs_auth"

            return make_response(jsonify({"success": True, "statuses": statuses}), 200)
        except Exception as e:
            current_app.logger.error(
                "Error checking MCP auth status: %s", e, exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": "Failed to check auth status"}),
                500,
            )
