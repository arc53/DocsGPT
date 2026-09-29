"""Tool management routes."""

import copy
from typing import Any, Optional
from urllib.parse import urlparse

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import Connection, text

from docsgpt.agents.default_tools import (
    builtin_agent_tools_for_management,
    BUILTIN_AGENT_TOOLS,
    default_tool_name_for_id,
    default_tools_for_management,
    is_builtin_agent_tool_id,
    is_default_tool_id,
    is_synthesized_tool_id,
    WORKFLOW_ONLY_BUILTINS,
)
from docsgpt.agents.tool_executor import API_TOOL_SECRET_SECTIONS, API_TOOL_SECRETS_KEY
from docsgpt.agents.tool_pins import iter_parameters, llm_fills, merge_submitted_actions, PinChangeRefused
from docsgpt.agents.tools.spec_parser import parse_spec
from docsgpt.agents.tools.tool_manager import ToolManager
from docsgpt.api import api
from docsgpt.api.pat.rules import filter_listing
from docsgpt.api.user.artifacts.authz import Principal, authorize_artifact
from docsgpt.api.user.resource_access import (
    AccessDenied,
    delete_settings,
    payload_for,
    require,
    ResourceAccess,
    settings_many,
)
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.connectors.catalog import base_url, definition_for_tool
from docsgpt.connectors.resolve import carry_removed_connection
from docsgpt.connectors.service import account_tool_names
from docsgpt.connectors.permissions import owner_credential_writes
from docsgpt.core.settings import settings
from docsgpt.core.url_validation import SSRFError, validate_url
from docsgpt.security.encryption import CredentialDecryptionError, decrypt_credentials, encrypt_credentials
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.repositories.notes import NotesRepository
from docsgpt.storage.db.repositories.todos import TodosRepository
from docsgpt.storage.db.repositories.user_tool_preferences import (
    UserToolPreferencesRepository,
)
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.upload_limits import (
    read_text_upload_limited,
    upload_limit_message,
    UploadTooLargeError,
)
from docsgpt.utils import check_required_fields, validate_function_name

tool_config = {}
tool_manager = ToolManager(config=tool_config)


# ---------------------------------------------------------------------------
# Shape translation helpers
# ---------------------------------------------------------------------------
# The frontend speaks camelCase (``displayName`` / ``customName`` /
# ``configRequirements``). The PG ``user_tools`` table stores snake_case
# (``display_name`` / ``custom_name`` / ``config_requirements``). Keep the
# translation localized to this module so repositories stay pure.

_CAMEL_TO_SNAKE = {
    "displayName": "display_name",
    "customName": "custom_name",
    "configRequirements": "config_requirements",
}
_SNAKE_TO_CAMEL = {v: k for k, v in _CAMEL_TO_SNAKE.items()}


def _row_to_api(row: dict) -> dict:
    """Rename DB-native snake_case keys to the camelCase shape the frontend expects."""
    out = dict(row)
    for snake, camel in _SNAKE_TO_CAMEL.items():
        if snake in out:
            out[camel] = out.pop(snake)
    # ``user_id`` is exposed as ``user`` in the legacy API shape.
    if "user_id" in out:
        out["user"] = out.pop("user_id")
    return out


def _api_to_update_fields(data: dict) -> dict:
    """Rename incoming camelCase update keys to the repo's snake_case columns."""
    fields_out: dict = {}
    for key, value in data.items():
        fields_out[_CAMEL_TO_SNAKE.get(key, key)] = value
    return fields_out


def _encrypt_secret_fields(config, config_requirements, user_id):
    secret_keys = [
        key for key, spec in config_requirements.items()
        if spec.get("secret") and key in config and config[key]
    ]
    if not secret_keys:
        return config

    storage_config = config.copy()
    secret_values = {k: config[k] for k in secret_keys}
    storage_config["encrypted_credentials"] = encrypt_credentials(secret_values, user_id)
    for key in secret_keys:
        storage_config.pop(key, None)
    return storage_config


def _validate_config(config, config_requirements, has_existing_secrets=False):
    errors = {}
    for key, spec in config_requirements.items():
        depends_on = spec.get("depends_on")
        if depends_on:
            if not all(config.get(dk) == dv for dk, dv in depends_on.items()):
                continue
        if spec.get("required") and not config.get(key):
            if has_existing_secrets and spec.get("secret"):
                continue
            errors[key] = f"{spec.get('label', key)} is required"
        value = config.get(key)
        if value is not None and value != "":
            if spec.get("type") == "number":
                try:
                    num = float(value)
                    if key == "timeout" and (num < 1 or num > 300):
                        errors[key] = "Timeout must be between 1 and 300"
                except (ValueError, TypeError):
                    errors[key] = f"{spec.get('label', key)} must be a number"
            if spec.get("enum") and value not in spec["enum"]:
                errors[key] = f"Invalid value for {spec.get('label', key)}"
    return errors


def _merge_secrets_on_update(new_config, existing_config, config_requirements, user_id):
    """Merge incoming config with existing encrypted secrets and re-encrypt.

    For updates, the client may omit unchanged secret values.  This helper
    decrypts any previously stored secrets, overlays whatever the client *did*
    send, strips plain-text secrets from the stored config, and re-encrypts
    the merged result.

    Returns the final ``config`` dict ready for persistence.
    """
    secret_keys = [
        key for key, spec in config_requirements.items()
        if spec.get("secret")
    ]

    if not secret_keys:
        return new_config

    existing_secrets = {}
    if "encrypted_credentials" in existing_config:
        existing_secrets = decrypt_credentials(
            existing_config["encrypted_credentials"], user_id
        )

    merged_secrets = existing_secrets.copy()
    for key in secret_keys:
        if key in new_config and new_config[key]:
            merged_secrets[key] = new_config[key]

    # Start from existing non-secret values, then overlay incoming non-secrets
    storage_config = {
        k: v for k, v in existing_config.items()
        if k not in secret_keys and k != "encrypted_credentials"
    }
    storage_config.update(
        {k: v for k, v in new_config.items() if k not in secret_keys}
    )

    if merged_secrets:
        storage_config["encrypted_credentials"] = encrypt_credentials(
            merged_secrets, user_id
        )
    else:
        storage_config.pop("encrypted_credentials", None)

    storage_config.pop("has_encrypted_credentials", None)
    return storage_config


# ---------------------------------------------------------------------------
# Access + secrets helpers
# ---------------------------------------------------------------------------
_CREDENTIALS_FOR_NEW_SERVER = "Enter credentials for the new server"
_FORBIDDEN_MESSAGE = "Your access to this item doesn't allow that"
_MCP_CREDENTIAL_AUTH_TYPES = {"api_key", "bearer", "basic"}
# ``name`` (the tool type) and ``actions`` are handled on their own.
_META_KEYS = ("displayName", "customName", "description")
_TYPE_IS_FIXED = "A tool's type can't be changed"
_FIXED_VALUES_OWNER_ONLY = "Only the tool's owner can change fixed values"
_MOVE_THROUGH_MCP_SAVE = (
    "This server signs in through a connection: change its address or sign-in by saving the "
    "server again (/api/mcp_server/save)"
)


class CredentialsRequired(Exception):
    """A save moved a tool to a new origin without supplying new secrets."""


def denied_response(err: AccessDenied):
    """JSON response for an :class:`AccessDenied` (403 or 404)."""
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


def check_action(ra: ResourceAccess, action: str) -> None:
    """Raise a 403 :class:`AccessDenied` unless ``ra`` allows ``action``."""
    if not ra.can(action):
        raise AccessDenied(403, _FORBIDDEN_MESSAGE)


_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def url_origin(url: Any) -> str:
    """``scheme://host:port`` of ``url``, lower-cased, default port filled in.

    Saved secrets follow the origin, not just the host: the same host over
    ``http`` would send them in cleartext, and another port can be another
    service. ``''`` when the URL has no host or doesn't parse.
    """
    try:
        parts = urlparse(str(url or "").strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return ""
    if not host:
        return ""
    scheme = (parts.scheme or "").lower()
    return f"{scheme}://{host}:{port or _DEFAULT_PORTS.get(scheme, '')}"


def _has_value(value: Any) -> bool:
    return value is not None and value != ""


def _secret_props(action: Any):
    """Yield ``(section, param, spec)`` for an api_tool action's secret-bearing params."""
    if not isinstance(action, dict):
        return
    for section in API_TOOL_SECRET_SECTIONS:
        block = action.get(section)
        props = block.get("properties") if isinstance(block, dict) else None
        if not isinstance(props, dict):
            continue
        for param, spec in props.items():
            if isinstance(spec, dict):
                yield section, param, spec


def _stored_api_tool_secrets(config: dict, owner_id: str) -> dict:
    """Decrypted ``{action: {section: {param: value}}}`` plus legacy plaintext values."""
    config = config or {}
    blob = config.get(API_TOOL_SECRETS_KEY)
    secrets: dict = decrypt_credentials(blob, owner_id) if blob else {}
    for name, action in (config.get("actions") or {}).items():
        for section, param, spec in _secret_props(action):
            value = spec.get("value")
            if _has_value(value):
                secrets.setdefault(name, {}).setdefault(section, {}).setdefault(param, value)
    return secrets


def mask_api_tool_config(config: dict) -> dict:
    """Copy of an api_tool config with header/query values blanked and ``has_value`` set.

    Args:
        config: The stored ``user_tools.config``.

    Returns:
        A deep copy safe to return to any caller: the encrypted blob is dropped
        and every header / query-param entry has ``value: ""`` plus ``has_value``.
    """
    out = copy.deepcopy(config or {})
    out.pop(API_TOOL_SECRETS_KEY, None)
    for action in (out.get("actions") or {}).values():
        for _section, _param, spec in _secret_props(action):
            spec["has_value"] = _has_value(spec.get("value")) or bool(spec.get("has_value"))
            spec["value"] = ""
    return out


def _seal_api_tool_secrets(new_config: dict, existing_config: dict, owner_id: str) -> dict:
    """Move api_tool header/query values into an encrypted blob keyed by the owner.

    An incoming entry with a value replaces the stored one; an empty value with
    ``has_value`` keeps it (legacy plaintext values included); anything else
    clears it. When an action's URL origin changes the stored values are not
    carried over.

    Args:
        new_config: The config the client sent.
        existing_config: The stored config (``{}`` on create).
        owner_id: The tool row's ``user_id`` — the encryption key owner.

    Returns:
        The config to persist.

    Raises:
        CredentialsRequired: an origin changed, the client asked to keep a value,
            and there is nothing to keep.
    """
    existing_config = existing_config or {}
    stored = _stored_api_tool_secrets(existing_config, owner_id)
    old_actions = existing_config.get("actions") or {}
    out = copy.deepcopy(new_config or {})
    out.pop(API_TOOL_SECRETS_KEY, None)
    sealed: dict = {}
    for name, action in (out.get("actions") or {}).items():
        old = old_actions.get(name) if isinstance(old_actions, dict) else None
        moved = isinstance(old, dict) and url_origin(old.get("url")) != url_origin(
            action.get("url") if isinstance(action, dict) else ""
        )
        prior = {} if moved else stored.get(name, {})
        for section, param, spec in _secret_props(action):
            value = spec.get("value")
            if _has_value(value):
                kept = value
            elif spec.get("has_value"):
                kept = (prior.get(section) or {}).get(param)
                if not _has_value(kept):
                    if moved:
                        raise CredentialsRequired(_CREDENTIALS_FOR_NEW_SERVER)
                    kept = None
            else:
                kept = None
            spec["value"] = ""
            spec["has_value"] = kept is not None
            if kept is not None:
                sealed.setdefault(name, {}).setdefault(section, {})[param] = kept
    if sealed:
        out[API_TOOL_SECRETS_KEY] = encrypt_credentials(sealed, owner_id)
    return out


def _api_tool_config_needs_credentials(new_config: dict, existing_config: dict) -> bool:
    """Whether an api_tool config change touches endpoints or secrets.

    Descriptions, parameter schemas and on/off flags are ``edit``; a new or
    changed URL, a new action (it brings a URL), a secret value or any other
    config key is ``edit_credentials``.
    """
    new_config = new_config or {}
    existing_config = existing_config or {}
    ignore = ("actions", API_TOOL_SECRETS_KEY, "has_encrypted_credentials")
    if {k: v for k, v in new_config.items() if k not in ignore} != {
        k: v for k, v in existing_config.items() if k not in ignore
    }:
        return True
    old_actions = existing_config.get("actions") or {}
    for name, action in (new_config.get("actions") or {}).items():
        old = old_actions.get(name)
        if not isinstance(old, dict) or not isinstance(action, dict):
            return True
        if str(action.get("url") or "") != str(old.get("url") or ""):
            return True
        for _section, _param, spec in _secret_props(action):
            if _has_value(spec.get("value")):
                return True
    return False


def _api_tool_param_state(section: str, spec: dict, *, stored: bool) -> tuple:
    """Who fills an api_tool parameter and which value it keeps.

    A header / query value is only ever shown masked, so a stored one (sealed,
    or legacy plaintext) reads as ``"stored"`` and any value a client sends
    is a new one.

    Args:
        section: ``headers``, ``query_params`` or ``body``.
        spec: The parameter's schema.
        stored: Whether ``spec`` comes from the stored config.

    Returns:
        ``(filled_by_llm, value marker)``; the marker is None without a value.
    """
    value = spec.get("value")
    if section in API_TOOL_SECRET_SECTIONS:
        if _has_value(value):
            marker: Any = "stored" if stored else ("new", value)
        else:
            marker = "stored" if spec.get("has_value") else None
    else:
        marker = value if _has_value(value) else None
    return llm_fills(spec), marker


def _api_tool_fixed_values_changed(new_config: dict, existing_config: dict) -> bool:
    """Whether an api_tool save changes a fixed value of an existing action.

    A fixed value may be a secret (an API key in a query) or where a call
    goes, so changing who fills a parameter, or its value, or clearing a
    stored one is the owner's. Flipping ``filled_by_llm`` on a stored secret
    would hand it to the model and show it in the chat. A parameter that
    carries no value can be added or removed freely; a new action brings a
    URL and is judged by :func:`_api_tool_config_needs_credentials`.

    Args:
        new_config: The config the client sent.
        existing_config: The stored config.

    Returns:
        True when any existing action's fixed values would differ.
    """
    old_actions = (existing_config or {}).get("actions") or {}
    new_actions = (new_config or {}).get("actions") or {}
    if not isinstance(old_actions, dict) or not isinstance(new_actions, dict):
        return bool(old_actions) or bool(new_actions)
    for name, action in new_actions.items():
        old = old_actions.get(name)
        if not isinstance(old, dict) or not isinstance(action, dict):
            continue
        before = {(s, p): _api_tool_param_state(s, d, stored=True) for s, p, d in iter_parameters(old)}
        after = {(s, p): _api_tool_param_state(s, d, stored=False) for s, p, d in iter_parameters(action)}
        for key in before.keys() | after.keys():
            if key in before and key in after:
                if before[key] != after[key]:
                    return True
            elif (before.get(key) or after.get(key))[1] is not None:
                return True
    return False


def _connection_server_moved(tool_doc: dict, new_config: Optional[dict]) -> bool:
    """Whether a config save re-points a connection-backed MCP tool.

    The connection holds the key for one server and one way of signing in;
    a tool moved on these routes would keep a connection that no longer
    applies (it is refused at run time) and the new key would be stored
    where nothing reads it. ``/api/mcp_server/save`` moves a server properly.

    Args:
        tool_doc: The stored ``user_tools`` row.
        new_config: The incoming ``config``.

    Returns:
        True when the base URL or ``auth_type`` would change.
    """
    if tool_doc.get("name") != "mcp_tool" or not tool_doc.get("connection_id"):
        return False
    existing = tool_doc.get("config") or {}
    new_config = new_config if isinstance(new_config, dict) else {}
    if "server_url" in new_config and base_url(str(new_config.get("server_url") or "").strip()) != base_url(
        existing.get("server_url")
    ):
        return True
    return "auth_type" in new_config and (new_config.get("auth_type") or "none") != (
        existing.get("auth_type") or "none"
    )


def _mcp_origin_changed(new_config: dict, existing_config: dict) -> bool:
    """Whether a save moves an MCP server to another scheme, host or port."""
    old_url = (existing_config or {}).get("server_url")
    return bool(old_url) and url_origin(old_url) != url_origin((new_config or {}).get("server_url"))


SHARED_OAUTH_OWNER_ONLY = "Only the owner can change or reconnect this server"


def check_oauth_mcp_owner_only(
    ra: ResourceAccess, existing_config: Optional[dict], new_config: Optional[dict]
) -> None:
    """Keep a shared OAuth MCP server's connection with its owner.

    MCP OAuth tokens are looked up by owner + server URL and a shared server
    runs as its owner, so a grantee who moved an OAuth server, switched a
    server to OAuth, or re-ran its sign-in would be using the owner's account
    somewhere the owner never chose. Until connectors own OAuth accounts, any
    connection change on a server that is (or would become) OAuth is
    owner-only.

    Args:
        ra: The caller's access to the tool.
        existing_config: The stored ``config``.
        new_config: The incoming ``config``.

    Raises:
        AccessDenied: 403 when a non-owner touches an OAuth server's config.
    """
    if ra.access == "owner":
        return
    configs = [c if isinstance(c, dict) else {} for c in (existing_config, new_config)]
    auth_types = {c.get("auth_type") for c in configs}
    if "oauth" in auth_types:
        raise AccessDenied(403, SHARED_OAUTH_OWNER_ONLY)


def check_api_tool_fixed_values(
    ra: ResourceAccess, new_config: Optional[dict], existing_config: Optional[dict]
) -> None:
    """Keep an api_tool's fixed header, query and body values with its owner.

    Args:
        ra: The caller's access to the tool.
        new_config: The incoming ``config``.
        existing_config: The stored ``config``.

    Raises:
        AccessDenied: 403 when a non-owner changes a fixed value (see
            :func:`_api_tool_fixed_values_changed`).
    """
    if ra.access != "owner" and _api_tool_fixed_values_changed(new_config or {}, existing_config or {}):
        raise AccessDenied(403, _FIXED_VALUES_OWNER_ONLY)


def _prepare_tool_config(tool_doc: dict, new_config: dict, config_requirements: dict) -> dict:
    """Validate-free merge of an incoming config with the stored one, as the owner.

    Handles the three secret stores: ``config_requirements`` secrets
    (``encrypted_credentials``), api_tool header/query values, and the MCP
    origin-change rule (a new scheme, host or port drops stored credentials).
    A removed connection's note is carried over from the stored config; the
    client's copy is ignored.

    Raises:
        CredentialsRequired: the MCP origin changed and no new secret arrived.
    """
    owner_id = tool_doc["user_id"]
    existing_config = tool_doc.get("config") or {}
    # The note that its connection was removed is the server's to keep.
    new_config = carry_removed_connection(new_config, existing_config)
    if tool_doc.get("name") == "api_tool":
        return _seal_api_tool_secrets(new_config, existing_config, owner_id)
    moved = tool_doc.get("name") == "mcp_tool" and _mcp_origin_changed(new_config, existing_config)
    if moved:
        existing_config = {k: v for k, v in existing_config.items() if k != "encrypted_credentials"}
    final = _merge_secrets_on_update(new_config, existing_config, config_requirements, owner_id)
    if moved and final.get("auth_type") in _MCP_CREDENTIAL_AUTH_TYPES and not final.get(
        "encrypted_credentials"
    ):
        raise CredentialsRequired(_CREDENTIALS_FOR_NEW_SERVER)
    return final


def _shared_via(conn: Connection, user_id: str, tool_ids: list) -> dict:
    """``tool_id -> team name`` through which a grant reaches ``user_id``."""
    ids = [str(t) for t in tool_ids if looks_like_uuid(str(t))]
    if not ids:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (g.resource_id) g.resource_id, t.name
            FROM team_resource_grants g
            JOIN team_members m ON m.team_id = g.team_id
            JOIN teams t ON t.id = g.team_id
            WHERE m.user_id = :user_id AND g.resource_type = 'tool'
              AND g.resource_id = ANY(CAST(:ids AS uuid[]))
              AND (g.target_user_id IS NULL OR g.target_user_id = :user_id)
            ORDER BY g.resource_id, (g.access_level = 'editor') DESC, t.name
            """
        ),
        {"user_id": user_id, "ids": ids},
    ).fetchall()
    return {str(r[0]): r[1] for r in rows}


def _owner_labels(conn: Connection, owner_ids) -> dict:
    """``user_id -> email`` for the owners that have one on record."""
    ids = sorted({str(o) for o in owner_ids if o})
    if not ids:
        return {}
    rows = conn.execute(
        text("SELECT user_id, email FROM users WHERE user_id = ANY(:ids) AND email IS NOT NULL"),
        {"ids": ids},
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _load_owned_row(conn: Connection, ra: ResourceAccess) -> Optional[dict]:
    """The tool row behind ``ra``, read as its owner."""
    return UserToolsRepository(conn).get_any(ra.resource_id, ra.owner_id)


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
                param_details["filled_by_llm"] = True
                param_details["value"] = ""
        transformed.append(action)
    return transformed


def _stored_actions(tool_doc: dict) -> list:
    """A tool's stored actions, or its class's own for a row stored without any.

    Args:
        tool_doc: The ``user_tools`` row.

    Returns:
        The action list submitted actions are validated against.
    """
    actions = tool_doc.get("actions") or []
    if actions or tool_doc.get("name") in ("mcp_tool", "api_tool"):
        return actions
    tool_instance = tool_manager.tools.get(tool_doc.get("name"))
    if tool_instance is None:
        return actions
    return transform_actions(copy.deepcopy(tool_instance.get_actions_metadata()))


tools_ns = Namespace("tools", description="Tool management operations", path="/api")

# Tools the Connectors page adds through "Add custom connector" rather than
# the Add Tool modal.
_CUSTOM_CONNECTOR_TOOLS = {"mcp_tool": "custom_mcp", "api_tool": "custom_openapi"}


@tools_ns.route("/available_tools")
class AvailableTools(Resource):
    @api.doc(description="Get available tools for a user")
    def get(self):
        if not request.decoded_token:
            return make_response(jsonify({"success": False}), 401)
        from docsgpt.connectors import service as connection_service

        try:
            with db_readonly() as conn:
                policies = connection_service.load_policies(conn)
        except Exception:
            # Without the admin's switches, fall back to the defaults (a
            # connector is on when its server settings are present).
            current_app.logger.warning("Could not read connector policies", exc_info=True)
            policies = {}
        try:
            tools_metadata = []
            for tool_name, tool_instance in tool_manager.tools.items():
                doc = tool_instance.__doc__.strip()
                lines = doc.split("\n", 1)
                name = lines[0].strip()
                description = lines[1].strip() if len(lines) > 1 else ""
                config_req = tool_instance.get_config_requirements()
                actions = tool_instance.get_actions_metadata()
                definition = definition_for_tool(tool_name)
                if definition is not None:
                    if not (definition.configured and connection_service.connector_is_enabled(
                        policies, definition.key,
                    )):
                        continue
                    group, connector_key = "service", definition.key
                    # One name everywhere: the connector's, not the tool's own.
                    name = definition.name
                elif tool_name in _CUSTOM_CONNECTOR_TOOLS:
                    group, connector_key = "custom", _CUSTOM_CONNECTOR_TOOLS[tool_name]
                else:
                    group, connector_key = "built_in", None
                tools_metadata.append(
                    {
                        "name": tool_name,
                        "displayName": name,
                        "description": description,
                        "configRequirements": config_req,
                        "actions": actions,
                        "group": group,
                        "connector_key": connector_key,
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
            with db_readonly() as conn:
                tools_repo = UserToolsRepository(conn)
                rows = tools_repo.list_for_user(user)
                user_doc = UsersRepository(conn).get(user)
                owned_ids = {str(r["id"]) for r in rows}
                # Tools shared with the caller's teams. Secrets are stripped
                # unconditionally below — a grantee never sees the owner's
                # credentials (they only run with the owner's creds server-side).
                team_shared = visible_with_access(conn, user, "tool")
                shared_ids = [tid for tid in team_shared if tid not in owned_ids]
                shared_rows = tools_repo.list_by_ids(shared_ids)
                # "Telegram · Alerts bot" when the owner has several bots.
                account_names = account_tool_names(conn, [*rows, *shared_rows])
                switches = settings_many(conn, "tool", [*owned_ids, *shared_ids])
                prefs = UserToolPreferencesRepository(conn).in_chat_many(user, shared_ids)
                shared_via = _shared_via(conn, user, shared_ids)
                owner_labels = _owner_labels(conn, [r.get("user_id") for r in shared_rows])
            user_tools = []

            def _shape_tool(row, *, ownership="user", force_strip_secret=False):
                tool_copy = _row_to_api(row)
                # The writes an agent's API write allowlist can cover (read
                # from the stored row, before any secret is masked).
                tool_copy["owner_credential_writes"] = owner_credential_writes(row)
                config_req = tool_copy.get("configRequirements", {})
                if not config_req:
                    tool_instance = tool_manager.tools.get(tool_copy.get("name"))
                    if tool_instance:
                        config_req = tool_instance.get_config_requirements()
                        tool_copy["configRequirements"] = config_req
                has_secrets = any(
                    spec.get("secret") for spec in config_req.values()
                ) if config_req else False
                if (has_secrets or force_strip_secret) and "encrypted_credentials" in tool_copy.get(
                    "config", {}
                ):
                    tool_copy["config"]["has_encrypted_credentials"] = True
                    tool_copy["config"].pop("encrypted_credentials", None)
                if tool_copy.get("connection_id"):
                    # The secret lives on the connection; the form must not
                    # ask for it again.
                    tool_copy.setdefault("config", {})["has_encrypted_credentials"] = True
                if tool_copy.get("name") == "api_tool":
                    # Header / query-param values are secrets for everyone.
                    tool_copy["config"] = mask_api_tool_config(tool_copy.get("config") or {})
                tool_copy["ownership"] = ownership
                if str(row["id"]) in account_names:
                    tool_copy["customName"] = tool_copy["displayName"] = account_names[str(row["id"])]
                return tool_copy

            for row in rows:
                shaped = _shape_tool(row)
                shaped.update(payload_for("tool", "owner", switches.get(str(row["id"]))))
                shaped["in_chat"] = bool(row.get("status"))
                user_tools.append(shaped)
            for row in shared_rows:
                tid = str(row["id"])
                shaped = _shape_tool(row, ownership="team", force_strip_secret=True)
                shaped["team_access"] = team_shared.get(tid)
                shaped.update(payload_for("tool", team_shared.get(tid), switches.get(tid)))
                shaped["in_chat"] = prefs.get(tid, False)
                shaped["shared_via"] = shared_via.get(tid)
                shaped["owner_label"] = owner_labels.get(row.get("user_id"))
                user_tools.append(shaped)

            # ``scheduler`` is dual-registered (default chat tool + agent-
            # selectable builtin) and resolves to the same synthetic uuid5 id.
            # Surface a single row with both flags so the frontend can show it
            # in the management page (toggle) and the agent picker.
            seen_ids: set = set()
            for default_row in default_tools_for_management(user_doc):
                default_copy = _row_to_api(default_row)
                default_copy["default"] = True
                default_copy["in_chat"] = bool(default_copy.get("status"))
                if default_copy.get("name") in BUILTIN_AGENT_TOOLS:
                    default_copy["builtin"] = True
                seen_ids.add(str(default_copy["id"]))
                user_tools.append(default_copy)
            # Builtins (e.g. scheduler) hidden from Add-Tool catalog, visible
            # to the agent picker. Skip ones already added via the default
            # path — both registries share ``_DEFAULT_TOOL_NAMESPACE``.
            # ``workflow_only`` builtins (e.g. ``read_document``) carry that
            # flag so the classic picker can hide them and the workflow node
            # picker can keep them.
            for builtin_row in builtin_agent_tools_for_management():
                builtin_copy = _row_to_api(builtin_row)
                if str(builtin_copy["id"]) in seen_ids:
                    continue
                builtin_copy["builtin"] = True
                builtin_copy["default"] = False
                builtin_copy["workflow_only"] = (
                    builtin_copy.get("name") in WORKFLOW_ONLY_BUILTINS
                )
                user_tools.append(builtin_copy)
            # A resource-restricted token sees only its allowed tools. Default
            # and builtin rows have ids too, so they follow the same allowlist.
            user_tools = filter_listing(request, "tools", user_tools)
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
        if isinstance(data.get("config"), dict):
            # Only removing a connection notes that it was removed.
            data["config"] = carry_removed_connection(data["config"], None)
        try:
            if data["name"] == "mcp_tool":
                server_url = (data.get("config", {}).get("server_url") or "").strip()
                if server_url:
                    try:
                        validate_url(server_url)
                    except SSRFError:
                        return make_response(
                            jsonify({"success": False, "message": "Invalid server URL"}),
                            400,
                        )
            tool_instance = tool_manager.tools.get(data["name"])
            if not tool_instance:
                return make_response(
                    jsonify({"success": False, "message": "Tool not found"}), 404
                )
            actions_metadata = tool_instance.get_actions_metadata()
            transformed_actions = transform_actions(actions_metadata)
        except Exception as err:
            current_app.logger.error(
                f"Error getting tool actions: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)
        definition = definition_for_tool(data["name"])
        if definition is not None:
            connected = _create_connected_tool(user, data, definition, tool_instance)
            if connected is not None:
                return connected
        try:
            config_requirements = tool_instance.get_config_requirements()
            if config_requirements:
                validation_errors = _validate_config(
                    data["config"], config_requirements
                )
                if validation_errors:
                    return make_response(
                        jsonify(
                            {
                                "success": False,
                                "message": "Validation failed",
                                "errors": validation_errors,
                            }
                        ),
                        400,
                    )
            if data["name"] == "api_tool":
                storage_config = _seal_api_tool_secrets(data["config"], {}, user)
            else:
                storage_config = _encrypt_secret_fields(
                    data["config"], config_requirements, user
                )
            with db_session() as conn:
                created = UserToolsRepository(conn).create(
                    user,
                    data["name"],
                    config=storage_config,
                    custom_name=data.get("customName", ""),
                    display_name=data["displayName"],
                    description=data["description"],
                    config_requirements=config_requirements,
                    actions=transformed_actions,
                    status=bool(data.get("status", True)),
                )
            new_id = str(created["id"])
        except Exception as err:
            current_app.logger.error(f"Error creating tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"id": new_id}), 200)


def _create_connected_tool(user, data, definition, tool_instance):
    """Create a service tool whose secret lives on a connection, not the tool.

    Uses ``connection_id`` when given, otherwise stores the pasted secret on
    a connection (reusing an identical one). Returns None to fall back to the
    legacy path when a multi-user install still runs on the default key.
    """
    from docsgpt.connectors import catalog as connector_catalog
    from docsgpt.connectors import service as connection_service
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    config_requirements = tool_instance.get_config_requirements()
    public, secrets = connection_service.split_secrets(data.get("config") or {}, config_requirements)
    connection_id = data.get("connection_id")
    # An existing connection supplies the secrets the request leaves out.
    validation_errors = _validate_config(
        data.get("config") or {}, config_requirements, has_existing_secrets=bool(connection_id),
    )
    if validation_errors:
        return make_response(
            jsonify({"success": False, "message": "Validation failed", "errors": validation_errors}), 400,
        )
    try:
        with db_session() as conn:
            if connection_id:
                connection = ConnectorSessionsRepository(conn).get_for_user(str(connection_id), user)
                if connection is None or connector_catalog.connector_key_for_row(connection) != definition.key:
                    return make_response(jsonify({"success": False, "message": "Connection not found"}), 404)
            else:
                connection, _ = connection_service.create_api_key_connection(conn, user, definition, secrets)
            created = connection_service.create_tool_for_connection(
                conn,
                user,
                connection,
                template=data["name"],
                display_name=data.get("customName") or data.get("displayName") or definition.name,
                config=public,
                status=bool(data.get("status", True)),
            )
    except connection_service.EncryptionKeyNotConfigured:
        return None
    except connection_service.ConnectorDisabled as err:
        return make_response(jsonify({"success": False, "message": str(err)}), 403)
    except ValueError as err:
        return make_response(jsonify({"success": False, "message": str(err)}), 400)
    return make_response(jsonify({"id": str(created["id"]), "connection_id": str(connection["id"])}), 200)


def _update_connection_secrets(conn, user, tool_doc, config, config_requirements):
    """Write changed secrets onto the tool's connection; return the tool's public config.

    Returns None when the caller does not own the connection (an editor on a
    team share may change actions, never the owner's credentials).
    """
    from docsgpt.connectors import service as connection_service
    from docsgpt.storage.db.repositories.connector_sessions import ConnectorSessionsRepository

    public, secrets = connection_service.split_secrets(config or {}, config_requirements)
    if secrets:
        connection = ConnectorSessionsRepository(conn).get_for_user(str(tool_doc["connection_id"]), user)
        if connection is None:
            return None
        try:
            stored = connection_service.read_secrets(connection)
        except CredentialDecryptionError:
            # Unreadable after a lost key: the new secret replaces it.
            stored = {}
        credentials = {**(stored.get("credentials") or {}), **secrets}
        connection_service.write_secrets(
            conn, connection, {**stored, "credentials": credentials},
            status=connection_service.STATUS_CONNECTED, last_error=None,
        )
        connection_service.resume_sources(conn, str(connection["id"]))
    return public


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
        """Update a tool's names, actions, config or chat switch.

        The tool type (``name``) never changes. ``actions`` are checked
        against the stored ones like ``/api/update_tool_actions``: nothing
        is added and fixed values are the owner's. A connection-backed MCP
        server is moved only through ``/api/mcp_server/save``.

        Returns:
            ``{"success": true}``, or 400 / 403 / 404 with a message.
        """
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        # Default-tool branch first: a dual-registered tool (e.g. ``scheduler``)
        # matches BOTH ``is_default_tool_id`` and ``is_builtin_agent_tool_id``.
        # The toggle in Tools settings is the per-user opt-out for the
        # agentless default — it must reach the ``set_default_tool_enabled``
        # path, not the builtin "not editable" reject.
        if is_default_tool_id(data["id"]):
            if "status" not in data:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Default tools are not editable; "
                            "only their on/off status can be changed.",
                        }
                    ),
                    400,
                )
            tool_name = default_tool_name_for_id(data["id"])
            try:
                with db_session() as conn:
                    UsersRepository(conn).set_default_tool_enabled(
                        user, tool_name, bool(data["status"])
                    )
            except Exception as err:
                current_app.logger.error(
                    f"Error updating default tool: {err}", exc_info=True
                )
                return make_response(jsonify({"success": False}), 400)
            return make_response(jsonify({"success": True}), 200)
        if is_builtin_agent_tool_id(data["id"]):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Built-in agent tools are not editable; "
                        "add them to an agent via the agent picker.",
                    }
                ),
                400,
            )
        if "config" in data and isinstance(data["config"], dict) and "actions" in data["config"]:
            for action_name in list((data["config"]["actions"] or {}).keys()):
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
        try:
            update_data: dict = {}
            for key in _META_KEYS:
                if key in data:
                    update_data[key] = data[key]
            with db_session() as conn:
                ra = require(conn, "tool", data["id"], user, "use")
                tool_doc = _load_owned_row(conn, ra)
                if not tool_doc:
                    return make_response(
                        jsonify({"success": False, "message": "Tool not found"}), 404,
                    )
                if "name" in data and data["name"] != tool_doc.get("name"):
                    # The type decides what the config and the connection's
                    # credentials are used for; it is set once, on create.
                    return make_response(jsonify({"success": False, "message": _TYPE_IS_FIXED}), 400)
                if update_data or "actions" in data:
                    check_action(ra, "edit")
                if "actions" in data:
                    # The stored actions are the schema, and a fixed value is
                    # the owner's (as on /api/update_tool_actions).
                    try:
                        update_data["actions"] = merge_submitted_actions(
                            _stored_actions(tool_doc), data["actions"], may_change_pins=ra.access == "owner",
                        )
                    except PinChangeRefused as err:
                        return make_response(jsonify({"success": False, "message": str(err)}), 403)
                    except ValueError as err:
                        return make_response(jsonify({"success": False, "message": str(err)}), 400)
                if "config" in data:
                    tool_name = tool_doc.get("name")
                    existing_config = tool_doc.get("config", {}) or {}
                    if tool_name == "mcp_tool":
                        check_oauth_mcp_owner_only(ra, existing_config, data["config"])
                    if _connection_server_moved(tool_doc, data["config"]):
                        return make_response(jsonify({"success": False, "message": _MOVE_THROUGH_MCP_SAVE}), 400)
                    if tool_name == "api_tool":
                        check_api_tool_fixed_values(ra, data["config"], existing_config)
                    if tool_name == "api_tool" and not _api_tool_config_needs_credentials(
                        data["config"], existing_config
                    ):
                        check_action(ra, "edit")
                    else:
                        check_action(ra, "edit_credentials")
                    tool_instance = tool_manager.tools.get(tool_name)
                    config_requirements = (
                        tool_instance.get_config_requirements() if tool_instance else {}
                    )
                    has_existing_secrets = (
                        "encrypted_credentials" in existing_config or bool(tool_doc.get("connection_id"))
                    )
                    # Validate before touching the connection: a rejected
                    # edit must not have rotated its credentials.
                    if config_requirements:
                        validation_errors = _validate_config(
                            data["config"], config_requirements,
                            has_existing_secrets=has_existing_secrets,
                        )
                        if validation_errors:
                            return make_response(
                                jsonify({
                                    "success": False,
                                    "message": "Validation failed",
                                    "errors": validation_errors,
                                }),
                                400,
                            )
                    if tool_doc.get("connection_id"):
                        # The connection may back the owner's other tools too,
                        # so its secret stays the owner's to change even when
                        # an editor may change the tool's own credentials.
                        new_config = _update_connection_secrets(
                            conn, user, tool_doc, data["config"], config_requirements,
                        )
                        if new_config is None:
                            return make_response(
                                jsonify({"success": False, "message": "Only the owner can change the credentials"}),
                                403,
                            )
                        data = {**data, "config": new_config}

                    update_data["config"] = _prepare_tool_config(
                        tool_doc, data["config"], config_requirements
                    )
                if "status" in data:
                    if ra.access == "owner":
                        update_data["status"] = bool(data["status"])
                    else:
                        # A grantee's chat switch is personal; the owner's
                        # ``status`` is the owner's own chat setting.
                        check_action(ra, "use_in_own")
                        UserToolPreferencesRepository(conn).set_in_chat(
                            user, str(tool_doc["id"]), bool(data["status"])
                        )
                if update_data:
                    UserToolsRepository(conn).update(
                        str(tool_doc["id"]), ra.owner_id, _api_to_update_fields(update_data),
                    )
        except AccessDenied as err:
            return denied_response(err)
        except CredentialsRequired as err:
            return make_response(jsonify({"success": False, "message": str(err)}), 400)
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
        """Replace a tool's config, keeping stored secrets the client left out.

        A connection-backed tool's new key goes to its connection (the
        owner's to change) and its server cannot be moved here; an api_tool's
        fixed values are the owner's.

        Returns:
            ``{"success": true}``, or 400 / 403 / 404 with a message.
        """
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        data = request.get_json()
        required_fields = ["id", "config"]
        missing_fields = check_required_fields(data, required_fields)
        if missing_fields:
            return missing_fields
        if is_synthesized_tool_id(data["id"]):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Default and built-in tools are config-free "
                        "and cannot be configured.",
                    }
                ),
                400,
            )
        try:
            with db_session() as conn:
                repo = UserToolsRepository(conn)
                ra = require(conn, "tool", data["id"], user, "edit_credentials")
                tool_doc = _load_owned_row(conn, ra)
                if not tool_doc:
                    return make_response(jsonify({"success": False}), 404)

                tool_name = tool_doc.get("name")
                if tool_name == "mcp_tool":
                    check_oauth_mcp_owner_only(ra, tool_doc.get("config"), data["config"])
                    server_url = (data["config"].get("server_url") or "").strip()
                    if server_url:
                        try:
                            validate_url(server_url)
                        except SSRFError:
                            return make_response(
                                jsonify({"success": False, "message": "Invalid server URL"}),
                                400,
                            )
                if _connection_server_moved(tool_doc, data["config"]):
                    return make_response(jsonify({"success": False, "message": _MOVE_THROUGH_MCP_SAVE}), 400)
                if tool_name == "api_tool":
                    check_api_tool_fixed_values(ra, data["config"], tool_doc.get("config"))
                tool_instance = tool_manager.tools.get(tool_name)
                config_requirements = (
                    tool_instance.get_config_requirements() if tool_instance else {}
                )
                existing_config = tool_doc.get("config", {}) or {}
                has_existing_secrets = (
                    "encrypted_credentials" in existing_config or bool(tool_doc.get("connection_id"))
                )

                if config_requirements:
                    validation_errors = _validate_config(
                        data["config"], config_requirements,
                        has_existing_secrets=has_existing_secrets,
                    )
                    if validation_errors:
                        return make_response(
                            jsonify({
                                "success": False,
                                "message": "Validation failed",
                                "errors": validation_errors,
                            }),
                            400,
                        )

                config = data["config"]
                if tool_doc.get("connection_id"):
                    # The tool runs with its connection's key: a new one goes
                    # there (the owner's to change), not into this config.
                    config = _update_connection_secrets(conn, user, tool_doc, config, config_requirements)
                    if config is None:
                        return make_response(
                            jsonify({"success": False, "message": "Only the owner can change the credentials"}),
                            403,
                        )
                final_config = _prepare_tool_config(tool_doc, config, config_requirements)

                repo.update(str(tool_doc["id"]), ra.owner_id, {"config": final_config})
        except AccessDenied as err:
            return denied_response(err)
        except CredentialsRequired as err:
            return make_response(jsonify({"success": False, "message": str(err)}), 400)
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
        if is_synthesized_tool_id(data["id"]):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Default and built-in tools' actions are not editable.",
                    }
                ),
                400,
            )
        try:
            with db_session() as conn:
                # ``edit`` covers action on/off, descriptions and approval
                # (``require_approval``); actions carry no credentials.
                ra = require(conn, "tool", data["id"], user, "edit")
                tool_doc = _load_owned_row(conn, ra)
                if not tool_doc:
                    return make_response(
                        jsonify({"success": False, "message": "Tool not found"}), 404,
                    )
                # The stored actions are the schema: nothing can be added,
                # and a fixed value is the owner's to set (an editor pinning
                # a Telegram chat would redirect the owner's bot).
                try:
                    actions = merge_submitted_actions(
                        _stored_actions(tool_doc), data["actions"], may_change_pins=ra.access == "owner",
                    )
                except PinChangeRefused as err:
                    return make_response(jsonify({"success": False, "message": str(err)}), 403)
                except ValueError as err:
                    return make_response(jsonify({"success": False, "message": str(err)}), 400)
                UserToolsRepository(conn).update(str(tool_doc["id"]), ra.owner_id, {"actions": actions})
        except AccessDenied as err:
            return denied_response(err)
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
            # Default branch first so a dual-registered id (e.g. ``scheduler``)
            # writes the per-user opt-out instead of being rejected as a
            # not-editable builtin (both predicates match the same uuid5).
            if is_default_tool_id(data["id"]):
                tool_name = default_tool_name_for_id(data["id"])
                with db_session() as conn:
                    UsersRepository(conn).set_default_tool_enabled(
                        user, tool_name, bool(data["status"])
                    )
                return make_response(jsonify({"success": True}), 200)
            if is_builtin_agent_tool_id(data["id"]):
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": "Built-in agent tools have no per-user "
                            "toggle; add them to an agent via the agent picker.",
                        }
                    ),
                    400,
                )
            with db_session() as conn:
                ra = require(conn, "tool", data["id"], user, "use")
                if ra.access == "owner":
                    UserToolsRepository(conn).update(
                        ra.resource_id, ra.owner_id, {"status": bool(data["status"])},
                    )
                else:
                    # A grantee's "In my chats" switch is personal.
                    check_action(ra, "use_in_own")
                    UserToolPreferencesRepository(conn).set_in_chat(
                        user, ra.resource_id, bool(data["status"])
                    )
        except AccessDenied as err:
            return denied_response(err)
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
        if is_synthesized_tool_id(data["id"]):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Built-in tools cannot be deleted; disable them instead.",
                    }
                ),
                400,
            )
        try:
            with db_session() as conn:
                ra = require(conn, "tool", data["id"], user, "delete")
                # Grants are removed by the ``user_tools`` delete trigger and
                # chat preferences by FK cascade; the switches have no FK.
                UserToolsRepository(conn).delete(ra.resource_id, ra.owner_id)
                delete_settings(conn, "tool", ra.resource_id)
        except AccessDenied as err:
            return denied_response(err)
        except Exception as err:
            current_app.logger.error(f"Error deleting tool: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True}), 200)


@tools_ns.route("/parse_spec")
class ParseSpec(Resource):
    @api.doc(
        description="Parse an API specification (OpenAPI 3.x or Swagger 2.0) and return actions"
    )
    def post(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        if "file" in request.files:
            file = request.files["file"]
            if not file.filename:
                return make_response(
                    jsonify({"success": False, "message": "No file selected"}), 400
                )
            try:
                spec_content = read_text_upload_limited(
                    file, max_bytes=settings.PARSE_SPEC_MAX_BYTES
                )
            except UploadTooLargeError:
                return make_response(
                    jsonify(
                        {
                            "success": False,
                            "message": upload_limit_message(
                                settings.PARSE_SPEC_MAX_BYTES
                            ),
                        }
                    ),
                    413,
                )
            except UnicodeDecodeError:
                return make_response(
                    jsonify({"success": False, "message": "Invalid file encoding"}), 400
                )
        elif request.is_json:
            data = request.get_json()
            spec_content = data.get("spec_content", "")
        else:
            return make_response(
                jsonify({"success": False, "message": "No spec provided"}), 400
            )
        if (
            not isinstance(spec_content, str)
            or len(spec_content.encode("utf-8")) > settings.PARSE_SPEC_MAX_BYTES
        ):
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": upload_limit_message(
                            settings.PARSE_SPEC_MAX_BYTES
                        ),
                    }
                ),
                413,
            )
        if not spec_content or not spec_content.strip():
            return make_response(
                jsonify({"success": False, "message": "Empty spec content"}), 400
            )
        try:
            metadata, actions = parse_spec(spec_content)
            return make_response(
                jsonify(
                    {
                        "success": True,
                        "metadata": metadata,
                        "actions": actions,
                    }
                ),
                200,
            )
        except ValueError as e:
            current_app.logger.error(f"Spec validation error: {e}")
            return make_response(jsonify({"success": False, "error": "Invalid specification format"}), 400)
        except Exception as err:
            current_app.logger.error(f"Error parsing spec: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to parse specification"}), 500)


@tools_ns.route("/artifact/<artifact_id>")
class GetArtifact(Resource):
    @api.doc(description="Get artifact data by artifact ID. Returns all todos for the tool when fetching a todo artifact.")
    def get(self, artifact_id: str):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user_id = decoded_token.get("sub")

        try:
            with db_readonly() as conn:
                notes_repo = NotesRepository(conn)
                todos_repo = TodosRepository(conn)

                # Artifact IDs may be PG UUIDs (post-cutover) or legacy
                # Mongo ObjectIds embedded in older conversation history.
                # Both repos' ``get_any`` handles the id-shape branching
                # internally so a non-UUID input never reaches
                # ``CAST(:id AS uuid)`` (which would poison the readonly
                # transaction and break the fallback below).
                note_doc = notes_repo.get_any(artifact_id, user_id)

                if note_doc:
                    content = note_doc.get("note", "") or note_doc.get("content", "")
                    line_count = len(content.split("\n")) if content else 0
                    updated = note_doc.get("updated_at")
                    artifact = {
                        "artifact_type": "note",
                        "data": {
                            "content": content,
                            "line_count": line_count,
                            "updated_at": (
                                updated.isoformat()
                                if hasattr(updated, "isoformat")
                                else updated
                            ),
                        },
                    }
                    return make_response(
                        jsonify({"success": True, "artifact": artifact}), 200
                    )

                todo_doc = todos_repo.get_any(artifact_id, user_id)
                if todo_doc:
                    tool_id = todo_doc.get("tool_id")
                    all_todos = todos_repo.list_for_tool(user_id, tool_id) if tool_id else []
                    items = []
                    open_count = 0
                    completed_count = 0
                    for t in all_todos:
                        # PG ``todos`` stores a ``completed BOOLEAN`` column;
                        # the legacy Mongo shape used a ``status`` string.
                        # Keep the response shape stable by translating here.
                        status = "completed" if t.get("completed") else "open"
                        if status == "open":
                            open_count += 1
                        else:
                            completed_count += 1
                        created = t.get("created_at")
                        updated = t.get("updated_at")
                        items.append({
                            "todo_id": t.get("todo_id"),
                            "title": t.get("title", ""),
                            "status": status,
                            "created_at": (
                                created.isoformat()
                                if hasattr(created, "isoformat")
                                else created
                            ),
                            "updated_at": (
                                updated.isoformat()
                                if hasattr(updated, "isoformat")
                                else updated
                            ),
                        })
                    artifact = {
                        "artifact_type": "todo_list",
                        "data": {
                            "items": items,
                            "total_count": len(items),
                            "open_count": open_count,
                            "completed_count": completed_count,
                        },
                    }
                    return make_response(
                        jsonify({"success": True, "artifact": artifact}), 200
                    )

                # Generalized document/file artifacts live in the
                # ``artifacts`` store, authorized by their parent (not user_id).
                # Shape-gate the UUID lookup so a non-UUID id (legacy note/todo
                # ObjectId already handled above) never reaches the CAST that
                # would poison this read-only transaction.
                artifact_doc = None
                if looks_like_uuid(artifact_id):
                    artifacts_repo = ArtifactsRepository(conn)
                    artifact_doc = artifacts_repo.get_artifact(artifact_id)
                if artifact_doc and authorize_artifact(
                    conn, artifact_doc, Principal(user_id=user_id)
                ):
                    current = artifacts_repo.get_version(
                        artifact_id, artifact_doc.get("current_version")
                    )
                    artifact = {
                        "artifact_type": (
                            "document"
                            if artifact_doc.get("kind") != "file"
                            else "file"
                        ),
                        "data": {
                            "id": str(artifact_doc.get("id")),
                            "kind": artifact_doc.get("kind"),
                            "title": artifact_doc.get("title"),
                            "current_version": artifact_doc.get("current_version"),
                            "mime_type": current.get("mime_type") if current else None,
                            "filename": current.get("filename") if current else None,
                            "size": current.get("size") if current else None,
                            "download_url": (
                                f"/api/artifacts/{artifact_id}/download"
                                if current and current.get("storage_path")
                                else None
                            ),
                        },
                    }
                    return make_response(
                        jsonify({"success": True, "artifact": artifact}), 200
                    )
        except Exception as err:
            current_app.logger.error(
                f"Error retrieving artifact: {err}", exc_info=True
            )
            return make_response(jsonify({"success": False}), 400)

        return make_response(
            jsonify({"success": False, "message": "Artifact not found"}), 404
        )
