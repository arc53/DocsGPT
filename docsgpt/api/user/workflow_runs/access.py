"""Who may read a workflow run, shared by the Flask routes and the download route.

A run is the caller's when they started it (``workflow_runs.user_id``). It
belongs to the agent that ran it (``inputs.agent_id``), so a personal access
token restricted to some agents reaches only those agents' runs; a run
without an agent (the builder preview) is outside every such allowlist.
A run of a team's workflow is the team's as well: someone who left the team
can't read it, as with their chats there, and can again if re-added.
Everything else reads as not found, so a token learns nothing about runs it
may not see.
"""

from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import text

from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.workspaces.principal import is_principal_id, team_of_principal
from docsgpt.workspaces.roles import team_role_for

# Resource families a run route can hold a token to: only agents. A token
# restricted on anything else is refused, since a run can read sources, tools
# and prompts this check cannot see.
RUN_RESTRICTABLE_FAMILIES = ("agents",)


def canonical_id(value: object) -> str:
    """A UUID in its canonical lower-case form; other values as text."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return str(value)


def run_agent_id(run: dict) -> Optional[str]:
    """The agent that ran ``run``, or None for a run without one."""
    inputs = run.get("inputs")
    agent_id = inputs.get("agent_id") if isinstance(inputs, dict) else None
    return canonical_id(agent_id) if agent_id else None


def agent_allowed(run: dict, allowed_agents: Optional[Iterable[str]]) -> bool:
    """Whether a run passes an agent allowlist (``None`` means no allowlist)."""
    if allowed_agents is None:
        return True
    agent_id = run_agent_id(run)
    return agent_id is not None and agent_id in {canonical_id(a) for a in allowed_agents}


def run_in_reach(conn, run: dict, user_id: Optional[str]) -> bool:
    """Whether ``user_id`` is still in the team whose workflow ``run`` ran, when a team's.

    Args:
        conn: A database connection.
        run: The run row (needs ``workflow_id``).
        user_id: The caller.

    Returns:
        False for a run of a team's workflow when the caller is not in that team; True otherwise.
    """
    workflow_id = run.get("workflow_id")
    if not workflow_id:
        return True
    owner = conn.execute(
        text("SELECT user_id FROM workflows WHERE id = CAST(:id AS uuid)"), {"id": str(workflow_id)}
    ).scalar()
    if not is_principal_id(owner):
        return True
    return team_role_for(conn, user_id, team_of_principal(owner)) is not None


def visible_run(conn, run_id: str, user_id: Optional[str], allowed_agents: Optional[Iterable[str]]) -> Optional[dict]:
    """The run when the caller may read it, else None.

    Args:
        conn: A database connection.
        run_id: The run's id, as the client sent it.
        user_id: The caller.
        allowed_agents: The caller's agent allowlist, or None when unrestricted.

    Returns:
        The run row, or None when it is missing, someone else's, outside
        the allowlist, or a run of a team's workflow and the caller left that team.
    """
    if not user_id or not looks_like_uuid(run_id):
        return None
    run = WorkflowRunsRepository(conn).get(run_id)
    if run is None or run.get("user_id") != user_id or not agent_allowed(run, allowed_agents):
        return None
    if not run_in_reach(conn, run, user_id):
        return None
    return run
