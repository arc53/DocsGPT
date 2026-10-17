"""Read / write classification and permissions for connection-backed tools.

Every action a connection's tool offers is either a *read* (it only looks
something up) or a *write* (it changes or sends something). Reads default to
"Always allow"; writes default to "Needs approval". The permission is stored
on the action itself: ``active`` off means "Off", ``require_approval`` means
"Needs approval", neither means "Always allow".
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Optional

ACCESS_READ = "read"
ACCESS_WRITE = "write"

PERMISSION_ALWAYS = "always"
PERMISSION_ASK = "ask"
PERMISSION_OFF = "off"
PERMISSIONS = (PERMISSION_ALWAYS, PERMISSION_ASK, PERMISSION_OFF)

_READ_WORDS = frozenset(
    ("search", "query", "find", "list", "get", "read", "view", "fetch", "lookup", "describe", "retrieve")
)
# A name holding any of these is a write even when it also holds a read word
# (``get_or_create_page``, ``search_and_replace``).
_WRITE_WORDS = frozenset((
    "create", "update", "delete", "remove", "set", "send", "post", "put", "patch", "write", "add", "insert",
    "upsert", "append", "replace", "edit", "modify", "rename", "move", "copy", "upload", "save", "submit",
    "publish", "share", "invite", "assign", "archive", "restore", "reset", "clear", "purge", "drop", "execute",
    "run", "invoke", "trigger", "start", "stop", "cancel", "close", "merge", "approve", "reject", "reply",
    "comment", "mark", "enable", "disable", "grant", "revoke", "transfer", "import", "sync", "lock", "unlock",
))
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_WORD = re.compile(r"[^A-Za-z0-9]+")


def _name_words(name: str) -> set[str]:
    """The lower-cased words of an action name (``snake``, ``kebab``, ``camelCase``)."""
    return {word.lower() for word in _NON_WORD.split(_CAMEL_BOUNDARY.sub(" ", name)) if word}


def action_access(tool_name: Optional[str], action: dict) -> str:
    """Whether ``action`` reads or writes.

    Order of evidence: an explicit ``access`` on the action metadata, MCP tool
    annotations (``readOnlyHint`` / ``destructiveHint``), the HTTP method of an
    API tool action, then the action's name: a read only when one of its
    words is a read verb and none is a write verb.

    Args:
        tool_name: The ``user_tools`` name the action belongs to.
        action: One entry of the tool's ``actions``.

    Returns:
        ``read`` or ``write``.
    """
    access = action.get("access")
    if access in (ACCESS_READ, ACCESS_WRITE):
        return access
    annotations = action.get("annotations") or {}
    if isinstance(annotations, dict):
        if annotations.get("readOnlyHint") is True:
            return ACCESS_READ
        if annotations.get("destructiveHint") is True or annotations.get("readOnlyHint") is False:
            return ACCESS_WRITE
    method = (action.get("method") or "").upper()
    if tool_name == "api_tool" and method:
        return ACCESS_READ if method in ("GET", "HEAD", "OPTIONS") else ACCESS_WRITE
    words = _name_words(action.get("name") or "")
    return ACCESS_READ if words & _READ_WORDS and not words & _WRITE_WORDS else ACCESS_WRITE


def action_permission(action: dict) -> str:
    """The action's permission: ``always``, ``ask`` or ``off``."""
    if action.get("active") is False:
        return PERMISSION_OFF
    if action.get("require_approval"):
        return PERMISSION_ASK
    return PERMISSION_ALWAYS


def apply_permission(action: dict, permission: str) -> dict:
    """Return ``action`` with ``permission`` written onto its flags."""
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    updated = dict(action)
    updated["active"] = permission != PERMISSION_OFF
    updated["require_approval"] = permission == PERMISSION_ASK
    return updated


def apply_default_permissions(
    tool_name: Optional[str], actions: list[dict], enabled: Collection[str] = (),
) -> list[dict]:
    """Stamp ``access`` on each action and default writes to needing approval.

    Args:
        tool_name: The ``user_tools`` name the actions belong to.
        actions: The actions to stamp.
        enabled: When given, the only actions that start on; the rest start
            "Off". An MCP preset with more tools than a model takes in one
            request (Alpha Vantage's 133) names its core ones here.

    Returns:
        The stamped actions.
    """
    stamped = []
    for action in actions:
        access = action_access(tool_name, action)
        updated = {**action, "access": access}
        if access == ACCESS_WRITE:
            updated["require_approval"] = True
        if enabled and action.get("name") not in enabled:
            updated["active"] = False
        stamped.append(updated)
    return stamped


def tool_actions(tool: dict) -> list[dict]:
    """A tool row's actions, each carrying its ``name``.

    An API tool keeps its actions under ``config["actions"]`` keyed by name;
    every other tool lists them in ``actions``.
    """
    if tool.get("name") == "api_tool":
        stored = (tool.get("config") or {}).get("actions") or {}
        return [{**(action or {}), "name": name} for name, action in stored.items()]
    return [action for action in tool.get("actions") or [] if isinstance(action, dict)]


# Where an API tool keeps the values it sends: header and query values are
# the owner's (sealed per action, flagged ``has_value``; legacy rows hold them
# in plain ``value``). Mirrors ``tool_executor.API_TOOL_SECRET_SECTIONS``.
_API_TOOL_SECRET_SECTIONS = ("headers", "query_params")


def _api_action_sends_credentials(action: dict) -> bool:
    """Whether an API tool action sends a header or query value the owner stored."""
    for section in _API_TOOL_SECRET_SECTIONS:
        block = action.get(section)
        props = block.get("properties") if isinstance(block, dict) else None
        for spec in (props or {}).values():
            if isinstance(spec, dict) and (spec.get("has_value") or spec.get("value") not in (None, "")):
                return True
    return False


def holds_owner_credentials(tool: dict, action_name: Optional[str] = None) -> bool:
    """Whether ``tool`` (or its ``action_name``) acts with credentials its owner stored.

    A connection's account, a stored secret, an MCP server the owner signed
    in to, or an API tool action that sends a header or query value the
    owner saved (a key, a token). Anyone running it acts as the owner there,
    whoever they are. An API tool action that sends nothing stored does not.

    Args:
        tool: A ``user_tools`` row.
        action_name: One action to judge; None judges the tool as a whole.

    Returns:
        True when the tool (or that action) runs on the owner's credentials.
    """
    config = tool.get("config") or {}
    if tool.get("connection_id") or config.get("encrypted_credentials"):
        return True
    if tool.get("name") == "api_tool":
        actions = config.get("actions") or {}
        if action_name is not None:
            return _api_action_sends_credentials(actions.get(action_name) or {})
        return any(_api_action_sends_credentials(action or {}) for action in actions.values())
    return tool.get("name") == "mcp_tool" and (config.get("auth_type") or "none") != "none"


def owner_credential_writes(tool: dict) -> list[str]:
    """Names of the tool's write actions that run on its owner's credentials.

    These are what someone who can't approve for the owner (an API-key or
    widget caller, a public-link user) may run only when the owner allows
    them in the agent's API write allowlist.

    Args:
        tool: A ``user_tools`` row.

    Returns:
        Action names, empty when the tool holds no owner credentials.
    """
    return [
        action["name"] for action in tool_actions(tool)
        if action.get("name") and action.get("active") is not False
        and action_access(tool.get("name"), action) == ACCESS_WRITE
        and holds_owner_credentials(tool, action["name"])
    ]
