"""Whether a workflow agent's stored graph may run where its builder doesn't watch it.

A draft's graph save checks the shape only, so a draft's stored graph may be
unfinished. Anything that runs an agent outside its builder (its key, a
webhook token, a schedule, its public link) runs that graph as it is, so
such an agent's saves run the full validation, and adding one of those to a
workflow agent first validates its stored graph in full.

It also says whether an agent's items may reach the people it is shared
with: someone else's tool or source never goes out through a key, link or
webhook, and a team's items reach only people who already reach them.
"""

from __future__ import annotations

from typing import Optional

from flask import jsonify, make_response
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    agent_refs,
    borrowed_refs,
    borrowed_refusal,
    can_use_ref,
    ref_names,
    resolve,
    resource_owner,
    sponsor_key,
)
from docsgpt.api.user.workflows.routes import (
    _node_folder_refs,
    _node_refs,
    stored_graph,
    validate_workflow_structure,
)
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.principal import canonical_team_id, is_principal_id, principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for


def graph_validation_failed(errors: list):
    """400 for a workflow graph that can't be saved, in both error shapes the clients read."""
    message = "Workflow validation failed"
    return make_response(jsonify({"success": False, "message": message, "error": message, "errors": errors}), 400)


def stored_graph_errors(conn, workflow_id, owner_id: str) -> list:
    """The full validation errors of a stored workflow graph, run as its owner.

    A draft save checks a graph's shape only, so a stored graph may be
    unfinished; a published agent must not start running one. A workflow the
    owner doesn't have is left to the caller's own checks.

    Args:
        conn: Open database connection.
        workflow_id: The workflow's id, or None.
        owner_id: The agent's owner, whose models the nodes run with.

    Returns:
        list: The errors, empty when the graph may run.
    """
    workflow = WorkflowsRepository(conn).get(str(workflow_id), owner_id) if workflow_id else None
    if workflow is None:
        return []
    nodes, edges = stored_graph(conn, workflow)
    return validate_workflow_structure(nodes, edges, user_id=owner_id)


def runs_outside_builder(conn, agent: dict) -> bool:
    """Whether something other than its builder can run an agent, whatever its status.

    Nothing on the run path checks ``status``: a key (kept when a published
    agent goes back to draft), an incoming webhook token, a live schedule or
    the public link (anyone holding it chats with the agent) each run the
    agent's current graph. A team grant doesn't count: teammates build a
    draft together, and a draft they share must keep saving unfinished.

    Args:
        conn: Open database connection.
        agent: The stored agent row.

    Returns:
        bool: True when the agent is published or one of those can run it.
    """
    if (
        agent.get("status") == "published"
        or agent.get("key")
        or agent.get("incoming_webhook_token")
        or agent.get("shared")
    ):
        return True
    return SchedulesRepository(conn).any_live_for_agent(str(agent["id"]))


def workflow_runs_elsewhere(conn, workflow_id, agent_id: str) -> bool:
    """Whether another agent linked to the workflow runs outside its builder.

    Since 1.1.0 a workflow belongs to one agent, but older rows can link two
    of an owner's agents to one; a graph saved through either is the graph
    both run.

    Args:
        conn: Open database connection.
        workflow_id: The workflow the save writes, or None.
        agent_id: The agent being saved, left out.

    Returns:
        bool: True when any other agent on the workflow runs outside its builder.
    """
    if not workflow_id:
        return False
    rows = conn.execute(
        text(
            "SELECT id, status, key, incoming_webhook_token, shared FROM agents "
            "WHERE workflow_id = CAST(:workflow_id AS uuid) AND id <> CAST(:agent_id AS uuid)"
        ),
        {"workflow_id": str(workflow_id), "agent_id": str(agent_id)},
    ).mappings().all()
    return any(runs_outside_builder(conn, dict(row)) for row in rows)


def unfinished_graph_errors(conn, agent: dict) -> list:
    """Why a workflow agent can't be given a way to run outside its builder.

    Args:
        conn: Open database connection.
        agent: The stored agent row.

    Returns:
        list: The full validation errors of its stored graph (a workflow agent
        with no workflow has an empty one); empty for any other agent type.
    """
    if agent.get("agent_type") != "workflow":
        return []
    owner_id = agent.get("user_id")
    if not agent.get("workflow_id"):
        return validate_workflow_structure([], [], user_id=owner_id)
    return stored_graph_errors(conn, agent["workflow_id"], owner_id)


def refuse_unfinished_graph(conn, agent: dict) -> Optional[object]:
    """The 400 that refuses a new run path for a workflow agent with an unfinished graph.

    For a webhook URL, a schedule or a public link: each runs the agent's
    current graph without its builder.

    Args:
        conn: Open database connection.
        agent: The stored agent row.

    Returns:
        The error response, or None when the agent may get one.
    """
    errors = unfinished_graph_errors(conn, agent)
    return graph_validation_failed(errors) if errors else None


def agent_borrowed_refs(conn, agent: dict, nodes: Optional[list] = None) -> list:
    """The tools and sources an agent uses that its owner reaches only through a grant.

    Its own tools and sources, the sources of its knowledge folders, and for
    a workflow agent those of its nodes (see ``resource_access.borrowed_refs``).
    Such an agent may not get a key, a public link or a webhook.

    Args:
        conn: Open database connection.
        agent: The agent row, or the row as a save would leave it (``user_id``
            and the ref fields; ``id`` once it exists).
        nodes: A workflow agent's nodes in builder shape, when the save
            brings them; else its stored graph is read.

    Returns:
        list: The borrowed ``(type, id)`` pairs.
    """
    owner = agent.get("user_id")
    holder = agent if agent.get("id") else None
    found = borrowed_refs(
        conn, owner, agent_refs(agent), agent.get("knowledge_folder_ids") or [],
        holder_type="agent" if holder else None, holder=holder,
    )
    if agent.get("agent_type") != "workflow":
        return found
    workflow = WorkflowsRepository(conn).get(str(agent["workflow_id"]), owner) if agent.get("workflow_id") else None
    if nodes is None:
        nodes = stored_graph(conn, workflow)[0] if workflow else []
    for ref in borrowed_refs(
        conn, owner, _node_refs(nodes), _node_folder_refs(nodes),
        holder_type="workflow" if workflow else None, holder=workflow,
    ):
        if ref not in found:
            found.append(ref)
    return found


def refuse_borrowed_outside_access(conn, agent: dict, user: str) -> Optional[object]:
    """The 403 that refuses a new key, public link or webhook to an agent using a borrowed item.

    Args:
        conn: Open database connection.
        agent: The stored agent row.
        user: Who asks.

    Returns:
        The error response, or None when the agent may get one.
    """
    borrowed = agent_borrowed_refs(conn, agent)
    if not borrowed:
        return None
    body, status = borrowed_refusal(conn, borrowed, user, agent)
    return make_response(jsonify(body), status)


# --- A team's items on an agent another team or person reaches -------------------
#
# An agent runs as its owner, so whoever chats with it reads the owner's sources
# and runs the owner's tools on their stored accounts. A team's sources, tools,
# prompts and knowledge folders stay with the people who already reach them: a
# holder that uses one may be shared with a whole team only when that team owns
# the item or receives it through a live share, and with one member only when
# that member can use the item. Items a person lent through a grant keep the
# grant rules.

# Error code of a share refused because the agent uses a team's items its audience can't reach.
CODE_USES_TEAM_ITEMS = "uses_team_items"
# Error code of a save that adds a team's item to an agent shared with someone who can't reach it.
CODE_TEAM_ITEM_SHARED_OUTSIDE = "team_item_shared_outside"

TeamRefs = dict[str, list[tuple[str, str]]]


def _team_owned(conn, refs: list[tuple[str, str]], holder_owner: Optional[str]) -> TeamRefs:
    """``refs`` grouped by the team that owns each, leaving out the holder owner's own and nobody's."""
    out: TeamRefs = {}
    for resource_type, resource_id in refs:
        rid = str(resource_id or "").strip().lower()
        if not looks_like_uuid(rid):
            continue
        owner = resource_owner(conn, resource_type, rid)
        if owner is None or owner == holder_owner or not is_principal_id(owner):
            continue
        team_id = team_of_principal(owner)
        if team_id is None:
            continue
        found = out.setdefault(team_id, [])
        if (resource_type, rid) not in found:
            found.append((resource_type, rid))
    return out


def _with_folders(conn, refs: list, folder_ids: list, holder_type: Optional[str], holder: Optional[dict]) -> list:
    """``refs`` plus each knowledge folder and every source it feeds the holder."""
    folder_ids = [str(f) for f in folder_ids or [] if f]
    if not folder_ids:
        return list(refs)
    # Lazy: folder_knowledge imports resource_access, which this module imports.
    from docsgpt.api.user.folder_knowledge import folder_source_ids

    fed = folder_source_ids(conn, folder_ids, holder_type, holder, keep_borrowed=True)
    return [*refs, *(("folder", f) for f in folder_ids), *(("source", s) for s in fed)]


def workflow_team_refs(conn, workflow: Optional[dict], owner_id: Optional[str], nodes: list) -> TeamRefs:
    """Another team's sources, tools and knowledge folders on a workflow's agent nodes.

    Args:
        conn: Open database connection.
        workflow: The saved workflow row, or None (a graph not saved yet).
        owner_id: The workflow's owner, whose own items don't count.
        nodes: The nodes in builder shape.

    Returns:
        TeamRefs: ``{team_id: [(type, id), ...]}``.
    """
    refs = _with_folders(conn, _node_refs(nodes), _node_folder_refs(nodes),
                         "workflow" if workflow else None, workflow)
    return _team_owned(conn, refs, owner_id)


def agent_team_refs(conn, agent: dict, nodes: Optional[list] = None) -> TeamRefs:
    """The items of teams other than the agent's owner that the agent uses, by team.

    Its sources, tools and prompt, its knowledge folders and the sources they
    feed, and for a workflow agent those of its nodes. Presets, builtin tools,
    the owner's own items and people's items don't count.

    Args:
        conn: Open database connection.
        agent: The agent row, or the row as a save would leave it (``user_id``
            and the ref fields; ``id`` once it exists).
        nodes: A workflow agent's nodes in builder shape, when the save
            brings them; else its stored graph is read.

    Returns:
        TeamRefs: ``{team_id: [(type, id), ...]}``, ids lowercased, each once.
    """
    owner = agent.get("user_id")
    holder = agent if agent.get("id") else None
    refs = _with_folders(conn, agent_refs(agent), agent.get("knowledge_folder_ids") or [],
                         "agent" if holder else None, holder)
    found = _team_owned(conn, refs, owner)
    if agent.get("agent_type") != "workflow":
        return found
    workflow = WorkflowsRepository(conn).get(str(agent["workflow_id"]), owner) if agent.get("workflow_id") else None
    if nodes is None:
        nodes = stored_graph(conn, workflow)[0] if workflow else []
    return merge_team_refs(found, workflow_team_refs(conn, workflow, owner, nodes))


def merge_team_refs(*groups: TeamRefs) -> TeamRefs:
    """The union of several :class:`TeamRefs`, each ref once, in the order first seen."""
    out: TeamRefs = {}
    for group in groups:
        for team_id, refs in group.items():
            found = out.setdefault(team_id, [])
            found.extend(ref for ref in refs if ref not in found)
    return out


def added_team_refs(before: TeamRefs, after: TeamRefs) -> TeamRefs:
    """The refs in ``after`` that ``before`` doesn't have."""
    had = {ref for refs in before.values() for ref in refs}
    out: TeamRefs = {}
    for team_id, refs in after.items():
        new = [ref for ref in refs if ref not in had]
        if new:
            out[team_id] = new
    return out


# The agent fields a save may change that decide which items it uses.
_REF_FIELDS = ("source_id", "extra_source_ids", "prompt_id", "tools", "knowledge_folder_ids", "agent_type", "workflow_id")


def team_refs_added_by_save(conn, agent: dict, fields: dict, nodes: Optional[list] = None) -> TeamRefs:
    """The team items an agent save adds: those the agent uses after it and didn't before.

    Args:
        conn: Open database connection.
        agent: The stored agent row.
        fields: The columns the save writes.
        nodes: The workflow nodes the save brings (an inline graph), if any.

    Returns:
        TeamRefs: The added items by owning team; empty when the save adds none.
    """
    if nodes is None and not any(f in fields for f in _REF_FIELDS):
        return {}
    after = {**agent, **{f: fields[f] for f in _REF_FIELDS if f in fields}}
    return added_team_refs(agent_team_refs(conn, agent), agent_team_refs(conn, after, nodes=nodes))


def _reaches(conn, item_team: str, ref: tuple[str, str], team_id: str, user_id: Optional[str]) -> bool:
    """Whether a whole team (``user_id`` None) or one person already reaches a team's item.

    A whole team reaches what it owns and what another team shares with it
    while that share is live; a person, what they can use. A knowledge folder
    isn't shared between teams, so only its own team, and its members, reach it.
    """
    resource_type, resource_id = ref
    if user_id:
        if resource_type == "folder":
            return team_role_for(conn, user_id, item_team) is not None
        return can_use_ref(conn, resource_type, resource_id, user_id)
    if canonical_team_id(team_id) is None:
        return False
    if resource_type == "folder":
        return canonical_team_id(team_id) == item_team
    return can_use_ref(conn, resource_type, resource_id, principal_id(team_id))


def unreached_team_refs(conn, team_refs: TeamRefs, team_id: str, user_id: Optional[str] = None) -> TeamRefs:
    """The team items a share with ``team_id`` (the whole team, or only ``user_id`` in it) wouldn't reach.

    Args:
        conn: Open database connection.
        team_refs: The holder's team items (see :func:`agent_team_refs`).
        team_id: The team the holder is or would be shared with.
        user_id: The one member it is shared with; None for the whole team.

    Returns:
        TeamRefs: The items its audience can't use, by owning team; empty when it reaches them all.
    """
    out: TeamRefs = {}
    for item_team, refs in team_refs.items():
        missing = [ref for ref in refs if not _reaches(conn, item_team, ref, team_id, user_id)]
        if missing:
            out[item_team] = missing
    return out


def _team_names(conn, team_ids) -> dict[str, str]:
    ids = [t for t in {str(t) for t in team_ids if t} if looks_like_uuid(t)]
    if not ids:
        return {}
    rows = conn.execute(
        text("SELECT id, name FROM teams WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": ids}
    ).fetchall()
    return {str(tid): name for tid, name in rows}


def uses_team_items_payload(conn, team_refs: TeamRefs, viewer: Optional[str]) -> list[dict]:
    """``[{team_id, name, items: [{key, type, id, name}]}]`` for a holder's team items.

    An item is named only to a viewer who can reach it (a folder: a member of
    its team), and a team only to its members or a viewer who reaches one of
    its listed items (they already see where it comes from).

    Args:
        conn: Open database connection.
        team_refs: Items by owning team.
        viewer: Who reads the payload.

    Returns:
        list[dict]: One row per team, in ``team_refs`` order.
    """
    names = ref_names(conn, [ref for refs in team_refs.values() for ref in refs])
    team_names = _team_names(conn, team_refs)
    out = []
    for team_id, refs in team_refs.items():
        member = team_role_for(conn, viewer, team_id) is not None
        items, any_seen = [], member
        for resource_type, rid in refs:
            if resource_type == "folder":
                seen = member
            else:
                seen = bool(viewer) and resolve(conn, resource_type, rid, viewer) is not None
            any_seen = any_seen or seen
            key = sponsor_key(resource_type, rid)
            items.append({"key": key, "type": resource_type, "id": rid, "name": names.get(key) if seen else None})
        out.append({"team_id": team_id, "name": team_names.get(team_id) if any_seen else None, "items": items})
    return out


def _move_offer(conn, team_refs: TeamRefs, agent: dict, caller: Optional[str]) -> Optional[dict]:
    """A team the caller may move their personal agent to that reaches every team item it uses, or None.

    Teams that own one of the items come first, then the caller's other teams.
    """
    owner = agent.get("user_id")
    if not caller or owner != caller or is_principal_id(owner):
        return None
    own_teams = TeamMembersRepository(conn).list_team_ids_for(caller)
    candidates = [t for t in team_refs if t in own_teams] + sorted(t for t in own_teams if t not in team_refs)
    for team_id in candidates:
        if not role_at_least(team_role_for(conn, caller, team_id), "editor"):
            continue
        if not unreached_team_refs(conn, team_refs, team_id):
            return {"team_id": team_id, "name": _team_names(conn, [team_id]).get(team_id)}
    return None


def _join_words(items: list[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _listed_items(rows: list[dict]) -> tuple[str, int]:
    """``the source "A" and the tool "B" from Ops`` for a payload, and how many items it names."""
    phrases, count = [], 0
    for row in rows:
        words = [f'the {i["type"]} "{i["name"]}"' if i["name"] else f'a {i["type"]}' for i in row["items"]]
        count += len(words)
        phrases.append(f"{_join_words(words)} from {row['name'] or 'another team'}")
    return _join_words(phrases), count


def team_confinement_refusal(
    conn, agent: dict, target_team_id: str, target_user_id: Optional[str], caller: Optional[str]
) -> Optional[tuple[dict, int]]:
    """The 409 that refuses sharing an agent with a team, or one member of it, who can't reach its team items.

    Call it before writing a share of an agent with ``target_team_id``, holding
    ``workspaces.locks.lock_owner_items`` for the agent's owner so a save that
    adds a team's item runs wholly before or after.

    Args:
        conn: Open database connection.
        agent: The stored agent row.
        target_team_id: The team it would be shared with.
        target_user_id: The one member it would be shared with; None for the whole team.
        caller: Who shares it.

    Returns:
        ``(body, 409)``, or None when the share may go ahead. The body has
        ``success``, ``error`` and ``code`` (:data:`CODE_USES_TEAM_ITEMS`),
        ``message``, ``uses_team_items`` (the items the share wouldn't reach,
        see :func:`uses_team_items_payload`) and ``move_to`` (``{team_id, name}``
        of a team where the caller, the agent's owner, is an Editor or above and
        which reaches every team item the agent uses; else None).
    """
    team_refs = agent_team_refs(conn, agent)
    if not team_refs:
        return None
    blocked = unreached_team_refs(conn, team_refs, target_team_id, target_user_id)
    if not blocked:
        return None
    rows = uses_team_items_payload(conn, blocked, caller)
    move_to = _move_offer(conn, team_refs, agent, caller)
    listed, count = _listed_items(rows)
    if target_user_id:
        audience = "that person"
    else:
        audience = _team_names(conn, [target_team_id]).get(canonical_team_id(target_team_id) or "") or "that team"
    message = (
        f"This agent uses {listed}, so it can't be shared with {audience}: "
        "a team's items stay with the people who can use them."
    )
    if move_to and move_to.get("name"):
        message += f" Move it to {move_to['name']} to share it from there."
    else:
        message += f" Remove {'it' if count == 1 else 'them'} from the agent first."
    return {
        "success": False,
        "error": CODE_USES_TEAM_ITEMS,
        "code": CODE_USES_TEAM_ITEMS,
        "message": message,
        "uses_team_items": rows,
        "move_to": move_to,
    }, 409


def holder_audiences(conn, agents: list[dict]) -> list[tuple[str, Optional[str]]]:
    """Who the agents are shared with: ``(team_id, member or None)`` for each grant and team share.

    Paused grants count too: they reach their people again with nothing written.
    """
    out: list[tuple[str, Optional[str]]] = []
    for row in agents:
        if not row.get("id"):
            continue
        aid = str(row["id"])
        found = [(str(g["team_id"]), g.get("target_user_id") or None)
                 for g in TeamResourceGrantsRepository(conn).list_for_resource("agent", aid)]
        found += [(str(s["team_id"]), None) for s in TeamItemSharesRepository(conn).teams_for("agent", aid)]
        out.extend(a for a in found if a not in out)
    return out


def team_items_shared_outside_refusal(
    conn, agents: list[dict], added: TeamRefs, caller: Optional[str]
) -> Optional[tuple[dict, int]]:
    """The 409 that refuses a save adding team items to agents shared with someone who can't reach them.

    Only items the save adds are judged: an agent shared before it used one
    keeps saving (its run leaves out what the person chatting can't use).
    Call it holding ``lock_owner_items`` for the agents' owner, so a share
    made at the same time is either seen here or sees this save.

    Args:
        conn: Open database connection.
        agents: The agents the save changes what they run (one agent, or every
            agent on a saved workflow).
        added: The team items the save adds (see :func:`added_team_refs`).
        caller: Who saves.

    Returns:
        ``(body, 409)``, or None. The body has ``success``, ``error`` and
        ``code`` (:data:`CODE_TEAM_ITEM_SHARED_OUTSIDE`), ``message``,
        ``uses_team_items`` (the added items someone can't reach) and
        ``shared_with`` (``[{team_id, name}]``, the name only for a member of
        that team or the agents' owner).
    """
    if not added:
        return None
    blocked: TeamRefs = {}
    shared_with: list[str] = []
    for team_id, user_id in holder_audiences(conn, agents):
        missing = unreached_team_refs(conn, added, team_id, user_id)
        if missing:
            blocked = merge_team_refs(blocked, missing)
            if team_id not in shared_with:
                shared_with.append(team_id)
    if not blocked:
        return None
    rows = uses_team_items_payload(conn, blocked, caller)
    listed, count = _listed_items(rows)
    owners = {row.get("user_id") for row in agents}
    names = _team_names(conn, shared_with)
    teams = [
        {"team_id": t, "name": names.get(t) if caller in owners or team_role_for(conn, caller, t) else None}
        for t in shared_with
    ]
    them = "it" if count == 1 else "them"
    message = (
        f"{listed[0].upper()}{listed[1:]} can't be added: this agent is shared with people who can't use "
        f"{them}, and a team's items stay with the people who can. Use {them} in an agent that isn't shared "
        "outside the team, or stop that share first."
    )
    return {
        "success": False,
        "error": CODE_TEAM_ITEM_SHARED_OUTSIDE,
        "code": CODE_TEAM_ITEM_SHARED_OUTSIDE,
        "message": message,
        "uses_team_items": rows,
        "shared_with": teams,
    }, 409


def workflow_team_items_refusal(
    conn, workflow: dict, owner_id: Optional[str], previous_nodes: list, nodes: list, caller: Optional[str]
) -> Optional[tuple[dict, int]]:
    """:func:`team_items_shared_outside_refusal` for a graph save, judged for every agent that runs the workflow.

    Args:
        conn: Open database connection.
        workflow: The saved workflow row.
        owner_id: Its owner.
        previous_nodes: The stored graph's nodes.
        nodes: The nodes being saved.
        caller: Who saves.

    Returns:
        ``(body, 409)``, or None.
    """
    added = added_team_refs(
        workflow_team_refs(conn, workflow, owner_id, previous_nodes),
        workflow_team_refs(conn, workflow, owner_id, nodes),
    )
    if not added:
        return None
    agents = conn.execute(
        text("SELECT id, user_id FROM agents WHERE workflow_id = CAST(:wid AS uuid)"), {"wid": str(workflow["id"])}
    ).mappings().all()
    return team_items_shared_outside_refusal(conn, [dict(a) for a in agents], added, caller)
