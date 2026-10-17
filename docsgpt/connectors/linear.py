"""Linear through its MCP server: what a sync can pick, and reading issues and documents.

Linear's hosted MCP server (``mcp.linear.app``) is its own OAuth issuer, and
the tokens it grants are for that server. Knowledge sync therefore reads
Linear through the same MCP tools the agents use (``list_issues``,
``get_issue``, ``list_comments``, ``list_documents``...), signed in with the
Linear connection, so one sign-in powers both and nobody registers an OAuth
app. Linear publishes no output schema for these tools, so records are read
defensively: a value may be a string or an object with a ``name``.
"""

from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator, Optional

from docsgpt.connectors import catalog

LINEAR_CONNECTOR = "mcp:linear"
LINEAR_MCP_URL = "https://mcp.linear.app/mcp"
# Enough for a team's working set; a sync is a full read, so it stays bounded.
MAX_ISSUES = 500
MAX_DOCUMENTS = 100
MAX_COMMENTS = 100
# Teams and projects offered in the picker.
MAX_PICKER_ITEMS = 250
PAGE_SIZE = 100
_MAX_PAGES = 50

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
_TRUNCATED = re.compile(r"\(truncated\b", re.IGNORECASE)
_LIST_KEYS = ("nodes", "items", "results", "data")
_PRIORITIES = {0: "No priority", 1: "Urgent", 2: "High", 3: "Medium", 4: "Low"}


class LinearSyncError(ValueError):
    """Linear's MCP server cannot do what the sync needs (a tool or filter is gone)."""


def mcp_url() -> str:
    """The Linear preset's MCP endpoint."""
    definition = catalog.get_definition(LINEAR_CONNECTOR)
    return (definition.mcp_url if definition and definition.mcp_url else None) or LINEAR_MCP_URL


# ---------------------------------------------------------------------------
# What a source syncs
# ---------------------------------------------------------------------------


def _truthy(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def _picked(values: Any, fields: tuple[str, ...]) -> list[dict]:
    picked: dict[str, dict] = {}
    for value in values if isinstance(values, list) else []:
        record = value if isinstance(value, dict) else {"id": value}
        item_id = str(record.get("id") or "").strip()
        if not item_id:
            continue
        current = picked.setdefault(item_id, {"id": item_id, **{f: "" for f in fields}})
        for field in fields:
            current[field] = current[field] or str(record.get(field) or "").strip()
    return list(picked.values())


def normalize_selection(items: Any) -> dict:
    """What a Linear source syncs, as it is stored in ``sources.remote_data``.

    Args:
        items: The wizard's choice (or a stored ``remote_data``, possibly as
            JSON): ``teams`` and ``projects`` as ids or ``{id, key, name}``
            records, ``include_comments`` (on unless turned off) and
            ``include_documents`` (the picked projects' documents).

    Returns:
        ``{teams: [{id, key, name}], projects: [{id, name}],
        include_comments, include_documents}``.

    Raises:
        ValueError: Nothing to sync was picked.
    """
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            items = {}
    items = items if isinstance(items, dict) else {}
    selection = {
        "teams": _picked(items.get("teams"), ("key", "name")),
        "projects": _picked(items.get("projects"), ("name",)),
        "include_comments": _truthy(items.get("include_comments"), True),
        "include_documents": _truthy(items.get("include_documents"), False),
    }
    if not selection["teams"] and not selection["projects"]:
        raise ValueError("Pick at least one Linear team or project")
    return selection


def selection_name(selection: dict) -> str:
    """``Linear · Engineering, Acme``: a source's default name, from what it syncs."""
    names = [item.get("name") for item in (*selection["teams"], *selection["projects"]) if item.get("name")]
    return f"Linear · {', '.join(names)}" if names else "Linear"


# ---------------------------------------------------------------------------
# Reading tool answers
# ---------------------------------------------------------------------------


def items_of(payload: Any, key: str) -> list[dict]:
    """The records in a list tool's answer: ``{key: [...]}``, a GraphQL ``nodes`` list or a bare list."""
    if isinstance(payload, list):
        found = payload
    elif isinstance(payload, dict):
        found = payload.get(key)
        if isinstance(found, dict):
            found = found.get("nodes")
        if not isinstance(found, list):
            found = next((payload[k] for k in _LIST_KEYS if isinstance(payload.get(k), list)), None)
        if found is None:
            lists = [value for value in payload.values() if isinstance(value, list)]
            found = lists[0] if len(lists) == 1 else []
    else:
        found = []
    return [item for item in found if isinstance(item, dict)]


def next_cursor(payload: Any) -> Optional[str]:
    """The cursor of the next page, or None on the last one."""
    if not isinstance(payload, dict):
        return None
    info = payload.get("pageInfo") if isinstance(payload.get("pageInfo"), dict) else payload
    if info.get("hasNextPage") is False:
        return None
    cursor = info.get("cursor") or info.get("nextCursor") or info.get("endCursor")
    return str(cursor) if cursor else None


def unwrap(payload: Any, key: str) -> dict:
    """A single record from a get tool's answer, bare or as ``{key: {...}}``."""
    if isinstance(payload, dict) and isinstance(payload.get(key), dict):
        return payload[key]
    return payload if isinstance(payload, dict) else {}


def name_of(value: Any) -> str:
    """A person's, state's or label's name, whether Linear sent a string or an object."""
    if isinstance(value, dict):
        value = value.get("name") or value.get("displayName") or value.get("title") or value.get("key")
    return str(value).strip() if value not in (None, "") else ""


def names_of(values: Any) -> list[str]:
    """Label names from a list of strings or objects (or a ``{nodes: [...]}``)."""
    if isinstance(values, dict):
        values = values.get("nodes")
    return [name for name in (name_of(value) for value in values or []) if name] if isinstance(values, list) else []


def priority_of(value: Any) -> str:
    """``High``: a priority given as a label, an object or Linear's 0-4 number."""
    if isinstance(value, dict):
        return str(value.get("name") or _PRIORITIES.get(value.get("value"), "")).strip()
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return _PRIORITIES.get(value, "") if value else ""
    return str(value or "").strip()


def issue_identifier(issue: dict) -> str:
    """``ENG-123``: the identifier people use, which list tools may send as the ``id``."""
    identifier = issue.get("identifier")
    if identifier:
        return str(identifier)
    item_id = str(issue.get("id") or "")
    return item_id if _IDENTIFIER.match(item_id) else ""


def is_truncated(text: Any) -> bool:
    """Whether Linear clipped a description in a list (it marks it ``(truncated…)``)."""
    return isinstance(text, str) and bool(_TRUNCATED.search(text))


# ---------------------------------------------------------------------------
# Calling the tools
# ---------------------------------------------------------------------------


async def _schema(session: Any, tool: str) -> dict:
    schema = await session.input_schema(tool)
    if schema is None:
        raise LinearSyncError(f"Linear's MCP server no longer offers {tool}")
    return schema


def argument(schema: dict, *names: str) -> Optional[str]:
    """The first of ``names`` the tool takes; the first name when the schema lists no properties."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return names[0]
    return next((name for name in names if name in properties), None)


def _page_size(schema: dict, name: str) -> int:
    spec = (schema.get("properties") or {}).get(name) if isinstance(schema, dict) else None
    maximum = spec.get("maximum") if isinstance(spec, dict) else None
    return min(PAGE_SIZE, int(maximum)) if isinstance(maximum, (int, float)) and maximum > 0 else PAGE_SIZE


async def paged(
    session: Any,
    tool: str,
    key: str,
    filters: dict,
    *,
    limit: int,
    extra: Optional[dict] = None,
) -> AsyncIterator[dict]:
    """Every record a list tool returns for ``filters``, page by page, up to ``limit``.

    Args:
        session: The open MCP session.
        tool: The list tool, e.g. ``list_issues``.
        key: Where its answer holds the records, e.g. ``issues``.
        filters: Filters the sync depends on, as ``{(name, alias...): value}``.
            A filter the tool does not take is an error, never dropped: a
            team's sync must not read the whole workspace.
        limit: Most records to yield.
        extra: Optional arguments, sent only when the tool takes them.

    Raises:
        LinearSyncError: The tool is gone or cannot apply a filter.
    """
    schema = await _schema(session, tool)
    arguments: dict = {}
    for names, value in filters.items():
        name = argument(schema, *names)
        if name is None:
            raise LinearSyncError(f"Linear's {tool} can no longer filter by {names[0]}")
        arguments[name] = value
    size_name = argument(schema, "limit", "first")
    if size_name:
        arguments[size_name] = _page_size(schema, size_name)
    properties = schema.get("properties") if isinstance(schema, dict) else None
    for name, value in (extra or {}).items():
        if isinstance(properties, dict) and name in properties:
            arguments[name] = value
    cursor_name = argument(schema, "cursor", "after")
    cursor: Optional[str] = None
    seen: set[str] = set()
    yielded = 0
    for _ in range(_MAX_PAGES):
        payload = await session.call(tool, {**arguments, **({cursor_name: cursor} if cursor else {})})
        for record in items_of(payload, key):
            yield record
            yielded += 1
            if yielded >= limit:
                return
        cursor = next_cursor(payload)
        if not cursor or not cursor_name or cursor in seen:
            return
        seen.add(cursor)


async def list_workspace(session: Any) -> dict:
    """The teams and projects a Linear account can see, for the sync picker.

    Returns:
        ``{teams: [{id, key, name}], projects: [{id, name, state, teams}]}``,
        each sorted by name.
    """
    teams = []
    async for team in paged(session, "list_teams", "teams", {}, limit=MAX_PICKER_ITEMS):
        if team.get("id"):
            teams.append({"id": str(team["id"]), "key": str(team.get("key") or ""),
                          "name": name_of(team.get("name")) or str(team.get("key") or team["id"])})
    projects = []
    async for project in paged(session, "list_projects", "projects", {}, limit=MAX_PICKER_ITEMS,
                               extra={"includeArchived": False}):
        if project.get("id"):
            project_teams = project.get("teams") or ([project["team"]] if project.get("team") else [])
            projects.append({
                "id": str(project["id"]),
                "name": name_of(project.get("name")) or str(project["id"]),
                "state": name_of(project.get("state") or project.get("status")),
                "teams": names_of(project_teams),
            })
    return {
        "teams": sorted(teams, key=lambda t: t["name"].lower()),
        "projects": sorted(projects, key=lambda p: p["name"].lower()),
    }
