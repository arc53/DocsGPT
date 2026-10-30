"""Readable names for tools in Activity: what the Add Tool catalog calls them.

A background job records the tool's module name (``code_executor``,
``mcp_tool``). The catalog's name is the first line of the tool class's
docstring; a user's own tool row may carry a custom name. A user with one
tool of a kind gets that tool's own name; with several (two API tools, two
MCP servers) the kind's catalog name, since the job doesn't say which one ran.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import re
from typing import Dict, Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

# A tool name becomes a module path, so only a plain identifier is imported.
_MODULE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


_ACRONYMS = {"api": "API", "mcp": "MCP", "pdf": "PDF", "docx": "DOCX"}

# Names found so far; a failed lookup isn't kept, so a module that couldn't be
# imported yet (an import cycle at start-up) is tried again next time.
_FOUND: Dict[str, str] = {}


def _fallback(tool_name: str) -> str:
    """A readable name from a tool's own: ``web_search`` becomes "Web search", ``mcp_tool`` "MCP tool"."""
    words = [w for w in tool_name.split("_") if w]
    if not words:
        return tool_name
    words = [_ACRONYMS.get(w, w) for w in words]
    first = words[0] if words[0].isupper() else words[0].capitalize()
    return " ".join([first, *words[1:]])


def catalog_name(tool_name: str) -> str:
    """The catalog's name for a tool kind, e.g. ``code_executor`` → "Code Executor".

    Args:
        tool_name: The tool's module name.

    Returns:
        The first docstring line of its tool class, or the name tidied up.
    """
    if not tool_name or not _MODULE_NAME.match(tool_name):
        return _fallback(tool_name or "")
    if tool_name in _FOUND:
        return _FOUND[tool_name]
    try:
        from docsgpt.agents.tools.base import Tool

        module = importlib.import_module(f"docsgpt.agents.tools.{tool_name}")
    except Exception:
        return _fallback(tool_name)
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, Tool) and obj is not Tool and obj.__module__ == module.__name__:
            first = (obj.__doc__ or "").strip().split("\n", 1)[0].strip()
            if first:
                _FOUND[tool_name] = first
                return first
    return _fallback(tool_name)


def tool_labels(conn: Connection, user_id: str, names: Iterable[str]) -> Dict[str, str]:
    """Readable names for the tool kinds in ``names``, as this user knows them.

    Args:
        conn: A read-only connection.
        user_id: Whose tools.
        names: Tool module names.

    Returns:
        ``{tool_name: label}`` for every name given.
    """
    wanted = sorted({n for n in names if n})
    if not wanted:
        return {}
    rows = conn.execute(
        text(
            """
            SELECT name,
                   COALESCE(NULLIF(custom_name, ''), NULLIF(display_name, '')) AS label,
                   COUNT(*) OVER (PARTITION BY name) AS kinds
            FROM user_tools
            WHERE user_id = :user_id AND name = ANY(:names)
            """
        ),
        {"user_id": user_id, "names": wanted},
    ).fetchall()
    own = {r[0]: r[1] for r in rows if r[2] == 1 and r[1]}
    return {name: own.get(name) or catalog_name(name) for name in wanted}
