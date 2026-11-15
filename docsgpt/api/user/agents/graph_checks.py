"""Whether a workflow agent's stored graph may run where its builder doesn't watch it.

A draft's graph save checks the shape only, so a draft's stored graph may be
unfinished. Anything that runs an agent outside its builder (its key, a
webhook token, a schedule, its public link) runs that graph as it is, so
such an agent's saves run the full validation, and adding one of those to a
workflow agent first validates its stored graph in full.
"""

from __future__ import annotations

from typing import Optional

from flask import jsonify, make_response
from sqlalchemy import text

from docsgpt.api.user.resource_access import agent_refs, borrowed_refs, borrowed_refusal
from docsgpt.api.user.workflows.routes import (
    _node_folder_refs,
    _node_refs,
    stored_graph,
    validate_workflow_structure,
)
from docsgpt.storage.db.repositories.schedules import SchedulesRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository


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
