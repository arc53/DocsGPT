"""Shared set-up for the Move tests: a team, a second team for shares, and item builders.

Ops (the target team): alice owner, adam admin, eddie editor, vera viewer.
Other (a team eddie shares with): olga owner, eddie and vera members.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.folders import FolderItemsRepository, FoldersRepository
from docsgpt.storage.db.repositories.prompts import PromptsRepository
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.storage.db.repositories.team_members import TeamMembersRepository
from docsgpt.storage.db.repositories.team_resource_grants import TeamResourceGrantsRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.repositories.workflows import WorkflowsRepository
from docsgpt.workspaces.principal import principal_id


def team(conn, owner="alice", name="Ops", members=(("adam", "team_admin"), ("eddie", "team_editor"),
                                                   ("vera", "team_viewer"))) -> tuple[str, str]:
    """Create a team with members; return ``(team_id, principal_id)``."""
    row = TeamsRepository(conn).create(name, f"{name.lower()}-{uuid.uuid4().hex[:6]}", owner)
    tid = str(row["id"])
    repo = TeamMembersRepository(conn)
    repo.add_member(tid, owner, role="team_admin")
    for user, role in members:
        repo.add_member(tid, user, role=role)
    for user in {owner, *(u for u, _ in members)}:
        UsersRepository(conn).upsert(user, email=f"{user}@example.com")
    return tid, principal_id(tid)


def other_team(conn) -> str:
    """Team "Other" (olga owner; eddie and vera members): what eddie shares with."""
    tid, _ = team(conn, owner="olga", name="Other", members=(("eddie", "team_member"), ("vera", "team_member")))
    return tid


def agent(conn, owner, name="Helper", **kwargs) -> str:
    kwargs.setdefault("created_by", owner if not owner.startswith("__team__") else "alice")
    return str(AgentsRepository(conn).create(owner, name, kwargs.pop("status", "draft"), **kwargs)["id"])


def source(conn, owner, name="Docs", **kwargs) -> str:
    row = SourcesRepository(conn).create(name, user_id=owner, **kwargs)
    if owner.startswith("__team__"):
        conn.execute(text("UPDATE sources SET created_by = 'alice' WHERE id = CAST(:i AS uuid)"), {"i": str(row["id"])})
    return str(row["id"])


def tool(conn, owner, name="read_webpage", *, config=None, status=False, **kwargs) -> str:
    created_by = "alice" if owner.startswith("__team__") else None
    return str(UserToolsRepository(conn).create(
        owner, name, config=config or {}, display_name=kwargs.pop("display_name", name), description="",
        actions=[{"name": "act", "active": True}], status=status, created_by=created_by, **kwargs,
    )["id"])


def prompt(conn, owner, name="Brief") -> str:
    created_by = "alice" if owner.startswith("__team__") else None
    return str(PromptsRepository(conn).create(owner, name, "Be brief.", created_by=created_by)["id"])


def folder(conn, owner, name, parent: Optional[str] = None) -> str:
    created_by = "alice" if owner.startswith("__team__") else None
    return str(FoldersRepository(conn).create(owner, name, parent_id=parent, created_by=created_by)["id"])


def file(conn, owner, kind, item_id, folder_id) -> None:
    FolderItemsRepository(conn).file(owner, kind, item_id, folder_id)


def grant(conn, team_id, kind, item_id, owner, *, target=None, level="viewer") -> None:
    TeamResourceGrantsRepository(conn).grant(team_id, kind, item_id, owner, owner, level, target)


def workflow(conn, owner, name="Flow", nodes=()) -> str:
    """A workflow at graph version 1 whose agent nodes carry ``nodes`` (each a node config dict)."""
    created_by = "alice" if owner.startswith("__team__") else None
    wf = WorkflowsRepository(conn).create(owner, name, created_by=created_by)
    wid = str(wf["id"])
    from docsgpt.storage.db.repositories.workflow_nodes import WorkflowNodesRepository

    WorkflowNodesRepository(conn).bulk_create(wid, 1, [
        {"node_id": f"n{i}", "node_type": "agent", "title": f"N{i}", "position": {"x": 0, "y": 0}, "config": cfg}
        for i, cfg in enumerate(nodes)
    ])
    return wid


def owner_of(conn, kind, item_id) -> Optional[str]:
    table = {"agent": "agents", "source": "sources", "tool": "user_tools", "prompt": "prompts",
             "folder": "folders", "workflow": "workflows"}[kind]
    return conn.execute(text(f"SELECT user_id FROM {table} WHERE id = CAST(:i AS uuid)"), {"i": item_id}).scalar()


def body(to, items, *, folder_id=None, fingerprint=None) -> dict:
    """A move request body; ``items`` are ``(type, id)`` pairs."""
    out = {"to": {"workspace": to}, "items": [{"type": t, "id": i} for t, i in items]}
    if folder_id:
        out["to"]["folder_id"] = folder_id
    if fingerprint:
        out["fingerprint"] = fingerprint
    return out


def plan(conn, mover, request_body) -> dict:
    from docsgpt.workspaces.move import parse_move_request, plan_move

    return plan_move(conn, mover, parse_move_request(request_body)).body


def apply(conn, mover, request_body) -> dict:
    """Plan then apply with that plan's fingerprint; returns the applied plan."""
    from docsgpt.workspaces.move import apply_move, parse_move_request

    fp = plan(conn, mover, request_body)["fingerprint"]
    return apply_move(conn, mover, parse_move_request({**request_body, "fingerprint": fp})).body


def keyed(entries) -> dict:
    """``{(type, id): entry}`` of a plan list."""
    return {(e["type"], e["id"]): e for e in entries}
