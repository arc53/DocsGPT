"""Default chat tools — config-free tools on by default in chats."""

from __future__ import annotations

import importlib
import inspect
import logging
import uuid
from typing import Any, Dict, List, Optional

from application.core.settings import settings

logger = logging.getLogger(__name__)

# Fixed namespace — never regenerate; produced ids are persisted.
_DEFAULT_TOOL_NAMESPACE = uuid.UUID("6b1d3f2a-9c84-4d17-bf6e-2a0c5e8d4471")

# Tool names whose storage tables FK ``tool_id`` to ``user_tools.id``;
# a synthetic id has no row, so a write would FK-violate. Schema-rot
# guard: ``tests.agents.test_default_tools.TestFkBoundToolsIsInSync``.
_FK_BOUND_TOOLS = frozenset({"notes", "todo_list"})

# Tools that should NEVER appear in a headless run (scheduled or webhook).
# ``scheduler`` only makes sense from an interactive chat — letting an LLM
# call ``schedule_task`` from a scheduled run chains new schedules each fire,
# bounded only by ``SCHEDULE_MAX_PER_USER`` (cost foot-gun, confusing UX).
_HEADLESS_EXCLUDED_TOOLS = frozenset({"scheduler"})

# Agent-selectable builtins: hidden from the Add-Tool catalog (internal=True)
# and exposed to the agent picker via the same synthetic-id machinery as
# default tools. Names may overlap with DEFAULT_CHAT_TOOLS (e.g. ``scheduler``)
# — both registries share ``_DEFAULT_TOOL_NAMESPACE`` so the same uuid5
# resolves either way (the dual-flag row carries ``default`` AND ``builtin``).
# ``code_executor`` and ``artifact_generator`` are builtin-only (not default-on):
# both render/execute through a running sandbox runner, so they are opt-in per
# agent, but staying registered keeps their synthetic ids resolvable (an agent
# that enabled one never silently loses it) and keeps them in the agent picker.
BUILTIN_AGENT_TOOLS: tuple = (
    "scheduler",
    "read_document",
    "code_executor",
    "artifact_generator",
)

# Builtins shown only in the workflow-node tool picker, never the classic
# agent picker. The synthesized row carries ``workflow_only`` so the frontend
# can filter; execution still reuses the builtin synthetic-id path.
WORKFLOW_ONLY_BUILTINS = frozenset({"read_document"})

_tool_cache: Dict[str, Optional[Any]] = {}
_ids_cache: Dict[tuple, Dict[str, str]] = {}
_id_set_cache: Dict[tuple, frozenset] = {}
_loaded_cache: Dict[tuple, List[str]] = {}
_builtin_ids_cache: Dict[tuple, Dict[str, str]] = {}
_builtin_id_set_cache: Dict[tuple, frozenset] = {}
_builtin_loaded_cache: Dict[tuple, List[str]] = {}


def _load_tool(tool_name: str) -> Optional[Any]:
    """Return a metadata-only instance of a tool, or None if it has no class."""
    # Imports just the named module (not the whole package) — avoids the
    # circular import via ``mcp_tool`` → ``application.api.user``.
    if tool_name in _tool_cache:
        return _tool_cache[tool_name]

    from application.agents.tools.base import Tool

    instance: Optional[Any] = None
    try:
        module = importlib.import_module(f"application.agents.tools.{tool_name}")
    except ModuleNotFoundError:
        _tool_cache[tool_name] = None
        return None
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, Tool) and obj is not Tool:
            try:
                instance = obj({})
            except Exception:
                logger.warning(
                    "DEFAULT_CHAT_TOOLS entry %r failed to instantiate; skipping.",
                    tool_name,
                )
                instance = None
            break
    _tool_cache[tool_name] = instance
    return instance


def default_tool_id(tool_name: str) -> str:
    """Return the deterministic synthetic id for a default tool name."""
    return str(uuid.uuid5(_DEFAULT_TOOL_NAMESPACE, tool_name))


def default_tool_ids() -> Dict[str, str]:
    """Map each configured default-tool name to its synthetic id (memoized)."""
    key = tuple(settings.DEFAULT_CHAT_TOOLS)
    cached = _ids_cache.get(key)
    if cached is None:
        cached = {name: default_tool_id(name) for name in key}
        _ids_cache[key] = cached
    return cached


def is_default_tool_id(tool_id: Any) -> bool:
    """Return True if ``tool_id`` is a synthetic default-tool id."""
    if not tool_id:
        return False
    key = tuple(settings.DEFAULT_CHAT_TOOLS)
    cached = _id_set_cache.get(key)
    if cached is None:
        cached = frozenset(default_tool_ids().values())
        _id_set_cache[key] = cached
    return str(tool_id) in cached


def default_tool_name_for_id(tool_id: Any) -> Optional[str]:
    """Return the default-tool name for a synthetic id, or None."""
    target = str(tool_id) if tool_id else ""
    for name, synthetic_id in default_tool_ids().items():
        if synthetic_id == target:
            return name
    return None


def builtin_agent_tool_ids() -> Dict[str, str]:
    """Map each agent-selectable builtin to its synthetic id (memoized)."""
    key = tuple(BUILTIN_AGENT_TOOLS)
    cached = _builtin_ids_cache.get(key)
    if cached is None:
        cached = {name: default_tool_id(name) for name in key}
        _builtin_ids_cache[key] = cached
    return cached


def is_builtin_agent_tool_id(tool_id: Any) -> bool:
    """Return True if ``tool_id`` is an agent-selectable builtin synthetic id."""
    if not tool_id:
        return False
    key = tuple(BUILTIN_AGENT_TOOLS)
    cached = _builtin_id_set_cache.get(key)
    if cached is None:
        cached = frozenset(builtin_agent_tool_ids().values())
        _builtin_id_set_cache[key] = cached
    return str(tool_id) in cached


def builtin_agent_tool_name_for_id(tool_id: Any) -> Optional[str]:
    """Return the builtin tool name for a synthetic id, or None."""
    target = str(tool_id) if tool_id else ""
    for name, synthetic_id in builtin_agent_tool_ids().items():
        if synthetic_id == target:
            return name
    return None


def synthesized_tool_name_for_id(tool_id: Any) -> Optional[str]:
    """Return the tool name for any synthetic id (default or builtin), or None."""
    return default_tool_name_for_id(tool_id) or builtin_agent_tool_name_for_id(tool_id)


def is_synthesized_tool_id(tool_id: Any) -> bool:
    """Return True for any synthetic id (default chat or agent-builtin)."""
    return is_default_tool_id(tool_id) or is_builtin_agent_tool_id(tool_id)


def loaded_default_tools() -> List[str]:
    """Return configured default-tool names that resolve to a loaded tool."""
    # Silent + memoized — runs per request; the one-time skip notice
    # for unimplemented names lives in ``validate_default_chat_tools``.
    key = tuple(settings.DEFAULT_CHAT_TOOLS)
    cached = _loaded_cache.get(key)
    if cached is None:
        cached = [name for name in key if _load_tool(name) is not None]
        _loaded_cache[key] = cached
    return cached


def loaded_builtin_agent_tools() -> List[str]:
    """Return builtin agent-tool names that resolve to a loaded tool."""
    key = tuple(BUILTIN_AGENT_TOOLS)
    cached = _builtin_loaded_cache.get(key)
    if cached is None:
        cached = [name for name in key if _load_tool(name) is not None]
        _builtin_loaded_cache[key] = cached
    return cached


def validate_default_chat_tools() -> List[str]:
    """Validate ``DEFAULT_CHAT_TOOLS`` at startup; return the usable names."""
    skipped = [
        name for name in settings.DEFAULT_CHAT_TOOLS if _load_tool(name) is None
    ]
    if skipped:
        logger.debug(
            "DEFAULT_CHAT_TOOLS entries with no loaded tool, skipped: %s. "
            "Each activates automatically once its tool exists.",
            ", ".join(skipped),
        )
    usable = loaded_default_tools()
    for name in usable:
        if name in _FK_BOUND_TOOLS:
            raise ValueError(
                f"DEFAULT_CHAT_TOOLS entry {name!r} has a storage table "
                f"that foreign-keys tool_id to user_tools; a default tool "
                f"has a synthetic id with no user_tools row, so it would "
                f"fail at write time. It cannot be defaulted on."
            )
        requirements = _load_tool(name).get_config_requirements() or {}
        required = [
            key for key, spec in requirements.items()
            if isinstance(spec, dict) and spec.get("required")
        ]
        if required:
            raise ValueError(
                f"DEFAULT_CHAT_TOOLS entry {name!r} requires config "
                f"fields {required}; only config-free tools may be "
                "defaulted on."
            )
    if usable:
        logger.info("Default chat tools active: %s", ", ".join(usable))
    return usable


def _tool_display(tool_name: str) -> str:
    """Return the human-readable display name from the tool docstring."""
    tool = _load_tool(tool_name)
    doc = (tool.__doc__ or "").strip() if tool else ""
    first_line = doc.split("\n", 1)[0].strip() if doc else ""
    return first_line or tool_name


def _tool_description(tool_name: str) -> str:
    """Return the tool description (docstring lines after the first)."""
    tool = _load_tool(tool_name)
    doc = (tool.__doc__ or "").strip() if tool else ""
    parts = doc.split("\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def synthesize_default_tool(tool_name: str) -> Optional[Dict[str, Any]]:
    """Build an in-memory ``user_tools``-shaped row for a default tool."""
    tool = _load_tool(tool_name)
    if tool is None:
        return None
    synthetic_id = default_tool_id(tool_name)
    return {
        "id": synthetic_id,
        "_id": synthetic_id,
        "name": tool_name,
        "display_name": _tool_display(tool_name),
        "custom_name": "",
        "description": _tool_description(tool_name),
        "config": {},
        "config_requirements": {},
        "actions": tool.get_actions_metadata() or [],
        "status": True,
        "default": True,
    }


def synthesize_builtin_agent_tool(tool_name: str) -> Optional[Dict[str, Any]]:
    """Build an in-memory ``user_tools``-shaped row for a builtin agent tool."""
    tool = _load_tool(tool_name)
    if tool is None:
        return None
    synthetic_id = default_tool_id(tool_name)
    return {
        "id": synthetic_id,
        "_id": synthetic_id,
        "name": tool_name,
        "display_name": _tool_display(tool_name),
        "custom_name": "",
        "description": _tool_description(tool_name),
        "config": {},
        "config_requirements": {},
        "actions": tool.get_actions_metadata() or [],
        "status": True,
        "default": False,
        "builtin": True,
        "workflow_only": tool_name in WORKFLOW_ONLY_BUILTINS,
    }


def synthesize_tool_by_name(tool_name: str) -> Optional[Dict[str, Any]]:
    """Synthesize the row for any default or builtin tool name."""
    if tool_name in BUILTIN_AGENT_TOOLS:
        return synthesize_builtin_agent_tool(tool_name)
    return synthesize_default_tool(tool_name)


def disabled_default_tools(user_doc: Optional[Dict[str, Any]]) -> List[str]:
    """Return the user's opt-out list from ``tool_preferences``."""
    if not isinstance(user_doc, dict):
        return []
    prefs = user_doc.get("tool_preferences") or {}
    if not isinstance(prefs, dict):
        return []
    disabled = prefs.get("disabled_default_tools") or []
    if not isinstance(disabled, list):
        return []
    return [str(name) for name in disabled]


def synthesized_default_tools(
    user_doc: Optional[Dict[str, Any]] = None,
    *,
    headless: bool = False,
) -> List[Dict[str, Any]]:
    """Return synthesized default-tool rows for an agentless chat."""
    # Agent-bound chats must NOT call this — they resolve exactly
    # ``agents.tools``. Disabled defaults are dropped. ``headless=True``
    # additionally drops chat-only tools (e.g. ``scheduler``) so a scheduled
    # / webhook LLM can't re-schedule itself.
    disabled = set(disabled_default_tools(user_doc))
    rows: List[Dict[str, Any]] = []
    for name in loaded_default_tools():
        if name in disabled:
            continue
        if headless and name in _HEADLESS_EXCLUDED_TOOLS:
            continue
        row = synthesize_default_tool(name)
        if row is not None:
            rows.append(row)
    return rows


def is_headless_excluded_tool(tool_name: Optional[str]) -> bool:
    """Return True if ``tool_name`` must be hidden from headless runs."""
    return bool(tool_name) and tool_name in _HEADLESS_EXCLUDED_TOOLS


def default_tools_for_management(
    user_doc: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return every loaded default tool with its on/off ``status``."""
    # Unlike ``synthesized_default_tools`` (chat toolset), this keeps
    # disabled tools so the management UI can render their toggle.
    disabled = set(disabled_default_tools(user_doc))
    rows: List[Dict[str, Any]] = []
    for name in loaded_default_tools():
        row = synthesize_default_tool(name)
        if row is None:
            continue
        row["status"] = name not in disabled
        rows.append(row)
    return rows


def builtin_agent_tools_for_management() -> List[Dict[str, Any]]:
    """Return every loaded agent-builtin tool for the agent picker (no per-user state)."""
    rows: List[Dict[str, Any]] = []
    for name in loaded_builtin_agent_tools():
        row = synthesize_builtin_agent_tool(name)
        if row is None:
            continue
        rows.append(row)
    return rows


def resolve_tool_by_id(
    tool_id: Any,
    user: Optional[str],
    *,
    user_tools_repo: Any = None,
) -> Optional[Dict[str, Any]]:
    """Resolve a tool by id: default/builtin synthetic id, else user_tools row.

    Dual-registered tools (e.g. ``scheduler``) get both flags on the resolved
    row so callers can branch on either path without losing the discriminator.
    """
    default_name = default_tool_name_for_id(tool_id)
    builtin_name = builtin_agent_tool_name_for_id(tool_id)
    if default_name is not None and builtin_name is not None:
        row = synthesize_default_tool(default_name) or {}
        row["builtin"] = True
        return row or None
    if default_name is not None:
        return synthesize_default_tool(default_name)
    if builtin_name is not None:
        return synthesize_builtin_agent_tool(builtin_name)
    if user_tools_repo is None or not user:
        return None
    return user_tools_repo.get_any(str(tool_id), user)
