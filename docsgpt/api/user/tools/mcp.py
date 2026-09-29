"""Tool management MCP server integration."""

from urllib.parse import urlencode, urlparse

from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import Namespace, Resource, fields

from docsgpt.agents.tools.mcp_tool import MCPOAuthManager, MCPTool
from docsgpt.api import api
from docsgpt.api.user.resource_access import AccessDenied, require
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.api.user.tools.routes import (
    _CREDENTIALS_FOR_NEW_SERVER,
    _MCP_CREDENTIAL_AUTH_TYPES,
    _mcp_host_changed,
    denied_response,
    transform_actions,
)
from docsgpt.cache import get_redis_instance
from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.security.encryption import decrypt_credentials, encrypt_credentials
from docsgpt.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields

tools_mcp_ns = Namespace("tools", description="Tool management operations", path="/api")

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


_ONLY_OWNER_RECONNECTS = "Only the owner can reconnect this account"


def _existing_mcp_context(tool_id, user, config):
    """Resolve the stored MCP tool a test/save refers to, and its credentials.

    With no ``tool_id`` the caller acts on their own new server. With one,
    the caller needs ``edit_credentials`` on that tool and everything runs as
    its owner. Stored secrets are write-only, so an empty secret field reuses
    the stored one while the host is unchanged; a new host never inherits them.

    Returns:
        ``(existing_doc, owner_id, is_owner, moved, credentials)``, or a Flask
        response (404 / 400) to return as is.

    Raises:
        AccessDenied: the caller can't see the tool (404) or can't change
            its credentials (403).
    """
    auth_credentials = _extract_auth_credentials(config)
    if not tool_id:
        return None, user, True, False, auth_credentials
    with db_readonly() as conn:
        ra = require(conn, "tool", tool_id, user, "edit_credentials")
        existing_doc = UserToolsRepository(conn).get_any(ra.resource_id, ra.owner_id)
    if not existing_doc or existing_doc.get("name") != "mcp_tool":
        return make_response(
            jsonify({"success": False, "message": "Tool not found or access denied"}), 404,
        )
    existing_config = existing_doc.get("config") or {}
    moved = _mcp_host_changed(config, existing_config)
    auth_type = config.get("auth_type", "none")
    new_secret_keys = set(auth_credentials) - {"api_key_header"}
    if moved and auth_type in _MCP_CREDENTIAL_AUTH_TYPES and not new_secret_keys:
        return make_response(
            jsonify({"success": False, "message": _CREDENTIALS_FOR_NEW_SERVER}), 400
        )
    credentials = dict(auth_credentials)
    existing_encrypted = None if moved else existing_config.get("encrypted_credentials")
    if existing_encrypted:
        credentials = {**decrypt_credentials(existing_encrypted, ra.owner_id), **auth_credentials}
    return existing_doc, ra.owner_id, ra.access == "owner", moved, credentials


@tools_mcp_ns.route("/mcp_server/test")
class TestMCPServerConfig(Resource):
    @api.expect(
        api.model(
            "MCPServerTestModel",
            {
                "id": fields.String(
                    required=False,
                    description="Stored tool to test with (empty secrets reuse its stored ones)",
                ),
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

            ctx = _existing_mcp_context(data.get("id"), user, config)
            if not isinstance(ctx, tuple):
                return ctx
            _existing_doc, owner_id, is_owner, _moved, auth_credentials = ctx
            if not is_owner and config.get("auth_type") == "oauth":
                # An OAuth flow would store tokens under the editor's account
                # (and its popup event goes to that account), not the owner's.
                return make_response(
                    jsonify({"success": False, "message": _ONLY_OWNER_RECONNECTS}), 403
                )
            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(config=test_config, user_id=owner_id)
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
        except AccessDenied as e:
            return denied_response(e)
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

            # An existing id is always an update of THAT row, written as its
            # owner; it never falls through to creating a copy for the caller.
            ctx = _existing_mcp_context(data.get("id"), user, config)
            if not isinstance(ctx, tuple):
                return ctx
            existing_doc, owner_id, is_owner, moved, merged_credentials = ctx
            existing_config = (existing_doc or {}).get("config") or {}
            auth_type = config.get("auth_type", "none")
            mcp_config = config.copy()
            mcp_config["auth_credentials"] = merged_credentials
            keep_actions = False

            if auth_type == "oauth":
                if config.get("oauth_task_id"):
                    if not is_owner:
                        # The OAuth flow stores tokens under the account that
                        # ran it; reconnecting as the owner is owner-only.
                        return make_response(
                            jsonify({
                                "success": False,
                                "message": _ONLY_OWNER_RECONNECTS,
                            }),
                            403,
                        )
                    redis_client = get_redis_instance()
                    manager = MCPOAuthManager(redis_client)
                    result = manager.get_oauth_status(
                        config["oauth_task_id"], user
                    )
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
                elif (
                    existing_doc is not None
                    and not moved
                    and existing_config.get("auth_type") == "oauth"
                ):
                    # Editing an already-connected server: keep its tools.
                    actions_metadata = existing_doc.get("actions") or []
                    keep_actions = True
                else:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "Connection not authorized. Please complete the OAuth authorization first.",
                            }
                        ),
                        400,
                    )
            elif auth_type == "none" or merged_credentials:
                mcp_tool = MCPTool(config=mcp_config, user_id=owner_id)
                mcp_tool.discover_tools()
                actions_metadata = mcp_tool.get_actions_metadata()
            else:
                raise Exception(
                    "No valid credentials provided for the selected authentication type"
                )
            storage_config = config.copy()

            if merged_credentials:
                storage_config["encrypted_credentials"] = encrypt_credentials(
                    merged_credentials, owner_id
                )

            for field in [
                "api_key",
                "bearer_token",
                "username",
                "password",
                "api_key_header",
                "redirect_uri",
            ]:
                storage_config.pop(field, None)
            # Kept actions already carry the owner's on/off and approval flags.
            transformed_actions = actions_metadata if keep_actions else transform_actions(actions_metadata)

            display_name = data["displayName"]
            description = f"MCP Server: {storage_config.get('server_url', 'Unknown')}"
            status_bool = bool(data.get("status", True))
            fields_out = {
                "display_name": display_name,
                "custom_name": display_name,
                "description": description,
                "config": storage_config,
                "actions": transformed_actions,
            }
            updated_message = (
                f"MCP server updated successfully! Discovered {len(transformed_actions)} tools."
            )

            with db_session() as conn:
                repo = UserToolsRepository(conn)
                if existing_doc is not None:
                    # ``status`` is the owner's own chat switch; an editor's
                    # save doesn't flip it.
                    if is_owner:
                        fields_out["status"] = status_bool
                    repo.update(str(existing_doc["id"]), owner_id, fields_out)
                    saved_id = str(existing_doc["id"])
                    response_data = {
                        "success": True,
                        "id": saved_id,
                        "message": updated_message,
                        "tools_count": len(transformed_actions),
                    }
                else:
                    fields_out["status"] = status_bool
                    # Fall back to find_by_user_and_name — the original
                    # dual-write path also ran an existence check before
                    # deciding between insert and update.
                    existing_by_name = repo.find_by_user_and_name(user, "mcp_tool")
                    if existing_by_name and (
                        (existing_by_name.get("config") or {}).get("server_url")
                        == storage_config.get("server_url")
                    ):
                        repo.update(str(existing_by_name["id"]), user, fields_out)
                        saved_id = str(existing_by_name["id"])
                        response_data = {
                            "success": True,
                            "id": saved_id,
                            "message": updated_message,
                            "tools_count": len(transformed_actions),
                        }
                    else:
                        created = repo.create(
                            user, "mcp_tool",
                            config=storage_config,
                            custom_name=display_name,
                            display_name=display_name,
                            description=description,
                            config_requirements={},
                            actions=transformed_actions,
                            status=status_bool,
                        )
                        saved_id = str(created["id"])
                        response_data = {
                            "success": True,
                            "id": saved_id,
                            "message": f"MCP server created successfully! Discovered {len(transformed_actions)} tools.",
                            "tools_count": len(transformed_actions),
                        }
            return make_response(jsonify(response_data), 200)
        except AccessDenied as e:
            return denied_response(e)
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
            with db_readonly() as conn:
                tools_repo = UserToolsRepository(conn)
                sessions_repo = ConnectorSessionsRepository(conn)
                all_tools = tools_repo.list_for_user(user)
                owned_ids = {str(t["id"]) for t in all_tools}
                # Team-shared MCP servers the caller can see run with the
                # owner's connection, so their status is the owner's.
                shared_ids = [
                    tid for tid in visible_with_access(conn, user, "tool") if tid not in owned_ids
                ]
                all_tools = all_tools + tools_repo.list_by_ids(shared_ids)
                mcp_tools = [t for t in all_tools if t.get("name") == "mcp_tool"]
                if not mcp_tools:
                    return make_response(
                        jsonify({"success": True, "statuses": {}}), 200
                    )

                oauth_server_urls: dict = {}
                statuses: dict = {}
                for tool in mcp_tools:
                    tool_id = str(tool["id"])
                    config = tool.get("config") or {}
                    auth_type = config.get("auth_type", "none")
                    if auth_type == "oauth":
                        server_url = config.get("server_url", "")
                        if server_url:
                            parsed = urlparse(server_url)
                            base_url = f"{parsed.scheme}://{parsed.netloc}"
                            oauth_server_urls[tool_id] = (tool.get("user_id") or user, base_url)
                        else:
                            statuses[tool_id] = "needs_auth"
                    else:
                        statuses[tool_id] = "configured"

                if oauth_server_urls:
                    # Look up a session per distinct base URL. MCP sessions
                    # are stored with ``provider = "mcp:<server_url>"``
                    # and the URL in ``server_url``; reuse the repo's
                    # per-URL accessor rather than an ad-hoc $in query.
                    url_has_tokens: dict = {}
                    for owner_id, base_url in set(oauth_server_urls.values()):
                        session = sessions_repo.get_by_user_and_server_url(
                            owner_id, base_url,
                        )
                        tokens = (
                            (session or {}).get("session_data", {}) or {}
                        ).get("tokens", {}) or {}
                        # MCP code also stashes tokens into token_info on
                        # the row; consider either present as "connected".
                        token_info = (session or {}).get("token_info") or {}
                        url_has_tokens[(owner_id, base_url)] = bool(
                            tokens.get("access_token")
                            or token_info.get("access_token")
                        )

                    for tool_id, key in oauth_server_urls.items():
                        if url_has_tokens.get(key):
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
