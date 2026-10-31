"""Which agents use a tool, prompt or source: the ``used_by`` field of the Workspace lists.

An agent uses a resource when running it would reach that resource:

- A classic agent (any ``agent_type`` but ``workflow``) through its own
  columns: ``agents.tools`` (a JSON list of tool ids, synthetic uuid5 ids of
  default and builtin tools included), ``agents.prompt_id``,
  ``agents.source_id`` and ``agents.extra_source_ids``. With no
  ``prompt_id``, ``agents.prompt_preset`` names the preset it runs
  (``creative`` or ``strict``), and NULL there too is ``default``.
- A workflow agent through the agent nodes of its workflow's current graph
  version (``workflows.current_graph_version``): their ``tools`` and
  ``sources`` lists. Workflow nodes carry their prompt inline, so a workflow
  agent never uses a prompt, and its classic columns are ignored.

Only agents the caller can open are listed: their own and the ones a team
shares with them (narrowed further by a token's agent allowlist; a token
without ``agents:read`` lists none). Each listed agent says whether the caller
may open its editor (``can_edit``, the agent action ``view``). For a resource
the caller may delete (the owner, or an editor the owner let delete), the
agents they can't open (a teammate's) are counted in ``others`` instead, so
they know a delete would break them; for any other resource ``others`` is
always 0, so nothing is revealed about agents outside the caller's reach.
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import allowed_actions, settings_many
from docsgpt.api.user.team_sharing import visible_with_access
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import STORED_PROMPT_PRESETS

UsageKind = Literal["tool", "prompt", "source"]

#: The ``used_by`` of a resource no agent uses. Compare against it; never mutate it.
EMPTY_USAGE: dict = {"agents": [], "others": 0}

#: The prompt preset an agent with no ``prompt_id`` and no ``prompt_preset`` runs with.
DEFAULT_PROMPT = "default"

#: Every preset an agent can run: the default and the stored ones.
PROMPT_PRESETS = frozenset({DEFAULT_PROMPT, *STORED_PROMPT_PRESETS})

# A classic agent is anything but a workflow agent.
_CLASSIC = "a.agent_type IS DISTINCT FROM 'workflow'"

_CLASSIC_TOOLS_SQL = f"""
    SELECT a.id::text AS agent_id, a.name, a.user_id, a.agent_type, r.ref
    FROM agents a
    CROSS JOIN LATERAL jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(a.tools) = 'array' THEN a.tools ELSE '[]'::jsonb END
    ) AS r(ref)
    WHERE {_CLASSIC} AND a.tools ?| CAST(:ids AS text[])
      AND r.ref = ANY(CAST(:ids AS text[]))
"""

_CLASSIC_SOURCES_SQL = f"""
    SELECT a.id::text AS agent_id, a.name, a.user_id, a.agent_type, s.sid::text AS ref
    FROM agents a
    CROSS JOIN LATERAL unnest(array_append(a.extra_source_ids, a.source_id)) AS s(sid)
    WHERE {_CLASSIC}
      AND (a.source_id = ANY(CAST(:ids AS uuid[])) OR a.extra_source_ids && CAST(:ids AS uuid[]))
      AND s.sid = ANY(CAST(:ids AS uuid[]))
"""

_CLASSIC_PROMPTS_SQL = f"""
    SELECT a.id::text AS agent_id, a.name, a.user_id, a.agent_type,
           COALESCE(a.prompt_id::text, a.prompt_preset, '{DEFAULT_PROMPT}') AS ref
    FROM agents a
    WHERE {_CLASSIC}
      AND (a.prompt_id = ANY(CAST(:ids AS uuid[]))
           OR (a.prompt_id IS NULL
               AND COALESCE(a.prompt_preset, '{DEFAULT_PROMPT}') = ANY(CAST(:presets AS text[]))
               AND (a.user_id = :user_id OR a.id = ANY(CAST(:visible AS uuid[])))))
"""

# Agent nodes of each workflow agent's current graph version.
_WORKFLOW_SQL = """
    SELECT a.id::text AS agent_id, a.name, a.user_id, a.agent_type, lower(r.ref) AS ref
    FROM agents a
    JOIN workflows w ON w.id = a.workflow_id
    JOIN workflow_nodes n ON n.workflow_id = w.id AND n.graph_version = w.current_graph_version
    CROSS JOIN LATERAL jsonb_array_elements_text(
        CASE WHEN jsonb_typeof(n.config -> CAST(:key AS text)) = 'array'
             THEN n.config -> CAST(:key AS text) ELSE '[]'::jsonb END
    ) AS r(ref)
    WHERE a.agent_type = 'workflow' AND n.node_type = 'agent'
      AND lower(r.ref) = ANY(CAST(:ids AS text[]))
"""

_WORKFLOW_KEY = {"tool": "tools", "source": "sources"}


def empty_usage() -> dict:
    """A fresh ``used_by`` for a resource no agent uses.

    Returns:
        dict: ``{"agents": [], "others": 0}``.
    """
    return {"agents": [], "others": 0}


def is_in_use(usage: Optional[dict]) -> bool:
    """Whether a ``used_by`` names any agent, listed or counted in ``others``.

    Args:
        usage: A ``used_by`` value, or None.

    Returns:
        bool: True when some agent uses the resource.
    """
    return bool(usage) and (bool(usage.get("agents")) or usage.get("others", 0) > 0)


def attach_used_by(
    conn: Connection,
    user_id: str,
    kind: UsageKind,
    items: list[dict],
    *,
    deletable_ids: Iterable[str],
    agent_allowlist: Optional[set[str]] = None,
) -> list[dict]:
    """Set ``used_by`` on every listed item, from one :func:`used_by_many` call.

    Args:
        conn: An open connection.
        user_id: The caller.
        kind: ``tool``, ``prompt`` or ``source``.
        items: The rows of a listing, each with an ``id``; changed in place.
        deletable_ids: The ids among them the caller may delete (see :func:`deletable_ids_of`).
        agent_allowlist: A token's agent allowlist, or None.

    Returns:
        list[dict]: ``items``.
    """
    usage = used_by_many(
        conn, user_id, kind, [str(item["id"]) for item in items],
        deletable_ids=deletable_ids, agent_allowlist=agent_allowlist,
    )
    for item in items:
        item["used_by"] = usage.get(str(item["id"])) or empty_usage()
    return items


def deletable_ids_of(items: Iterable[dict]) -> list[str]:
    """The ids of listed rows whose ``allowed_actions`` include ``delete``.

    Args:
        items: Listing rows carrying ``id`` and the access payload
            (``allowed_actions``); presets without it never count.

    Returns:
        list[str]: The ids the caller may delete.
    """
    return [str(item["id"]) for item in items if "delete" in (item.get("allowed_actions") or ())]


def deletable_row_ids(
    conn: Connection, user_id: str, kind: UsageKind, rows: Iterable[dict], team_shared: dict[str, str]
) -> list[str]:
    """The ids among raw resource rows the caller may delete, for listings without the access payload.

    Args:
        conn: An open connection.
        user_id: The caller.
        kind: ``tool``, ``prompt`` or ``source``.
        rows: Resource rows with ``id`` and ``user_id``.
        team_shared: ``resource_id -> strongest team access`` for the caller.

    Returns:
        list[str]: Owned ids, plus shared ids whose role and owner switches allow ``delete``.
    """
    owned: list[str] = []
    shared: list[str] = []
    for row in rows:
        (owned if str(row.get("user_id")) == str(user_id) else shared).append(str(row["id"]))
    if not shared:
        return owned
    switches = settings_many(conn, kind, shared)
    return owned + [
        rid for rid in shared
        if "delete" in allowed_actions(kind, team_shared.get(rid), switches.get(rid.lower()))
    ]


def _key(resource_id: str) -> str:
    """The form a resource id is matched in: a lower-case UUID, or the id as given."""
    value = str(resource_id).strip()
    return value.lower() if looks_like_uuid(value) else value


def _usage_rows(
    conn: Connection, kind: UsageKind, uuid_ids: list[str], user_id: str, team_agents: list[str], presets: list[str]
) -> list:
    """Every ``(agent_id, name, user_id, agent_type, ref)`` naming one of the ids, whoever owns the agent."""
    rows: list = []
    if kind == "prompt":
        if uuid_ids or presets:
            # A preset has no owner, so only agents the caller can open count.
            rows.extend(
                conn.execute(
                    text(_CLASSIC_PROMPTS_SQL),
                    {"ids": uuid_ids, "presets": presets, "user_id": user_id, "visible": team_agents},
                ).fetchall()
            )
        return rows
    if not uuid_ids:
        return rows
    classic = _CLASSIC_TOOLS_SQL if kind == "tool" else _CLASSIC_SOURCES_SQL
    rows.extend(conn.execute(text(classic), {"ids": uuid_ids}).fetchall())
    rows.extend(conn.execute(text(_WORKFLOW_SQL), {"ids": uuid_ids, "key": _WORKFLOW_KEY[kind]}).fetchall())
    return rows


def _collect(
    conn: Connection,
    user_id: str,
    kind: UsageKind,
    resource_ids: Iterable[str],
    deletable_ids: Iterable[str],
    agent_allowlist: Optional[set[str]],
) -> tuple[dict[str, str], dict[str, dict[str, tuple[str, str, bool]]], dict[str, set[str]]]:
    """Who uses each resource: the agents the caller can open, and the hidden ones of what they may delete.

    Returns:
        tuple: ``keys`` (each id given → its match key), ``listed`` (key →
        ``{agent_id: (name, agent_type, can_edit)}``) and ``hidden`` (key →
        agent ids the caller can't open, for deletable keys only).
    """
    keys = {str(rid): _key(rid) for rid in resource_ids}
    wanted = set(keys.values())
    listed: dict[str, dict[str, tuple[str, str, bool]]] = {k: {} for k in wanted}
    hidden: dict[str, set[str]] = {k: set() for k in wanted}
    deletable = {_key(rid) for rid in deletable_ids}
    uuid_ids = sorted(k for k in wanted if looks_like_uuid(k))
    presets = sorted(wanted & PROMPT_PRESETS) if kind == "prompt" else []
    if not uuid_ids and not presets:
        return keys, listed, hidden

    team_access = visible_with_access(conn, user_id, "agent")
    team_agents = sorted(team_access)

    def _can_open(agent_id: str, owner: str) -> bool:
        if agent_allowlist is not None and agent_id not in agent_allowlist:
            return False
        return owner == user_id or agent_id in team_access

    shared_listed: set[str] = set()
    for agent_id, name, owner, agent_type, ref in _usage_rows(conn, kind, uuid_ids, user_id, team_agents, presets):
        ref_key = _key(ref)
        if ref_key not in wanted:
            continue
        if _can_open(agent_id, owner):
            listed[ref_key][agent_id] = (name, agent_type or "classic", owner == user_id)
            if owner != user_id:
                shared_listed.add(agent_id)
        elif ref_key in deletable:
            hidden[ref_key].add(agent_id)
    if shared_listed:
        # A team agent opens in its editor when the caller's role there may ``view`` it.
        switches = settings_many(conn, "agent", shared_listed)
        editable = {
            agent_id for agent_id in shared_listed
            if "view" in allowed_actions("agent", team_access.get(agent_id), switches.get(agent_id))
        }
        for agents in listed.values():
            for agent_id, (name, agent_type, can_edit) in agents.items():
                if agent_id in editable:
                    agents[agent_id] = (name, agent_type, True)
    return keys, listed, hidden


def _usage(listed: dict[str, tuple[str, str, bool]], hidden: set[str]) -> dict:
    """A ``used_by`` from the agents listed and the hidden agent ids, agents sorted by name."""
    agents = sorted(listed.items(), key=lambda item: ((item[1][0] or "").casefold(), item[0]))
    return {
        "agents": [
            {"id": agent_id, "name": name, "agent_type": agent_type, "can_edit": can_edit}
            for agent_id, (name, agent_type, can_edit) in agents
        ],
        "others": len(hidden - listed.keys()),
    }


def used_by_many(
    conn: Connection,
    user_id: str,
    kind: UsageKind,
    resource_ids: Iterable[str],
    *,
    deletable_ids: Iterable[str],
    agent_allowlist: Optional[set[str]] = None,
) -> dict[str, dict]:
    """Map each resource id to the agents that use it, in a fixed number of queries.

    Args:
        conn: An open connection.
        user_id: The caller.
        kind: ``tool``, ``prompt`` or ``source``.
        resource_ids: The ids on the list being built. Prompt presets go in by
            name (``default``, ``creative``, ``strict``); the synthetic ids of
            default and builtin tools match like any other tool id.
        deletable_ids: Which of ``resource_ids`` the caller may delete; only
            those get an ``others`` count.
        agent_allowlist: A token's agent allowlist (canonical ids), or None.
            Agents outside it are treated as ones the caller can't open.

    Returns:
        dict[str, dict]: ``{resource_id: {"agents": [{"id", "name", "agent_type", "can_edit"}], "others": n}}``
        for every id given, agents sorted by name.
    """
    keys, listed, hidden = _collect(conn, user_id, kind, resource_ids, deletable_ids, agent_allowlist)
    return {rid: _usage(listed[key], hidden[key]) for rid, key in keys.items()}


def combined_usage(
    conn: Connection,
    user_id: str,
    kind: UsageKind,
    resource_ids: Iterable[str],
    *,
    deletable_ids: Iterable[str],
    agent_allowlist: Optional[set[str]] = None,
) -> dict:
    """One ``used_by`` for a set of resources: every agent that uses any of them, counted once.

    Summing each resource's ``others`` would count a teammate's agent once per
    resource it uses; this unions the agent ids first, so a bulk delete can
    say how many agents lose something.

    Args:
        conn: An open connection.
        user_id: The caller.
        kind: ``tool``, ``prompt`` or ``source``.
        resource_ids: The resources, as for :func:`used_by_many`.
        deletable_ids: Which of them the caller may delete; only those add to ``others``.
        agent_allowlist: A token's agent allowlist (canonical ids), or None.

    Returns:
        dict: ``{"agents": [{"id", "name", "agent_type", "can_edit"}], "others": n}``.
    """
    _, listed, hidden = _collect(conn, user_id, kind, resource_ids, deletable_ids, agent_allowlist)
    all_listed: dict[str, tuple[str, str, bool]] = {}
    for agents in listed.values():
        all_listed.update(agents)
    all_hidden: set[str] = set().union(*hidden.values()) if hidden else set()
    return _usage(all_listed, all_hidden)
