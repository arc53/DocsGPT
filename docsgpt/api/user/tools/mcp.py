"""Tool management MCP server integration."""

from urllib.parse import urlencode, urlparse

from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import Namespace, Resource, fields

from docsgpt.agents.tool_pins import carry_pins_between
from docsgpt.agents.tools.mcp_tool import MCPOAuthManager, MCPTool
from docsgpt.api import api
from docsgpt.api.user.resource_access import AccessDenied, require
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.api.user.tools.routes import (
    _CREDENTIALS_FOR_NEW_SERVER,
    _MCP_CREDENTIAL_AUTH_TYPES,
    _mcp_origin_changed,
    check_oauth_mcp_owner_only,
    denied_response,
    transform_actions,
)
from docsgpt.cache import get_redis_instance
from docsgpt.connectors.resolve import REMOVED_CONNECTION_KEY
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
    transports, ``connection_id``, which only the tool executor sets
    (it picks whose MCP tokens the tool uses), and the note that a
    connection was removed, which only removing one writes (a save stores
    a fresh config, so it drops that note too). Returns the cleaned
    transport type string.
    """
    transport_type = (config.get("transport_type") or "auto").lower()
    if transport_type not in _ALLOWED_TRANSPORTS:
        raise ValueError(f"Unsupported transport_type: {transport_type}")
    config.pop("command", None)
    config.pop("args", None)
    config.pop("connection_id", None)
    config.pop(REMOVED_CONNECTION_KEY, None)
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


class InvalidServerUrl(ValueError):
    """The MCP server URL is refused by the outbound URL check; the message is safe to show the user."""


def _validate_mcp_server_url(config: dict) -> None:
    """Validate the server_url in an MCP config to prevent SSRF.

    Raises:
        ValueError: If the URL is missing.
        InvalidServerUrl: If it points to a blocked address.
    """
    server_url = (config.get("server_url") or "").strip()
    if not server_url:
        raise ValueError("server_url is required")
    try:
        validate_url(server_url)
    except SSRFError as exc:
        raise InvalidServerUrl(f"Invalid server URL: {exc}") from exc


def _invalid_server_url_response(exc: InvalidServerUrl):
    """400 naming why the URL was refused, as ``error`` and as ``message`` (what the dialog shows)."""
    return make_response(jsonify({"success": False, "error": str(exc), "message": str(exc)}), 400)


def _mcp_connection(user, config, auth_type, auth_credentials, display_name):
    """The connection an MCP tool runs with; created on first save.

    OAuth servers already have one (the sign-in stored its tokens there).
    Key, bearer and basic auth store their secret on a connection; servers
    with no auth get a credential-less connection so they still appear on
    the Connectors page. Returns None when a multi-user install runs on the
    default encryption key, which keeps the legacy per-tool secret.
    """
    from docsgpt.connectors import catalog, service

    base = catalog.base_url(config.get("server_url"))
    if not base:
        return None
    if auth_type == "oauth":
        with db_readonly() as conn:
            row = service._mcp_row(conn, user, base, None)
        return str(row["id"]) if row else None
    definition = catalog.get_definition("custom_mcp")
    host = base.split("://")[-1]
    try:
        with db_session() as conn:
            if auth_credentials:
                row, _ = service.create_api_key_connection(
                    conn, user, definition, auth_credentials, server_url=base, display_name=display_name,
                )
            else:
                repo = ConnectorSessionsRepository(conn)
                row = repo.find_account(user, "custom_mcp", server_url=base, account_label=host) or repo.create(
                    user, "custom_mcp", connector_key="custom_mcp", auth_kind="none",
                    display_name=display_name, account_label=host, server_url=base,
                )
    except service.EncryptionKeyNotConfigured:
        return None
    return str(row["id"]) if row else None


def _previous_connection(existing_doc, config, owner_id) -> str | None:
    """The saved tool's connection, kept only while the server is unchanged.

    An edit that cannot resolve a connection of its own (the default
    encryption key blocks storing a new secret) must not carry the old
    one over to a different server (its key would be sent there), to a
    connection the tool's owner does not own, or to one that signs in
    another way.
    """
    from docsgpt.connectors import catalog

    connection_id = (existing_doc or {}).get("connection_id")
    base = catalog.base_url(config.get("server_url"))
    if not connection_id or not base:
        return None
    with db_readonly() as conn:
        row = ConnectorSessionsRepository(conn).get_for_user(str(connection_id), owner_id)
    if row is None or catalog.base_url(row.get("server_url")) != base:
        return None
    wanted = {"oauth": "mcp_oauth", "none": "none"}.get(config.get("auth_type") or "none", "api_key")
    if (row.get("auth_kind") or "") != wanted:
        return None
    return str(connection_id)


def _mcp_policy_error(config: dict):
    """A 403 when an admin turned this MCP server's connector off, else None.

    A preset's own switch applies to its server; any other server is a
    custom connector and needs "Allow custom MCP servers".
    """
    from docsgpt.connectors import catalog, service

    preset = catalog.preset_for_url(config.get("server_url"))
    key = preset.key if preset else "custom_mcp"
    try:
        with db_readonly() as conn:
            service.ensure_connector_allowed(conn, key)
    except service.ConnectorDisabled:
        return make_response(
            jsonify({"success": False, "error": "This MCP server is turned off by an admin", "code": "disabled"}),
            403,
        )
    except Exception:
        # Fail closed: a server whose admin switch cannot be read is not contacted.
        current_app.logger.warning("Could not read connector policies", exc_info=True)
        return make_response(
            jsonify({"success": False, "error": "Could not check whether this MCP server is allowed"}),
            503,
        )
    return None


def _stored_mcp_credentials(existing_doc: dict, owner_id: str) -> dict:
    """The secrets a saved MCP tool authenticates with, for reuse on an edit.

    A legacy tool keeps them encrypted in its config; a connection-backed one
    on its key-based connection, read only while that connection is the
    owner's and was stored for the tool's own server.

    Args:
        existing_doc: The stored ``user_tools`` row.
        owner_id: The tool's owner.

    Returns:
        The stored credentials, or ``{}`` when there are none to reuse.
    """
    from docsgpt.connectors import catalog, service

    existing_config = existing_doc.get("config") or {}
    if existing_config.get("encrypted_credentials"):
        return decrypt_credentials(existing_config["encrypted_credentials"], owner_id)
    connection_id = existing_doc.get("connection_id")
    if not connection_id:
        return {}
    with db_readonly() as conn:
        row = ConnectorSessionsRepository(conn).get_for_user(str(connection_id), owner_id)
    if (
        row is None
        or (row.get("auth_kind") or "") != "api_key"
        or catalog.base_url(row.get("server_url")) != catalog.base_url(existing_config.get("server_url"))
    ):
        return {}
    try:
        return service.get_credentials(row)
    except service.ConnectionUnavailable:
        return {}


def _existing_mcp_context(tool_id, user, config):
    """Resolve the stored MCP tool a test/save refers to, and its credentials.

    With no ``tool_id`` the caller acts on their own new server. With one,
    the caller needs ``edit_credentials`` on that tool and everything runs as
    its owner. Stored secrets are write-only, so an empty secret field reuses
    the stored one (on the tool, or on its key-based connection) while the
    origin (scheme, host, port) is unchanged; a new origin never inherits them.
    A server that is or would become OAuth is the owner's alone (its tokens
    are the owner's sign-in).

    Returns:
        ``(existing_doc, owner_id, is_owner, moved, credentials)``, or a Flask
        response (404 / 400) to return as is.

    Raises:
        AccessDenied: the caller can't see the tool (404), can't change its
            credentials (403), or isn't the owner of an OAuth server (403).
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
    check_oauth_mcp_owner_only(ra, existing_config, config)
    moved = _mcp_origin_changed(config, existing_config)
    auth_type = config.get("auth_type", "none")
    new_secret_keys = set(auth_credentials) - {"api_key_header"}
    if moved and auth_type in _MCP_CREDENTIAL_AUTH_TYPES and not new_secret_keys:
        return make_response(
            jsonify({"success": False, "message": _CREDENTIALS_FOR_NEW_SERVER}), 400
        )
    credentials = dict(auth_credentials)
    stored = {} if moved else _stored_mcp_credentials(existing_doc, ra.owner_id)
    if stored:
        credentials = {**stored, **auth_credentials}
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
            policy_error = _mcp_policy_error(config)
            if policy_error is not None:
                return policy_error

            ctx = _existing_mcp_context(data.get("id"), user, config)
            if not isinstance(ctx, tuple):
                return ctx
            _existing_doc, owner_id, _is_owner, _moved, auth_credentials = ctx
            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(config=test_config, user_id=owner_id)
            result = mcp_tool.test_connection()

            if result.get("requires_oauth"):
                safe_result = {
                    k: v
                    for k, v in result.items()
                    if k in ("success", "requires_oauth", "auth_url", "task_id")
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
        except InvalidServerUrl as e:
            current_app.logger.warning(f"Invalid MCP server test request: {e}")
            return _invalid_server_url_response(e)
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
            policy_error = _mcp_policy_error(config)
            if policy_error is not None:
                return policy_error

            # An existing id is always an update of THAT row, written as its
            # owner; it never falls through to creating a copy for the caller.
            ctx = _existing_mcp_context(data.get("id"), user, config)
            if not isinstance(ctx, tuple):
                return ctx
            existing_doc, owner_id, is_owner, _moved, merged_credentials = ctx
            auth_type = config.get("auth_type", "none")
            mcp_config = config.copy()
            mcp_config["auth_credentials"] = merged_credentials

            if auth_type == "oauth" and not config.get("oauth_task_id"):
                # Only the owner reaches here for an existing server (see
                # ``_existing_mcp_context``). No new handshake: they signed in
                # to this server before, so its stored tokens answer the
                # discovery, and the save below still needs that connection.
                try:
                    mcp_tool = MCPTool(config=mcp_config, user_id=owner_id)
                    mcp_tool.discover_tools()
                    actions_metadata = mcp_tool.get_actions_metadata()
                except Exception:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "error": "Connection not authorized. Please complete the OAuth authorization first.",
                            }
                        ),
                        400,
                    )
            elif auth_type == "oauth":
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
            from docsgpt.connectors.permissions import apply_default_permissions

            transformed_actions = apply_default_permissions(
                "mcp_tool", transform_actions(actions_metadata),
            )

            display_name = data["displayName"]
            # The connection is the owner's: an editor's save stores the
            # secret on the owner's account, as the tool runs as its owner.
            connection_id = _mcp_connection(
                owner_id, storage_config, auth_type, merged_credentials, display_name,
            ) or _previous_connection(existing_doc, storage_config, owner_id)
            if auth_type == "oauth" and not connection_id:
                # A sign-in server's tokens live on its connection. Without one
                # (it was removed, and a client cached before that answered the
                # discovery) the tool would be saved unconnected.
                return make_response(
                    jsonify({
                        "success": False,
                        "error": "Not signed in to this server. Sign in again to connect it.",
                    }),
                    400,
                )
            if connection_id and auth_type != "oauth":
                # The secret lives on the connection only.
                storage_config.pop("encrypted_credentials", None)
            description = f"MCP Server: {storage_config.get('server_url', 'Unknown')}"
            status_bool = bool(data.get("status", True))
            fields_out = {
                "display_name": display_name,
                "custom_name": display_name,
                "description": description,
                "config": storage_config,
                "connection_id": connection_id,
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
                    # Fixed values the owner set survive a re-save.
                    fields_out["actions"] = carry_pins_between(existing_doc.get("actions"), transformed_actions)
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
                        fields_out["actions"] = carry_pins_between(
                            existing_by_name.get("actions"), transformed_actions,
                        )
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
                            connection_id=connection_id,
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
        except InvalidServerUrl as e:
            current_app.logger.warning(f"Invalid MCP server save request: {e}")
            return _invalid_server_url_response(e)
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
            success = manager.handle_oauth_callback(state, code, error, iss=request.args.get("iss"))
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

                from docsgpt.connectors import service

                # Read from connection status alone: status checks never
                # decrypt credentials.
                statuses: dict = {}
                for tool in mcp_tools:
                    tool_id = str(tool["id"])
                    config = tool.get("config") or {}
                    auth_type = config.get("auth_type", "none")
                    row = None
                    if tool.get("connection_id"):
                        row = sessions_repo.get(str(tool["connection_id"]))
                    elif auth_type == "oauth" and config.get("server_url"):
                        parsed = urlparse(config["server_url"])
                        # A team-shared server signs in as its owner.
                        row = sessions_repo.get_by_user_provider(
                            tool.get("user_id") or user,
                            service.mcp_provider(f"{parsed.scheme}://{parsed.netloc}"),
                        )
                    if row is not None:
                        connected = service.normalize_status(row) == service.STATUS_CONNECTED
                        if auth_type == "oauth" or not connected:
                            statuses[tool_id] = "connected" if connected else "needs_auth"
                        else:
                            statuses[tool_id] = "configured"
                    elif auth_type == "oauth":
                        statuses[tool_id] = "needs_auth"
                    else:
                        statuses[tool_id] = "configured"

            return make_response(jsonify({"success": True, "statuses": statuses}), 200)
        except Exception as e:
            current_app.logger.error(
                "Error checking MCP auth status: %s", e, exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": "Failed to check auth status"}),
                500,
            )
