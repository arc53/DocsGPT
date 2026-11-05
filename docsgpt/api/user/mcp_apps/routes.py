"""MCP Apps routes: the sandbox page, a view's HTML and saved result, and the tool calls a view makes.

The chat renders an MCP tool's view (``docsgpt/agents/mcp_apps.py``) in the
sandbox page this API serves on an origin other than the app's. The view's
HTML and its own ``tools/call`` requests go through the user's session here,
on the tool row the call that drew it ran on.
"""

import json
import logging
from typing import Any, Optional, Tuple

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import text

from docsgpt.agents import mcp_apps
from docsgpt.agents.default_tools import resolve_tool_by_id
from docsgpt.agents.tool_executor import ToolExecutor
from docsgpt.agents.tool_pins import resolve_arguments
from docsgpt.api import api
from docsgpt.connectors.permissions import (
    ACCESS_WRITE,
    PERMISSION_ASK,
    PERMISSION_OFF,
    action_access,
    action_permission,
)
from docsgpt.security.origins import normalize_origin
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

mcp_apps_ns = Namespace("mcp_apps", description="MCP Apps: interactive tool views in chat", path="/api/mcp_apps")


def _error(message: str, status: int, **extra: Any):
    return make_response(jsonify({"success": False, "error": message, **extra}), status)


def _app_tool(user: str, tool_id: Any) -> Optional[Tuple[ToolExecutor, dict]]:
    """The MCP tool row ``user`` may use, and an executor to load it with; None when there is none.

    The row resolves as an agent's call to it does: the user's own, or one a
    live team grant lets them use. A row switched off (``status``) is left
    out, as the chat leaves it out, so an open view can't keep driving it.
    """
    if not isinstance(tool_id, str) or not tool_id:
        return None
    with db_readonly() as conn:
        row = resolve_tool_by_id(tool_id, user, user_tools_repo=UserToolsRepository(conn))
    if not row or row.get("name") != "mcp_tool" or row.get("status") is not True:
        return None
    return ToolExecutor(user=user), row


def _ships_view(row: dict) -> bool:
    """Whether any of ``row``'s actions renders an MCP App view."""
    return any(isinstance(a, dict) and mcp_apps.resource_uri(a) for a in row.get("actions") or [])


def _load(executor: ToolExecutor, row: dict):
    return executor._get_or_load_tool(row, str(row["id"]), "")


def _json_object() -> Optional[dict]:
    """The request's JSON body when it is an object; None when it is missing, malformed or not one."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _delegated(executor: ToolExecutor, row: dict, user: str) -> bool:
    """Whether a call on ``row`` runs on an account other than ``user``'s.

    A connection-backed row runs on the connection it resolves to: the
    owner's, or in member mode the caller's own. Any other row runs on its
    owner's credentials.
    """
    resolved = executor._resolve_connection(row)
    if resolved is not None:
        return bool(resolved.delegated)
    return row.get("user_id") != user


@mcp_apps_ns.route("/sandbox")
class McpAppSandbox(Resource):
    @api.doc(
        description=(
            "The sandbox page an MCP App view runs in, served with a CSP built from the view's declared domains. "
            "Only on the sandbox origin (MCP_APPS_SANDBOX_URL), never one of the app's."
        ),
        params={"csp": "The view's _meta.ui.csp, as JSON"},
    )
    def get(self):
        if not mcp_apps.enabled():
            return _error("MCP Apps are off", 404)
        hosts = mcp_apps.host_origins()
        # On an app origin the view's code would run where the session lives.
        if normalize_origin(request.host_url) in hosts:
            return _error("Not the MCP Apps sandbox origin", 404)
        try:
            csp = json.loads(request.args.get("csp") or "null")
        except ValueError:
            csp = None
        response = make_response(mcp_apps.sandbox_page(hosts))
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.headers["Content-Security-Policy"] = mcp_apps.build_csp(csp, hosts)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


@mcp_apps_ns.route("/resource")
class McpAppResource(Resource):
    @api.expect(
        api.model(
            "McpAppResourceModel",
            {
                "tool_id": fields.String(required=True, description="The MCP tool row the call ran on"),
                "uri": fields.String(required=True, description="The view's ui:// resource"),
            },
        )
    )
    @api.doc(description="Read an MCP App view's HTML and its declared CSP and permissions.")
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return _error("Unauthorized", 401)
        if not mcp_apps.enabled():
            return _error("MCP Apps are off", 404)
        data = _json_object()
        if data is None:
            return _error("Send a JSON object", 400)
        found = _app_tool(decoded_token.get("sub"), data.get("tool_id"))
        uri = data.get("uri")
        if found is None or not any(
            isinstance(a, dict) and mcp_apps.resource_uri(a) == uri for a in found[1].get("actions") or []
        ):
            return _error("No such view", 404)
        from docsgpt.connectors.service import ConnectionUnavailable

        try:
            view = _load(*found).read_ui_resource(uri)
        except ConnectionUnavailable:
            # A fixed message, as the connector routes answer: the exception's own may quote the provider.
            return _error("Reconnect to continue", 409, code="reconnect")
        except Exception as exc:
            logger.warning("MCP App view %s could not be read: %s", uri, exc)
            return _error("The view could not be loaded from its MCP server", 502)
        return make_response(jsonify({"success": True, **view, "sandbox_url": mcp_apps.sandbox_url()}), 200)


@mcp_apps_ns.route("/call")
class McpAppCall(Resource):
    @api.expect(
        api.model(
            "McpAppCallModel",
            {
                "tool_id": fields.String(required=True, description="The MCP tool row the view belongs to"),
                "name": fields.String(required=True, description="The tool the view calls"),
                "arguments": fields.Raw(required=False, description="Its arguments"),
                "approved": fields.Boolean(
                    required=False, description="The user approved this call, for a tool that needs approval"
                ),
            },
        )
    )
    @api.doc(
        description=(
            "Run a tool an MCP App view calls. Only tools visible to the app; a tool that needs approval answers "
            "409 needs_approval until the call is sent approved."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return _error("Unauthorized", 401)
        if not mcp_apps.enabled():
            return _error("MCP Apps are off", 404)
        user = decoded_token.get("sub")
        data = _json_object()
        if data is None:
            return _error("Send a JSON object", 400)
        found = _app_tool(user, data.get("tool_id"))
        if found is None:
            return _error("No such tool", 404)
        executor, row = found
        # Only a server that ships a view has calls a view makes.
        if not _ships_view(row):
            return _error("This tool has no app view", 403)
        name = data.get("name")
        action = next(
            (a for a in row.get("actions") or [] if isinstance(a, dict) and a.get("name") == name), None
        )
        if action is None or not mcp_apps.visible_to_app(action):
            return _error("The view may not call this tool", 403)
        # The same gate as an agent's call: the action's permission, or the row's own approval switch.
        permission = action_permission(action)
        if permission != PERMISSION_OFF and (row.get("config") or {}).get("require_approval"):
            permission = PERMISSION_ASK
        if permission == PERMISSION_OFF:
            return _error("This tool is turned off", 403)
        writes = action_access(row.get("name"), action) == ACCESS_WRITE
        if writes and _delegated(executor, row, user):
            return _error("A view can't change things on a shared tool's account", 403)
        if permission == PERMISSION_ASK and data.get("approved") is not True:
            return _error("This tool needs your approval", 409, needs_approval=True)
        arguments = data.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return _error("arguments must be an object", 400)
        # The view's arguments follow the model's rules: a fixed value wins over the
        # view's, and a parameter hidden from the model (``filled_by_llm`` false)
        # takes its stored value or stays out, whatever the view sends. The view is
        # the server's HTML, so it is trusted no further than the model is.
        arguments = resolve_arguments(action, arguments or {}, executor._connection_parameters(row))["parameters"]
        from docsgpt.connectors.service import ConnectionUnavailable

        logger.info("MCP App view call: tool row %s, %s, by %s", row.get("id"), name, user)
        try:
            result = _load(executor, row).call_app_tool(name, arguments)
        except ConnectionUnavailable:
            return _error("Reconnect to continue", 409, code="reconnect")
        except Exception as exc:
            logger.warning("MCP App call to %s failed: %s", name, exc)
            return _error("The tool call failed", 502)
        # As the view's copy of an agent's call: no control characters, no raw exposed secrets.
        return make_response(jsonify({"success": True, "result": executor.redact_app_result(result)}), 200)


@mcp_apps_ns.route("/result")
class McpAppResult(Resource):
    @api.expect(
        api.model(
            "McpAppResultModel",
            {
                "message_id": fields.String(required=True, description="The message the call belongs to"),
                "call_id": fields.String(required=True, description="The call that drew the view"),
            },
        )
    )
    @api.doc(
        description=(
            "Read back the tool result an MCP App view was handed live, for a reopened conversation. "
            "The caller needs the access that reloading the conversation needs."
        )
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return _error("Unauthorized", 401)
        if not mcp_apps.enabled():
            return _error("MCP Apps are off", 404)
        data = _json_object()
        if data is None:
            return _error("Send a JSON object", 400)
        message_id, call_id = data.get("message_id"), data.get("call_id")
        if not isinstance(message_id, str) or not looks_like_uuid(message_id):
            return _error("No such result", 404)
        if not isinstance(call_id, str) or not call_id:
            return _error("No such result", 404)
        with db_readonly() as conn:
            message = conn.execute(
                text("SELECT conversation_id FROM conversation_messages WHERE id = CAST(:id AS uuid)"),
                {"id": message_id},
            ).fetchone()
            # The access a reload of the conversation needs: its owner, or a user it is shared with.
            if message is None or not ConversationsRepository(conn).get_any(
                str(message._mapping["conversation_id"]), decoded_token.get("sub")
            ):
                return _error("No such result", 404)
            result = ToolCallAttemptsRepository(conn).get_app_result(message_id, call_id)
        if result is None:
            return _error("No such result", 404)
        return make_response(jsonify({"success": True, "result": result}), 200)
