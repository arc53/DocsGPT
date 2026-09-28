"""Read / write classification and permissions for connection-backed tools.

Every action a connection's tool offers is either a *read* (it only looks
something up) or a *write* (it changes or sends something). Reads default to
"Always allow"; writes default to "Needs approval". The permission is stored
on the action itself: ``active`` off means "Off", ``require_approval`` means
"Needs approval", neither means "Always allow".
"""

from __future__ import annotations

from typing import Optional

ACCESS_READ = "read"
ACCESS_WRITE = "write"

PERMISSION_ALWAYS = "always"
PERMISSION_ASK = "ask"
PERMISSION_OFF = "off"
PERMISSIONS = (PERMISSION_ALWAYS, PERMISSION_ASK, PERMISSION_OFF)

_READ_WORDS = ("search", "query", "find", "list", "get", "read", "fetch", "lookup", "describe", "retrieve")


def action_access(tool_name: Optional[str], action: dict) -> str:
    """Whether ``action`` reads or writes.

    Order of evidence: an explicit ``access`` on the action metadata, MCP tool
    annotations (``readOnlyHint`` / ``destructiveHint``), the HTTP method of an
    API tool action, then the action's name.

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
    name = (action.get("name") or "").lower()
    return ACCESS_READ if any(word in name for word in _READ_WORDS) else ACCESS_WRITE


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


def apply_default_permissions(tool_name: Optional[str], actions: list[dict]) -> list[dict]:
    """Stamp ``access`` on each action and default writes to needing approval."""
    stamped = []
    for action in actions:
        access = action_access(tool_name, action)
        updated = {**action, "access": access}
        if access == ACCESS_WRITE:
            updated["require_approval"] = True
        stamped.append(updated)
    return stamped
