"""Items another team shares with a team workspace, as that workspace's lists and detail reads show them.

A team's agent, source, tool or prompt shared with a whole other team (``team_item_shares``) is listed in the
receiving team's workspace beside its own items: ``origin: team_shared``, ``shared_from`` the owning team, the
receiver's fixed actions (``outside.RECEIVER_ACTIONS``) and the receiving team as its ``workspace``. Only live
shares list: the owning team isn't locked and still owns the item. Personal lists never show them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from flask import has_request_context
from sqlalchemy import Connection, text

from docsgpt.api.user.resource_access import ResourceAccess, receiver_payload, team_item_reach
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.workspaces.context import Workspace, parse_workspace_ref
from docsgpt.workspaces.outside import outside_minimum
from docsgpt.workspaces.principal import team_of_principal

_TABLES = {"agent": "agents", "source": "sources", "tool": "user_tools", "prompt": "prompts"}


def received_into(conn: Connection, workspace: Workspace, resource_type: str) -> dict[str, dict]:
    """The items of one kind other teams share with a team workspace, each with its access fields.

    Args:
        conn: Open database connection.
        workspace: The request's workspace; Personal receives nothing.
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.

    Returns:
        dict[str, dict]: ``item id (canonical) -> access payload`` (``receiver_payload``) for every live
        share into the team, newest first. A share whose owning team is locked, or that names a team that
        no longer owns the item, is left out.
    """
    table = _TABLES.get(resource_type)
    if table is None or not workspace.is_team or not workspace.team_id:
        return {}
    shares = TeamItemSharesRepository(conn).list_into(workspace.team_id, resource_type)
    if not shares:
        return {}
    owners = dict(
        conn.execute(
            text(f"SELECT CAST(id AS text), user_id FROM {table} WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(s["resource_id"]) for s in shares]},
        ).fetchall()
    )
    out: dict[str, dict] = {}
    for share in shares:
        rid = str(share["resource_id"]).lower()
        owner_team = str(share["owner_team_id"])
        # The item must still be the sharing team's, and that team not locked. The policy comes with the
        # share row; ``outside_minimum`` reads an unknown value as locked, as ``team_policy`` does.
        if team_of_principal(owners.get(rid)) != owner_team or outside_minimum(share.get("owner_team_policy")) is None:
            continue
        out[rid] = receiver_payload(resource_type, workspace.team_id, owner_team, share.get("owner_team_name"))
    return out


def in_request_workspace(conn: Connection, ra: Optional[ResourceAccess], user: str) -> Optional[ResourceAccess]:
    """``ra`` placed in the team the request is made from, when the item reaches the caller through it.

    A shared item that reaches the caller through several teams otherwise answers the oldest share's team;
    a read made from one of the others lives there instead.

    Args:
        conn: Open database connection.
        ra: The caller's access to the item (from ``resolve``), or None.
        user: The caller.

    Returns:
        Optional[ResourceAccess]: ``ra``, with ``via_team_id`` the request's team when that team receives it.
    """
    if ra is None or not ra.via_team_id or not has_request_context():
        return ra
    requested = parse_workspace_ref()
    if not requested:
        return ra
    team = team_item_reach(conn, user, ra.resource_type, ra.resource_id, prefer_team=requested)
    if team and team != ra.via_team_id:
        return replace(ra, via_team_id=team)
    return ra


def is_received(ra: Optional[ResourceAccess]) -> bool:
    """Whether the caller reaches the item only through a share with their team (no filing, no edit page)."""
    return ra is not None and bool(ra.via_team_id)
