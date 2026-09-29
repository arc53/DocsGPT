"""Connectors catalog and connections API.

``/api/connectors/catalog`` lists every service DocsGPT can connect to, with
whether the server is set up for it and the caller's connection summary.
``/api/connections`` lists and manages the caller's connections. Responses
never include tokens or secrets.
"""

from __future__ import annotations

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

import uuid

from docsgpt.api import api
from docsgpt.api.user.authz import ROLE_ADMIN, has_role
from docsgpt.connectors import catalog, service
from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.security.encryption import CredentialDecryptionError

_FREQUENCIES = ("never", "daily", "weekly", "monthly")

connections_ns = Namespace("connections", description="Connectors and connections", path="/api")
api.add_namespace(connections_ns)


def _user_id() -> str | None:
    token = getattr(request, "decoded_token", None)
    return token.get("sub") if isinstance(token, dict) else None


def _unauthorized():
    return make_response(jsonify({"success": False, "error": "Unauthorized"}), 401)


def _not_found():
    return make_response(jsonify({"success": False, "error": "Connection not found"}), 404)


@connections_ns.route("/connectors/catalog")
class ConnectorCatalog(Resource):
    @api.doc(description="Every connector with its availability and the caller's connection summary")
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                entries = service.catalog_for_user(
                    conn, user_id, is_admin=has_role(request.decoded_token, ROLE_ADMIN),
                )
        except Exception as err:
            current_app.logger.error(f"Error building connector catalog: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connectors"}), 500)
        return make_response(jsonify({"success": True, "connectors": entries}), 200)


def _json_body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _owned(conn, connection_id: str, user_id: str):
    return ConnectorSessionsRepository(conn).get_for_user(connection_id, user_id)


def _error(message: str, status: int, **extra):
    return make_response(jsonify({"success": False, "error": message, **extra}), status)


@connections_ns.route("/connections")
class ConnectionsList(Resource):
    @api.doc(
        description=(
            "Create a connection from pasted credentials: "
            "{connector_key, credentials, label?}. Same credentials reuse the same connection."
        )
    )
    def post(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        definition = catalog.get_definition(body.get("connector_key"))
        if definition is None or definition.auth_kind != "api_key":
            return _error("This connector does not take pasted credentials", 400)
        if definition.missing_settings:
            return _error("This connector needs admin setup", 400, code="needs_setup")
        credentials = body.get("credentials")
        if not isinstance(credentials, dict):
            return _error("credentials must be an object", 400)
        label = body.get("label") or None
        if definition.key == "github":
            # Check the token now, not at the first sync, and name the
            # connection after the account rather than a hint of the token.
            from docsgpt.connectors import github

            try:
                label = label or github.token_account(credentials.get("access_token"))
            except github.TokenRejected as err:
                return _error(str(err), 400, code="invalid_credentials")
            except service.TransientConnectionError as err:
                return _error(str(err), 502)
        try:
            with db_session() as conn:
                row, created = service.create_api_key_connection(
                    conn, user_id, definition, credentials, label=label,
                )
        except service.EncryptionKeyNotConfigured as err:
            return _error(str(err), 400, code="encryption_key_default")
        except service.ConnectorDisabled as err:
            return _error(str(err), 403, code="disabled")
        except ValueError as err:
            return _error(str(err), 400)
        except Exception as err:
            current_app.logger.error(f"Error creating connection: {err}", exc_info=True)
            return _error("Failed to create connection", 500)
        return make_response(
            jsonify(
                {
                    "success": True,
                    "created": created,
                    "connection": service.serialize_connection(row),
                    "setup": dict(definition.setup),
                }
            ),
            201 if created else 200,
        )

    @api.doc(description="The caller's connections with status and linked resource counts")
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                connections = service.list_connections(conn, user_id)
        except Exception as err:
            current_app.logger.error(f"Error listing connections: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connections"}), 500)
        return make_response(jsonify({"success": True, "connections": connections}), 200)


@connections_ns.route("/connections/<string:connection_id>")
class ConnectionDetail(Resource):
    @api.doc(description="One connection with the sources it syncs and the tools it provides")
    def get(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_readonly() as conn:
                row = ConnectorSessionsRepository(conn).get_for_user(connection_id, user_id)
                if row is None:
                    return _not_found()
                detail = service.connection_detail(conn, row)
        except Exception as err:
            current_app.logger.error(f"Error loading connection: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to load connection"}), 500)
        return make_response(jsonify({"success": True, "connection": detail}), 200)

    @api.doc(description="Name an account: {name}. An empty name clears it. Owner only.")
    def patch(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        name = _json_body().get("name")
        if not isinstance(name, str) or len(name.strip()) > service.ACCOUNT_NAME_MAX:
            return _error(f"name must be text of at most {service.ACCOUNT_NAME_MAX} characters", 400)
        with db_session() as conn:
            row = _owned(conn, connection_id, user_id)
            if row is None:
                return _not_found()
            connection = service.rename_connection(conn, row, name)
        return make_response(jsonify({"success": True, "connection": connection}), 200)

    @api.doc(
        description=(
            "Remove a connection: {sources: keep | delete, tools: delete | keep}. "
            "Kept sources keep their content and stop syncing."
        )
    )
    def delete(self, connection_id: str):
        from docsgpt.api.user.sources.routes import delete_source

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        sources_mode = body.get("sources", "keep")
        tools_mode = body.get("tools", "delete")
        if sources_mode not in ("keep", "delete") or tools_mode not in ("keep", "delete"):
            return _error("sources and tools must be keep or delete", 400)
        try:
            with db_session() as conn:
                row = _owned(conn, connection_id, user_id)
                if row is None:
                    return _not_found()
                to_delete = service.remove_connection(conn, row, sources=sources_mode, tools=tools_mode)
            failed = [str(doc["id"]) for doc in to_delete if not delete_source(user_id, doc)]
        except Exception as err:
            current_app.logger.error(f"Error removing connection: {err}", exc_info=True)
            return _error("Failed to remove connection", 500)
        return make_response(jsonify({"success": True, "failed_sources": failed}), 200)


@connections_ns.route("/connections/<string:connection_id>/disconnect")
class ConnectionDisconnect(Resource):
    @api.doc(description="Delete a connection's stored credentials; its sources and tools stay")
    def post(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        try:
            with db_session() as conn:
                row = ConnectorSessionsRepository(conn).get_for_user(connection_id, user_id)
                if row is None:
                    return _not_found()
                connection = service.disconnect(conn, row)
        except Exception as err:
            current_app.logger.error(f"Error disconnecting connection: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to disconnect"}), 500)
        return make_response(jsonify({"success": True, "connection": connection}), 200)


@connections_ns.route("/connections/<string:connection_id>/setup")
class ConnectionSetup(Resource):
    @api.doc(
        description=(
            "Apply the connect wizard's choices: {create_tools, tool_permissions?, "
            "sync?: {items, frequency, name?}}. Honours an Idempotency-Key header for the sync."
        )
    )
    def post(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        create_tools = body.get("create_tools", True)
        try:
            mcp_actions = None
            with db_readonly() as conn:
                row = _owned(conn, connection_id, user_id)
                discover = bool(row) and create_tools and service.needs_mcp_discovery(conn, row)
            if row is None:
                return _not_found()
            if service.normalize_status(row) != service.STATUS_CONNECTED:
                return _error("Reconnect before setting up", 409, code="reconnect")
            if discover:
                # GitHub's tool is its MCP server: read its actions before
                # the write transaction, not while holding it open.
                from docsgpt.connectors.mcp import discover_builtin_actions

                try:
                    mcp_actions = discover_builtin_actions(user_id, row)
                except service.ConnectionUnavailable:
                    return _error("Reconnect before setting up", 409, code="reconnect")
                except Exception as err:
                    current_app.logger.warning(f"Could not list the MCP server's tools: {err}")
                    return _error("The service's tools could not be reached. Try again.", 502,
                                  code="tools_unavailable")
            with db_session() as conn:
                row = _owned(conn, connection_id, user_id)
                if row is None:
                    return _not_found()
                tools = []
                if create_tools:
                    tools = service.ensure_connection_tools(
                        conn, user_id, row, permissions=body.get("tool_permissions") or None,
                        mcp_actions=mcp_actions,
                    )
                account_parameters = service.connection_parameters(row)
                tool_payload = [service.serialize_tool(tool, account_parameters) for tool in tools]
            sources = []
            if body.get("sync"):
                started = _start_sync(user_id, row, body["sync"])
                if isinstance(started, tuple):
                    return _error(*started)
                sources.append(started)
        except Exception as err:
            current_app.logger.error(f"Error setting up connection: {err}", exc_info=True)
            return _error("Failed to set up connection", 500)
        return make_response(jsonify({"success": True, "tools": tool_payload, "sources": sources}), 200)


def _start_sync(user_id: str, row: dict, sync: dict):
    """Queue the first ingest of a source synced from ``row``.

    Returns the source summary, or ``(message, status)`` on a bad request.
    """
    from docsgpt.api.user.sources.upload import (
        _claim_task_or_get_cached,
        _derive_source_id,
        _read_idempotency_key,
        _scoped_idempotency_key,
    )
    from docsgpt.api.user.tasks import ingest_connector_task, ingest_remote

    definition = catalog.get_definition(catalog.connector_key_for_row(row))
    if definition is None or not definition.sync_ingestor:
        return ("This connector does not sync content", 400)
    items = sync.get("items") or {}
    if not isinstance(items, dict):
        return ("items must be an object", 400)
    frequency = sync.get("frequency") or definition.default_sync_frequency
    if frequency not in _FREQUENCIES:
        return ("Unknown sync frequency", 400)
    name = (sync.get("name") or "").strip()
    if definition.sync_ingestor == "github":
        from docsgpt.parser.remote.github_loader import GitHubLoader

        repo = GitHubLoader.normalize_repo(str(items.get("repo_url") or ""))
        if not repo:
            return ("Pick a GitHub repository", 400)
        items = {**items, "repo_url": repo}
        name = name or repo
    name = name or definition.name
    # Validate before claiming the idempotency key: a rejected request must
    # leave the key free for the corrected retry.
    if definition.auth_kind == "oauth":
        file_ids = [str(i) for i in items.get("file_ids") or [] if i]
        folder_ids = [str(i) for i in items.get("folder_ids") or [] if i]
        if not file_ids and not folder_ids:
            return ("Pick at least one file or folder", 400)
        task_fn = ingest_connector_task
        kwargs = {
            "job_name": name,
            "user": user_id,
            "source_type": definition.sync_ingestor,
            "connection_id": str(row["id"]),
            "file_ids": file_ids,
            "folder_ids": folder_ids,
            "recursive": bool(items.get("recursive", True)),
            "sync_frequency": frequency,
        }
    else:
        fields = {f.key for f in definition.setup_fields}
        source_data = {k: v for k, v in items.items() if k in fields and v not in (None, "")}
        missing = [f.label for f in definition.setup_fields if f.required and f.key not in source_data]
        if missing:
            return (f"Missing: {', '.join(missing)}", 400)
        task_fn = ingest_remote
        kwargs = {
            "source_data": source_data,
            "job_name": name,
            "user": user_id,
            "loader": definition.sync_ingestor,
            "connection_id": str(row["id"]),
            "sync_frequency": frequency,
        }
    idempotency_key, _ = _read_idempotency_key()
    scoped_key = _scoped_idempotency_key(idempotency_key, user_id)
    task_id = None
    if scoped_key:
        task_id, cached = _claim_task_or_get_cached(scoped_key, "connection_setup_sync")
        if cached is not None:
            return {"id": cached.get("source_id"), "task_id": cached.get("task_id"), "name": name}
    source_id = str(_derive_source_id(scoped_key)) if scoped_key else str(uuid.uuid4())
    options = {"task_id": task_id} if task_id else {}
    task = task_fn.apply_async(
        kwargs={**kwargs, "idempotency_key": scoped_key, "source_id": source_id}, **options,
    )
    return {"id": source_id, "task_id": task_id or task.id, "name": name, "sync_frequency": frequency}


@connections_ns.route("/connections/<string:connection_id>/repositories")
class ConnectionRepositories(Resource):
    @api.doc(
        description=(
            "GitHub: the repositories the connection can read, for the sync picker. "
            "install_url is where a GitHub App sign-in chooses more repositories."
        )
    )
    def get(self, connection_id: str):
        from docsgpt.connectors import github

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        with db_readonly() as conn:
            row = _owned(conn, connection_id, user_id)
        if row is None or catalog.connector_key_for_row(row) != "github":
            return _not_found()
        app_sign_in = (row.get("auth_kind") or "") == "oauth"
        try:
            token = service.access_credentials(row).get("access_token")
            repositories = github.list_repositories(token or "", app=app_sign_in)
        except service.ConnectionUnavailable:
            return _error("Reconnect to continue", 409, code="reconnect")
        except github.TokenRejected as err:
            service.mark_reconnect_needed(connection_id, str(err))
            return _error("Reconnect to continue", 409, code="reconnect")
        except service.TransientConnectionError:
            return _error("GitHub is not responding. Try again.", 503)
        except Exception as err:
            current_app.logger.error(f"Error listing GitHub repositories: {err}", exc_info=True)
            return _error("Failed to list repositories", 502)
        install_url = None
        if app_sign_in:
            from docsgpt.core.settings import settings

            slug = settings.GITHUB_APP_SLUG
            install_url = f"https://github.com/apps/{slug}/installations/new" if slug else None
        return make_response(
            jsonify({"success": True, "repositories": repositories, "install_url": install_url}), 200,
        )


@connections_ns.route("/connections/<string:connection_id>/reconnect")
class ConnectionReconnect(Resource):
    @api.doc(
        description=(
            "OAuth: returns an authorization URL for the same account. "
            "API key: accepts {credentials} and replaces the stored ones."
        )
    )
    def post(self, connection_id: str):
        from docsgpt.api.connector.routes import build_authorization

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        try:
            with db_readonly() as conn:
                row = _owned(conn, connection_id, user_id)
            if row is None:
                return _not_found()
            key = catalog.connector_key_for_row(row)
            definition = catalog.get_definition(key)
            auth_kind = row.get("auth_kind") or (definition.auth_kind if definition else None)
            if auth_kind == "oauth":
                started = build_authorization(row["provider"], user_id, connection_id)
                return make_response(jsonify({"success": True, "kind": "oauth", **started}), 200)
            if auth_kind == "mcp_oauth":
                # The MCP client runs the OAuth dance (dynamic registration,
                # PKCE); the frontend starts it through /api/mcp_server/test.
                return make_response(
                    jsonify({"success": True, "kind": "mcp_oauth", "server_url": row.get("server_url")}), 200,
                )
            credentials = body.get("credentials")
            if not isinstance(credentials, dict) or not credentials:
                return _error("credentials are required", 400)
            service.ensure_can_store_credentials()
            with db_session() as conn:
                locked = ConnectorSessionsRepository(conn).get_for_update(connection_id)
                # read_secrets, not load_secrets: flagging an unreadable row
                # would write it from a second transaction while this one
                # holds its lock. The new credentials replace it anyway.
                try:
                    stored = service.read_secrets(locked)
                except CredentialDecryptionError:
                    stored = {}
                merged = {**(stored.get("credentials") or {}), **{k: v for k, v in credentials.items() if v}}
                service.write_secrets(
                    conn, locked, {**stored, "credentials": merged},
                    status=service.STATUS_CONNECTED, last_error=None,
                )
                service.resume_sources(conn, connection_id)
                connection = service.serialize_connection(ConnectorSessionsRepository(conn).get(connection_id))
        except service.EncryptionKeyNotConfigured as err:
            return _error(str(err), 400, code="encryption_key_default")
        except Exception as err:
            current_app.logger.error(f"Error reconnecting: {err}", exc_info=True)
            return _error("Failed to reconnect", 500)
        return make_response(jsonify({"success": True, "kind": "api_key", "connection": connection}), 200)


@connections_ns.route("/connections/<string:connection_id>/picker-token")
class ConnectionPickerToken(Resource):
    @api.doc(description="A short-lived access token for a browser-side file picker. Owner only; never a refresh token.")
    def post(self, connection_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        with db_readonly() as conn:
            row = _owned(conn, connection_id, user_id)
        if row is None or (row.get("auth_kind") or "oauth") != "oauth":
            return _not_found()
        try:
            token = service.picker_token(connection_id)
        except service.ConnectionUnavailable:
            return _error("Reconnect to continue", 409, code="reconnect")
        except service.TransientConnectionError:
            return _error("The provider is not responding. Try again.", 503)
        return make_response(jsonify({"success": True, **token}), 200)


@connections_ns.route("/connections/claim")
class ConnectionClaim(Resource):
    @api.doc(
        description=(
            "One-time link of a legacy browser session token ({provider, session_token}) "
            "to the caller's connection. Removed next release."
        )
    )
    def post(self):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        provider, token = body.get("provider"), body.get("session_token")
        if not provider or not token:
            return _error("provider and session_token are required", 400)
        with db_readonly() as conn:
            row = service.claim_session_token(conn, user_id, str(provider), str(token))
        if row is None:
            return _not_found()
        return make_response(jsonify({"success": True, "connection_id": str(row["id"])}), 200)


@connections_ns.route("/connections/<string:connection_id>/tools/<string:tool_id>/permissions")
class ConnectionToolPermissions(Resource):
    @api.doc(description="Set per-action permissions: {permissions: {action: always | ask | off}}")
    def put(self, connection_id: str, tool_id: str):
        from docsgpt.connectors.permissions import PERMISSIONS

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        permissions = _json_body().get("permissions")
        if not isinstance(permissions, dict) or any(p not in PERMISSIONS for p in permissions.values()):
            return _error("permissions must map action names to always, ask or off", 400)
        with db_session() as conn:
            row = _owned(conn, connection_id, user_id)
            if row is None:
                return _not_found()
            tool = service.set_tool_permissions(conn, user_id, connection_id, tool_id, permissions)
            if tool is None:
                return _not_found()
            payload = service.serialize_tool(tool, service.connection_parameters(row))
        return make_response(jsonify({"success": True, "tool": payload}), 200)


@connections_ns.route("/connections/<string:connection_id>/tools/<string:tool_id>/parameters")
class ConnectionToolParameters(Resource):
    @api.doc(
        description=(
            "Fix or release an action's parameters: {action, parameters: {name: value | null}}. "
            "A value is sent on every call and hidden from the model; null lets the model decide. Owner only."
        )
    )
    def put(self, connection_id: str, tool_id: str):
        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        body = _json_body()
        action, pins = body.get("action"), body.get("parameters")
        if not isinstance(action, str) or not isinstance(pins, dict) or not pins:
            return _error("Send the action and a map of parameters to values or null", 400)
        with db_session() as conn:
            row = _owned(conn, connection_id, user_id)
            if row is None:
                return _not_found()
            try:
                tool = service.set_tool_parameters(conn, user_id, connection_id, tool_id, action, pins)
            except ValueError as err:
                return _error(str(err), 400)
            if tool is None:
                return _not_found()
            payload = service.serialize_tool(tool, service.connection_parameters(row))
        return make_response(jsonify({"success": True, "tool": payload}), 200)


@connections_ns.route("/connections/<string:connection_id>/refresh-tools")
class ConnectionRefreshTools(Resource):
    @api.doc(description="MCP: re-scan the server's actions and return what was added and removed")
    def post(self, connection_id: str):
        from docsgpt.connectors.mcp import refresh_mcp_tools

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        with db_readonly() as conn:
            row = _owned(conn, connection_id, user_id)
        if row is None:
            return _not_found()
        try:
            diff = refresh_mcp_tools(user_id, row)
        except service.ConnectionUnavailable:
            return _error("Reconnect to continue", 409, code="reconnect")
        except Exception as err:
            current_app.logger.error(f"Error refreshing MCP tools: {err}", exc_info=True)
            return _error("Failed to refresh tools", 502)
        return make_response(jsonify({"success": True, **diff}), 200)


@connections_ns.route("/connections/tools/<string:tool_id>/credential-mode")
class ToolCredentialMode(Resource):
    @api.doc(
        description=(
            "Whose account a shared connection-backed tool uses: {mode: owner | member}. "
            "Owner only; refused when an admin forces a mode for the connector."
        )
    )
    def put(self, tool_id: str):
        from docsgpt.connectors.resolve import MODE_MEMBER, MODE_OWNER
        from docsgpt.storage.db.repositories.user_tools import UserToolsRepository

        user_id = _user_id()
        if not user_id:
            return _unauthorized()
        mode = _json_body().get("mode")
        if mode not in (MODE_OWNER, MODE_MEMBER):
            return _error("mode must be owner or member", 400)
        with db_session() as conn:
            tools = UserToolsRepository(conn)
            tool = tools.get_any(tool_id, user_id)
            if tool is None or tool.get("user_id") != user_id or not tool.get("connection_id"):
                return _error("Tool not found", 404)
            connection = ConnectorSessionsRepository(conn).get(str(tool["connection_id"]))
            forced = service.forced_credential_mode(
                conn, catalog.connector_key_for_row(connection) if connection else None,
            )
            if forced and forced != mode:
                return _error("An admin sets this for every share", 409, code="forced", mode=forced)
            tools.update(str(tool["id"]), user_id, {"credential_mode": mode})
        return make_response(jsonify({"success": True, "mode": mode}), 200)
