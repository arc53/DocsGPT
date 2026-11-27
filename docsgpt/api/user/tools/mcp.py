"""Tool management MCP server integration."""

from typing import NamedTuple, Optional
from urllib.parse import urlencode, urlparse

from flask import current_app, jsonify, make_response, redirect, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import Connection

from docsgpt.agents.tool_pins import carry_pins_between
from docsgpt.agents.tools.mcp_tool import MCPOAuthManager, MCPTool
from docsgpt.api import api
from docsgpt.api.user.folders.service import FolderError, filing_folder, filing_owner
from docsgpt.api.user.resource_access import AccessDenied, require
from docsgpt.api.user.tasks import mcp_oauth_task
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.api.user.tools.routes import (
    _CREDENTIALS_FOR_NEW_SERVER,
    _MCP_CREDENTIAL_AUTH_TYPES,
    _mcp_origin_changed,
    _STORED_SECRETS_UNREADABLE,
    check_oauth_mcp_owner_only,
    CODE_OAUTH_PERSONAL_ONLY,
    create_workspace,
    denied_response,
    personal_only_response,
    StoredCredentialsUnreadable,
    transform_actions,
)
from docsgpt.cache import get_redis_instance
from docsgpt.connectors.resolve import is_connectionless_member, own_connection, REMOVED_CONNECTION_KEY
from docsgpt.connectors.team import (
    ACCOUNT_ALREADY_CONNECTED,
    authorize_connection,
    CONNECTION_NOT_FOUND,
    ConnectionAccess,
    ConnectionDenied,
    creation_owner,
)
from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.guardrails import tool_descriptions
from docsgpt.security.encryption import (
    CredentialDecryptionError,
    encrypt_tool_credentials,
    load_tool_credentials,
)
from docsgpt.storage.db.repositories.connector_sessions import (
    ConnectorSessionsRepository,
)
from docsgpt.storage.db.repositories.folders import FolderItemsRepository
from docsgpt.storage.db.repositories.user_tool_preferences import UserToolPreferencesRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import check_required_fields
from docsgpt.workspaces.context import current_workspace, WorkspaceError
from docsgpt.workspaces.principal import is_principal_id

tools_mcp_ns = Namespace("tools", description="Tool management operations", path="/api")

_ALLOWED_TRANSPORTS = {"auto", "sse", "http"}
# Set by a team's sign-in on the task's config, never by a client.
_TEAM_SIGN_IN_KEYS = ("oauth_connected_by", "oauth_previous_connected_by")


def _sanitize_mcp_transport(config):
    """Normalise and validate the transport_type field.

    Strips ``command`` / ``args`` keys that are only valid for local STDIO
    transports, ``connection_id``, which only the tool executor sets
    (it picks whose MCP tokens the tool uses), who signed in for a team,
    which only a team's sign-in sets, and the note that a
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
    for key in _TEAM_SIGN_IN_KEYS:
        config.pop(key, None)
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


def _url_parameters_error(config: dict):
    """A 400 when the URL is at a preset's server and lacks a parameter the preset needs, else None.

    Supabase's preset needs a project ref, so no connection reaches every
    project the account can see; see :func:`catalog.check_url_parameters`.
    """
    from docsgpt.connectors import catalog

    try:
        catalog.check_url_parameters((config.get("server_url") or "").strip())
    except catalog.UrlParametersRequired as exc:
        return make_response(
            jsonify({"success": False, "error": str(exc), "message": str(exc), "code": "url_parameters"}), 400,
        )
    return None


def _mcp_connection_revision(user: str, config: dict, auth_type: str) -> dict | None:
    """Capture the no-auth connection revision before remote discovery.

    A connection can be disconnected while discovery is in flight. The save
    transaction uses this revision to avoid overwriting that newer action.
    """
    if auth_type != "none":
        return None
    from docsgpt.connectors import catalog

    base = catalog.base_url(config.get("server_url"))
    if not base:
        return None
    host = base.split("://")[-1]
    with db_readonly() as conn:
        row = ConnectorSessionsRepository(conn).find_account(
            user,
            "custom_mcp",
            server_url=base,
            account_label=host,
        )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "status": row.get("status"),
        "updated_at": row["updated_at"],
    }


def _mcp_connection(
    conn: Connection,
    user: str,
    config: dict,
    auth_type: str,
    auth_credentials: dict,
    display_name: str,
    no_auth_revision: dict | None = None,
) -> str | None:
    """The connection an MCP tool runs with; created on first save.

    OAuth servers already have one (the sign-in stored its tokens there).
    Key, bearer and basic auth store their secret on a connection; servers
    with no auth get a credential-less connection so they still appear on
    the Connectors page. Saving restores an existing no-auth connection
    after successful discovery, unless its captured revision changed while
    discovery was running. The caller owns the transaction so connection
    recovery and tool persistence commit or roll back together. Returns None
    when a multi-user install runs on the default encryption key, which keeps
    the legacy per-tool secret.
    """
    from docsgpt.connectors import catalog, service

    base = catalog.base_url(config.get("server_url"))
    if not base:
        return None
    if auth_type == "oauth":
        row = service._mcp_row(conn, user, base, None)
        return str(row["id"]) if row else None
    definition = catalog.get_definition("custom_mcp")
    host = base.split("://")[-1]
    try:
        if auth_credentials:
            row, _ = service.create_api_key_connection(
                conn, user, definition, auth_credentials, server_url=base, display_name=display_name,
            )
        else:
            repo = ConnectorSessionsRepository(conn)
            row = repo.find_account(user, "custom_mcp", server_url=base, account_label=host)
            if row is None:
                row = repo.create(
                    user, "custom_mcp", connector_key="custom_mcp", auth_kind="none",
                    display_name=display_name, account_label=host, server_url=base,
                )
            elif (
                no_auth_revision
                and str(row["id"]) == str(no_auth_revision["id"])
                and no_auth_revision.get("status") != service.STATUS_CONNECTED
            ):
                repo.update_if_revision(
                    str(row["id"]),
                    no_auth_revision["updated_at"],
                    {"status": service.STATUS_CONNECTED, "last_error": None},
                )
    except service.EncryptionKeyNotConfigured:
        return None
    return str(row["id"]) if row else None


def _previous_connection(
    conn: Connection,
    existing_doc: dict | None,
    config: dict,
    owner_id: str,
) -> str | None:
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


_MCP_REQUIRED_CREDENTIALS = {
    "api_key": ("api_key",),
    "bearer": ("bearer_token",),
    "basic": ("username", "password"),
}


def _stored_mcp_credentials(existing_doc: dict, owner_id: str) -> tuple[dict, bool]:
    """The secrets a saved MCP tool authenticates with, for reuse on an edit.

    A legacy tool keeps them encrypted in its config; a connection-backed one
    on its key-based connection, read only while that connection is the
    owner's and was stored for the tool's own server.

    Args:
        existing_doc: The stored ``user_tools`` row.
        owner_id: The tool's owner.

    Returns:
        ``(credentials, unreadable)``.  ``unreadable`` reports a stored blob no
        available key opens, so a save that would keep a value from it can be
        refused while a complete re-entry still replaces it.
    """
    from docsgpt.connectors import catalog, service

    existing_config = existing_doc.get("config") or {}
    if existing_config.get("encrypted_credentials"):
        try:
            return load_tool_credentials(existing_config["encrypted_credentials"], owner_id), False
        except CredentialDecryptionError:
            return {}, True
    connection_id = existing_doc.get("connection_id")
    if not connection_id:
        return {}, False
    with db_readonly() as conn:
        row = ConnectorSessionsRepository(conn).get_for_user(str(connection_id), owner_id)
    if (
        row is None
        or (row.get("auth_kind") or "") != "api_key"
        or catalog.base_url(row.get("server_url")) != catalog.base_url(existing_config.get("server_url"))
    ):
        return {}, False
    try:
        return service.get_credentials(row), False
    except service.ConnectionUnavailable:
        return {}, False


def _existing_mcp_context(tool_id, user, config):
    """Resolve the stored MCP tool a test/save refers to, and its credentials.

    With no ``tool_id`` the caller acts on a new server in the request's
    workspace: their own in Personal, the team's (owned by its principal) in a
    team, where they need Editor and can't add a server they sign in to (a
    team has no connections in v1). With one, the caller needs
    ``edit_credentials`` on that tool and everything runs as its owner.
    Stored secrets are write-only, so an empty secret field reuses the stored one (on the tool, or on its key-based connection) while the
    origin (scheme, host, port) is unchanged; a new origin never inherits them.
    A server that is or would become OAuth is the owner's alone (its tokens
    are the owner's sign-in).

    Returns:
        ``(existing_doc, owner_id, is_owner, moved, credentials)``, or a Flask
        response (404 / 400 / 403) to return as is.

    Raises:
        AccessDenied: the caller can't see the tool (404), can't change its
            credentials (403), or isn't the owner of an OAuth server (403).
        StoredCredentialsUnreadable: the stored blob cannot be opened and the
            save would have to keep a secret from it.
        WorkspaceError: a new server in a team the caller isn't in (404) or is
            only a Viewer of (403).
    """
    auth_credentials = _extract_auth_credentials(config)
    if not tool_id:
        with db_readonly() as conn:
            workspace = create_workspace(conn)
        if workspace.is_team and (config.get("auth_type") or "none") == "oauth":
            return personal_only_response(CODE_OAUTH_PERSONAL_ONLY)
        owner_id, _created_by = workspace.owner_for_create(user)
        return None, owner_id, True, False, auth_credentials
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
    stored, unreadable = ({}, False) if moved else _stored_mcp_credentials(existing_doc, ra.owner_id)
    if unreadable and auth_type in _MCP_CREDENTIAL_AUTH_TYPES:
        missing = [key for key in _MCP_REQUIRED_CREDENTIALS[auth_type] if not credentials.get(key)]
        if missing:
            raise StoredCredentialsUnreadable(_STORED_SECRETS_UNREADABLE)
    if stored:
        credentials = {**stored, **auth_credentials}
    return existing_doc, ra.owner_id, ra.access == "owner", moved, credentials


def _mcp_filing(data: dict, user: str, owner_id: str):
    """Where a save asks to file its MCP server, checked before the server is contacted.

    A new server is filed in the tree it lands in (the caller's own, or the
    team's); an existing one by the tool's own rule: a team's server in the
    team's tree, anyone else's in the caller's own, and only by someone who
    may move it between folders.

    Args:
        data: The request body; only a present ``folder_id`` files (``null`` unfiles an existing server).
        user: The caller.
        owner_id: The server's owner (the new server's, or the stored one's).

    Returns:
        ``(tree_owner, folder_id)``, or None when the body names no folder.

    Raises:
        FolderError: 404 ``folder_not_found`` when the folder isn't in that tree.
        AccessDenied: the caller may not move the existing server between folders.
    """
    if "folder_id" not in data:
        return None
    with db_readonly() as conn:
        if not data.get("id"):
            return owner_id, filing_folder(conn, owner_id, data["folder_id"])
        tree_owner = filing_owner(require(conn, "tool", data["id"], user, "move_folder"), user)
        return tree_owner, filing_folder(conn, tree_owner, data["folder_id"])


class TeamSignIn(NamedTuple):
    """A sign-in to an MCP server for the team the workspace header names.

    Attributes:
        owner_id: The team's principal: it owns the connection and its tokens.
        access: The Admin's access to the connection being reconnected, or None for a new one.
    """

    owner_id: str
    access: Optional[ConnectionAccess]

    @property
    def connection_id(self) -> Optional[str]:
        """The connection being reconnected, if any."""
        return str(self.access.row["id"]) if self.access is not None else None


def _team_sign_in(data: dict, user: str, config: dict):
    """Whether a test/save signs in to a server for the team, checked.

    Only a new sign-in server asks for it (``owner=team``, no stored
    ``id``); an Admin of the header's team signs in, and ``connection_id``
    names the team's connection to that server being reconnected.

    Args:
        data: The request body.
        user: The caller.
        config: The sanitised MCP config.

    Returns:
        A :class:`TeamSignIn`, None for anything else, or a 400 response
        when ``connection_id`` signs in to another server.

    Raises:
        WorkspaceError: 400 ``invalid_owner`` / ``team_workspace_required``,
            404 outside the team, 403 ``workspace_role_required`` below Admin.
        ConnectionDenied: 404 ``connection_not_found`` (not this team's
            connection), 403 ``connection_admin_required``.
    """
    from docsgpt.connectors import catalog, service

    if data.get("id") or (config.get("auth_type") or "none") != "oauth" or not data.get("owner"):
        return None
    with db_readonly() as conn:
        owner_id, connected_by = creation_owner(conn, user, data.get("owner"))
        if connected_by is None:
            return None
        connection_id = data.get("connection_id")
        if not connection_id:
            return TeamSignIn(owner_id, None)
        access = authorize_connection(conn, str(connection_id), user, "manage")
    if not access.is_team or access.owner_id != owner_id:
        raise ConnectionDenied(404, CONNECTION_NOT_FOUND, "Connection not found")
    if access.row.get("provider") != service.mcp_provider(catalog.base_url(config.get("server_url"))):
        message = "This connection signs in to another server"
        return make_response(jsonify({"success": False, "error": message, "message": message}), 400)
    return TeamSignIn(owner_id, access)


def _start_team_sign_in(config: dict, user: str, team: TeamSignIn):
    """Start a fresh sign-in for the team, followed by ``user`` alone.

    A stored sign-in never answers it: reconnecting means signing in again.
    A new one is refused (409 ``account_already_connected``) while the team
    holds a sign-in for that server; it is reconnected instead.

    Args:
        config: The sanitised MCP config.
        user: The Admin signing in.
        team: The checked :class:`TeamSignIn`.

    Returns:
        The Flask response: ``{success: false, requires_oauth: true, task_id}``.
    """
    from docsgpt.connectors import catalog, service

    task_config = config.copy()
    if team.access is None:
        with db_readonly() as conn:
            existing = ConnectorSessionsRepository(conn).get_by_user_provider(
                team.owner_id, service.mcp_provider(catalog.base_url(config.get("server_url"))),
            )
        if existing is not None and service.has_credentials(existing):
            return make_response(jsonify({
                "success": False, "error": ACCOUNT_ALREADY_CONNECTED, "connection_id": str(existing["id"]),
                "message": "The team is already signed in to this server. Reconnect it instead.",
            }), 409)
    else:
        task_config["connection_id"] = team.connection_id
        task_config["oauth_previous_connected_by"] = team.access.connected_by
    task_id = mcp_oauth_task.delay(task_config, team.owner_id, user).id
    # Only the Admin who started it cancels it, and its events are theirs.
    MCPOAuthManager(get_redis_instance()).register_task(task_id, user)
    return make_response(jsonify({"success": False, "requires_oauth": True, "task_id": task_id}), 200)


def _team_signed_in_connection(conn: Connection, team: TeamSignIn, user: str, config: dict, result: dict):
    """The team's connection a finished sign-in wrote, when it is the one ``user`` signed in to.

    Args:
        conn: Open connection.
        team: The checked :class:`TeamSignIn`.
        user: The Admin saving.
        config: The MCP config being saved.
        result: The sign-in's ``completed`` status, read from ``user``'s stream.

    Returns:
        The ``connector_sessions`` row, or None.
    """
    from docsgpt.connectors import catalog, service

    connection_id = result.get("connection_id")
    if not connection_id or (team.connection_id and str(connection_id) != team.connection_id):
        return None
    row = ConnectorSessionsRepository(conn).get(str(connection_id))
    if (
        row is None
        or row.get("user_id") != team.owner_id
        or row.get("connected_by") != user
        or row.get("provider") != service.mcp_provider(catalog.base_url(config.get("server_url")))
    ):
        return None
    return row


def _audit_team_sign_in(conn: Connection, user: str, team: TeamSignIn, row: dict, result: dict) -> None:
    """Record a team's new or reconnected MCP sign-in on the team's audit trail."""
    from docsgpt.api.connector.connections import audit_team_connection

    if team.access is None:
        audit_team_connection(
            conn, user, "team.connection_added", row,
            connector_key=row.get("connector_key"), account_label=row.get("account_label"),
        )
        return
    previous = result.get("previous_connected_by")
    audit_team_connection(
        conn, user, "team.connection_reconnected", row, replaced=previous != user, previous_connected_by=previous,
    )


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
                "owner": fields.String(
                    required=False,
                    description="team: sign in to a new sign-in server for the team the workspace header names "
                    "(Admins); the sign-in's events, cancel and status are the caller's",
                ),
                "connection_id": fields.String(
                    required=False, description="With owner=team: the team's connection to this server to reconnect",
                ),
            },
        )
    )
    @api.doc(
        description=(
            "Test MCP server connection with provided configuration. With owner=team on a sign-in server "
            "(Admins of the header's team), always starts a fresh sign-in for the team: "
            "{requires_oauth, task_id}; 409 account_already_connected {connection_id} when the team is "
            "already signed in to that server (reconnect it with connection_id instead)."
        )
    )
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
            parameters_error = _url_parameters_error(config)
            if parameters_error is not None:
                return parameters_error
            policy_error = _mcp_policy_error(config)
            if policy_error is not None:
                return policy_error

            team = _team_sign_in(data, user, config)
            if isinstance(team, TeamSignIn):
                return _start_team_sign_in(config, user, team)
            if team is not None:
                return team
            ctx = _existing_mcp_context(data.get("id"), user, config)
            if not isinstance(ctx, tuple):
                return ctx
            _existing_doc, owner_id, _is_owner, _moved, auth_credentials = ctx
            test_config = config.copy()
            test_config["auth_credentials"] = auth_credentials

            mcp_tool = MCPTool(config=test_config, user_id=owner_id)
            result = mcp_tool.test_connection()

            if result.get("requires_oauth"):
                # The caller may cancel this sign-in; nobody else can.
                MCPOAuthManager(get_redis_instance()).register_task(result.get("task_id"), user)
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
        except (WorkspaceError, ConnectionDenied) as e:
            return e.response()
        except StoredCredentialsUnreadable as e:
            return make_response(jsonify({"success": False, "error": str(e), "message": str(e)}), 400)
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
                "folder_id": fields.String(
                    required=False,
                    description="Folder to file the server in: the workspace's tree for a new server, the "
                    "tool's own tree for an existing one; null unfiles an existing server",
                ),
                "owner": fields.String(
                    required=False,
                    description="team: save a sign-in server on the team's connection the caller just signed in "
                    "to (config.oauth_task_id from /mcp_server/test with owner=team; Admins)",
                ),
                "connection_id": fields.String(
                    required=False, description="With owner=team: the team's connection that was reconnected",
                ),
            },
        )
    )
    @api.doc(
        description=(
            "Create or update MCP server with automatic tool discovery. While Admin > Guardrails warns on tool "
            "descriptions, each discovered action is scored for prompt injection and stored with "
            "`injection: {p, scorer}`; the response's `injection` is `{flagged: [names], unscored: [names]}` "
            "(null while the warnings are off). Nothing is deactivated. The response's `connection_id` is the "
            "connection the server runs on. With owner=team, the tool is the team's, on the team connection "
            "the caller's finished sign-in wrote; signing in again updates that tool."
        )
    )
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
            parameters_error = _url_parameters_error(config)
            if parameters_error is not None:
                return parameters_error
            policy_error = _mcp_policy_error(config)
            if policy_error is not None:
                return policy_error

            team = _team_sign_in(data, user, config)
            if team is not None and not isinstance(team, TeamSignIn):
                return team
            if team is not None:
                # A sign-in server for the team: the tool runs on the team's
                # connection its Admin just signed in to.
                existing_doc, owner_id, is_owner, merged_credentials = None, team.owner_id, True, {}
            else:
                # An existing id is always an update of THAT row, written as its
                # owner; it never falls through to creating a copy for the caller.
                ctx = _existing_mcp_context(data.get("id"), user, config)
                if not isinstance(ctx, tuple):
                    return ctx
                existing_doc, owner_id, is_owner, _moved, merged_credentials = ctx
            filing = _mcp_filing(data, user, owner_id)
            # A team's server (owned by its principal) keeps a key-based secret on
            # the tool, sealed under the principal; a sign-in server is on a team connection.
            team_owned = is_principal_id(owner_id)
            auth_type = config.get("auth_type", "none")
            mcp_config = config.copy()
            mcp_config["auth_credentials"] = merged_credentials
            connection_revision = None if team_owned else _mcp_connection_revision(owner_id, config, auth_type)
            oauth_result: dict = {}

            if team is not None and not config.get("oauth_task_id"):
                return make_response(
                    jsonify({"success": False, "error": "Sign in to this server for the team first."}), 400,
                )
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
                # Read from the caller's own stream: a sign-in someone else started is not theirs to save.
                result = manager.get_oauth_status(
                    config["oauth_task_id"], user
                )
                oauth_result = result
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
                storage_config["encrypted_credentials"] = encrypt_tool_credentials(
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
            from docsgpt.connectors import catalog, service
            from docsgpt.connectors.permissions import apply_default_permissions

            # Scored as read, so a re-save of an unchanged server is a cache hit; warn only.
            description_scan = tool_descriptions.score_actions(actions_metadata)
            # A preset with more tools than a model takes at once starts with its core ones on.
            preset = catalog.preset_for_url(storage_config.get("server_url"))
            transformed_actions = apply_default_permissions(
                "mcp_tool", transform_actions(actions_metadata), preset.default_actions if preset else (),
            )

            display_name = data["displayName"]
            description = f"MCP Server: {storage_config.get('server_url', 'Unknown')}"
            status_bool = bool(data.get("status", True))
            updated_message = (
                f"MCP server updated successfully! Discovered {len(transformed_actions)} tools."
            )

            with db_session() as conn:
                # The connection is the owner's: an editor's save stores the
                # secret on the owner's account, as the tool runs as its owner.
                # Connection recovery and tool persistence share this transaction.
                team_row = None
                if team is not None:
                    team_row = _team_signed_in_connection(conn, team, user, storage_config, oauth_result)
                    connection_id = str(team_row["id"]) if team_row is not None else None
                else:
                    connection_id = None if team_owned else (_mcp_connection(
                        conn,
                        owner_id,
                        storage_config,
                        auth_type,
                        merged_credentials,
                        display_name,
                        connection_revision,
                    ) or _previous_connection(conn, existing_doc, storage_config, owner_id))
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
                # A preset's tool rebuilt from its connection gets the same project back.
                service.remember_url_parameters(conn, connection_id, storage_config.get("server_url"))
                fields_out = {
                    "display_name": display_name,
                    "custom_name": display_name,
                    "description": description,
                    "config": storage_config,
                    "connection_id": connection_id,
                }
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
                    if not team_owned:
                        # A team server's ``status`` stays off: each member switches it
                        # into their own chats (the creator's choice is set below).
                        fields_out["status"] = status_bool
                    if team is not None:
                        # Signing in to the team's server again updates its tool.
                        existing_by_name = next((
                            t for t in repo.list_for_user(owner_id)
                            if t.get("name") == "mcp_tool" and str(t.get("connection_id") or "") == connection_id
                        ), None)
                    elif team_owned:
                        # A new server in a team is added, never matched by its address: the team's tool
                        # there may run on an Admin's sign-in, which a member's save must not take over.
                        existing_by_name = None
                    else:
                        # Fall back to find_by_user_and_name — the original
                        # dual-write path also ran an existence check before
                        # deciding between insert and update.
                        existing_by_name = repo.find_by_user_and_name(owner_id, "mcp_tool")
                    if existing_by_name and (
                        team is not None
                        or (existing_by_name.get("config") or {}).get("server_url")
                        == storage_config.get("server_url")
                    ):
                        fields_out["actions"] = carry_pins_between(
                            existing_by_name.get("actions"), transformed_actions,
                        )
                        repo.update(str(existing_by_name["id"]), owner_id, fields_out)
                        saved_id = str(existing_by_name["id"])
                        response_data = {
                            "success": True,
                            "id": saved_id,
                            "message": updated_message,
                            "tools_count": len(transformed_actions),
                        }
                    else:
                        created = repo.create(
                            owner_id, "mcp_tool",
                            config=storage_config,
                            custom_name=display_name,
                            display_name=display_name,
                            description=description,
                            config_requirements={},
                            actions=transformed_actions,
                            status=status_bool and not team_owned,
                            connection_id=connection_id,
                            created_by=user,
                        )
                        saved_id = str(created["id"])
                        response_data = {
                            "success": True,
                            "id": saved_id,
                            "message": f"MCP server created successfully! Discovered {len(transformed_actions)} tools.",
                            "tools_count": len(transformed_actions),
                        }
                    if team_owned and status_bool:
                        UserToolPreferencesRepository(conn).set_in_chat(user, saved_id, True)
                if filing is not None and (existing_doc is not None or filing[1]):
                    FolderItemsRepository(conn).file(filing[0], "tool", saved_id, filing[1])
                if team_row is not None:
                    _audit_team_sign_in(conn, user, team, team_row, oauth_result)
            response_data["injection"] = description_scan
            response_data["connection_id"] = connection_id
            return make_response(jsonify(response_data), 200)
        except AccessDenied as e:
            return denied_response(e)
        except (WorkspaceError, ConnectionDenied) as e:
            return e.response()
        except FolderError as e:
            return e.response()
        except StoredCredentialsUnreadable as e:
            return make_response(jsonify({"success": False, "error": str(e), "message": str(e)}), 400)
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


@tools_mcp_ns.route("/mcp_server/oauth_cancel")
class MCPOAuthCancel(Resource):
    @api.expect(
        api.model(
            "MCPOAuthCancelModel",
            {"task_id": fields.String(required=True, description="OAuth task to cancel")},
        )
    )
    @api.doc(
        description="Cancel an MCP OAuth sign-in the caller started, so the worker stops waiting for its callback"
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json(silent=True) or {}
        missing_fields = check_required_fields(data, ["task_id"])
        if missing_fields:
            return missing_fields
        try:
            cancelled = MCPOAuthManager(get_redis_instance()).cancel(str(data["task_id"]), user)
        except Exception as e:
            current_app.logger.error(f"Error cancelling MCP OAuth: {e}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to cancel sign-in"}), 500)
        if not cancelled:
            return make_response(jsonify({"success": False, "error": "Sign-in not found"}), 404)
        return make_response(jsonify({"success": True}), 200)


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
                workspace = current_workspace(conn)
                tools_repo = UserToolsRepository(conn)
                sessions_repo = ConnectorSessionsRepository(conn)
                if workspace.is_team:
                    # The team's servers, the same list its Tools page shows.
                    all_tools = tools_repo.list_for_user(workspace.owner_id)
                else:
                    all_tools = tools_repo.list_for_user(user)
                    owned_ids = {str(t["id"]) for t in all_tools}
                    # Team-shared MCP servers the caller can see run with the
                    # owner's connection, so their status is the owner's.
                    shared_ids = [
                        tid for tid in visible_with_access(conn, user, "tool") if tid not in owned_ids
                    ]
                    all_tools = all_tools + tools_repo.list_by_ids(shared_ids)
                    # A team's server never shows in Personal.
                    all_tools = [t for t in all_tools if not is_principal_id(t.get("user_id"))]
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
                    if is_connectionless_member(tool):
                        # A team's tool on each person's own account: the caller's sign-in, never the team's.
                        row = own_connection(conn, user, tool)
                    elif tool.get("connection_id"):
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
        except WorkspaceError as e:
            return e.response()
        except Exception as e:
            current_app.logger.error(
                "Error checking MCP auth status: %s", e, exc_info=True
            )
            return make_response(
                jsonify({"success": False, "error": "Failed to check auth status"}),
                500,
            )
