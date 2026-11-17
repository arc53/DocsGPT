"""``GET /api/teams/<team_id>/usage``: what a team workspace spent, for its Owner and Admins.

A report, not a limit: it reads the usage rows stamped with the team, so
plain chats in the team count, Personal rows and another team's never do,
and an agent's spend stays here after it is moved out. Alongside it, the
schedules, outside access and scheduled source syncs of the team that are
paused for their payer, so the admins can see who should take them over.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from flask import jsonify, make_response, request
from flask_restx import Resource
from sqlalchemy import text

from docsgpt.core.settings import settings
from docsgpt.quotas.agent_limits import has_agent_limit
from docsgpt.quotas.pause import PayerChecks, outside_access_pause, schedule_pause
from docsgpt.quotas.payer import published_access_payer
from docsgpt.quotas.windows import window_bounds
from docsgpt.storage.db.repositories.token_usage import TokenUsageRepository
from docsgpt.storage.db.session import db_readonly
from docsgpt.workspaces.principal import is_principal_id, principal_id
from docsgpt.workspaces.roles import from_stored_role, role_rank

from .routes import (
    OUTSIDE_ACCESS_ON_SQL,
    _current_user,
    _user_labels,
    person_ref,
    team_admin_refusal,
    teams_ns,
)

logger = logging.getLogger(__name__)

PERIODS = ("current", "previous")

#: The most people and agents each list carries.
LIST_LIMIT = 200

#: The ways in from outside, by the name payloads use.
_ACCESS_KINDS = ("api_key", "public_link", "webhook")

_AGENT_COLUMNS = (
    "a.id, a.name, a.user_id, a.key, a.shared, a.shared_token, a.incoming_webhook_token, a.access_payer_id, "
    "a.limited_token_mode, a.limited_request_mode"
)


def period_bounds(period: str, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """The ``QUOTA_PERIOD`` window the report covers.

    Args:
        period: ``current`` or ``previous``.
        now: Reference instant, for tests.

    Returns:
        ``(start, end)``, end exclusive.
    """
    start, end = window_bounds(settings.QUOTA_PERIOD, now)
    if period == "previous":
        return window_bounds(settings.QUOTA_PERIOD, start - timedelta(microseconds=1))
    return start, end


def access_on(agent: dict) -> list[str]:
    """The ways in from outside an agent row has switched on, by payload name."""
    flags = {
        "api_key": bool(agent.get("key")),
        "public_link": bool(agent.get("shared") and agent.get("shared_token")),
        "webhook": bool(agent.get("incoming_webhook_token")),
    }
    return [kind for kind in _ACCESS_KINDS if flags[kind]]


def _roles_in_team(conn, team_id: str, user_ids: set[str]) -> dict[str, str]:
    """Each person's role in the team now (``owner`` … ``viewer``); a person no longer in it is absent."""
    ids = sorted(u for u in user_ids if u)
    if not ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT user_id, role FROM team_members WHERE team_id = CAST(:t AS uuid) AND user_id = ANY(:ids) "
            "UNION ALL SELECT owner_id, 'owner' FROM teams WHERE id = CAST(:t AS uuid) AND owner_id = ANY(:ids)"
        ),
        {"t": team_id, "ids": ids},
    ).fetchall()
    roles: dict[str, str] = {}
    for user_id, stored in rows:
        role = "owner" if stored == "owner" else from_stored_role(stored)
        if role and role_rank(role) > role_rank(roles.get(user_id)):
            roles[user_id] = role
    return roles


def _agents(conn, agent_ids: list[str]) -> dict[str, dict]:
    if not agent_ids:
        return {}
    rows = conn.execute(
        text(f"SELECT {_AGENT_COLUMNS} FROM agents a WHERE a.id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": agent_ids},
    ).mappings().fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def _shared_in(conn, team_id: str, agents: dict[str, dict]) -> dict[str, dict]:
    """``agent_id -> {team_id, name}`` for the agents another team shares with this one (``shared_from``).

    Their chats here are this team's spend; the agent stays the owning team's, so only its name is read.

    Args:
        conn: Open connection.
        team_id: The receiving team.
        agents: The agents on the list that this team doesn't own, by id.

    Returns:
        dict: The owning team of each agent shared with this team now, by id.
    """
    if not agents:
        return {}
    rows = conn.execute(
        text(
            "SELECT s.resource_id::text AS agent_id, s.owner_team_id::text AS owner_team_id, t.name "
            "FROM team_item_shares s JOIN teams t ON t.id = s.owner_team_id "
            "WHERE s.team_id = CAST(:team AS uuid) AND s.resource_type = 'agent' "
            "AND s.resource_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"team": team_id, "ids": list(agents)},
    ).mappings().fetchall()
    return {
        row["agent_id"]: {"team_id": row["owner_team_id"], "name": row["name"]}
        for row in rows
        # Still that team's agent: a row left behind by a move names nobody.
        if agents[row["agent_id"]].get("user_id") == principal_id(row["owner_team_id"])
    }


def _published_payer(agent: dict) -> Optional[str]:
    payer = published_access_payer(agent)
    return payer if payer and not is_principal_id(payer) else None


def paused_items(conn, team_id: str) -> list[dict]:
    """Everything of the team's that is paused for its payer, for the admins to see and take over.

    Args:
        conn: Open connection.
        team_id: The team.

    Returns:
        A list of ``{type: "schedule", id, name, agent {id, name}, paused_for {reason, until}, paid_by}``,
        ``{type: "outside_access", id, agent {id, name}, access [...], paused_for, paid_by}`` (``id`` is the
        agent's) and ``{type: "source_sync", id, name, paused_for {reason, since}}``. ``paid_by`` is
        ``{user_id, label}`` or None when nobody pays. A schedule a person paused is not listed.
    """
    principal = principal_id(team_id)
    checks = PayerChecks()
    found: list[tuple[dict, Optional[str]]] = []
    schedules = conn.execute(
        text(
            "SELECT s.id, s.name, s.user_id AS setter, a.id AS agent_id, a.name AS agent_name, a.user_id, a.key "
            "FROM schedules s JOIN agents a ON a.id = s.agent_id "
            "WHERE a.user_id = :principal AND s.status = 'active' ORDER BY s.created_at, s.id"
        ),
        {"principal": principal},
    ).mappings().fetchall()
    for row in schedules:
        agent = {"id": str(row["agent_id"]), "user_id": row["user_id"], "key": row["key"]}
        pause = schedule_pause(conn, {"user_id": row["setter"]}, agent, checks=checks)
        if pause is None:
            continue
        found.append((
            {
                "type": "schedule",
                "id": str(row["id"]),
                "name": row["name"],
                "agent": {"id": str(row["agent_id"]), "name": row["agent_name"]},
                "paused_for": pause.payload(),
            },
            pause.payer,
        ))
    agents = conn.execute(
        text(
            f"SELECT {_AGENT_COLUMNS} FROM agents a WHERE a.user_id = :principal AND {OUTSIDE_ACCESS_ON_SQL} "
            "ORDER BY a.name, a.id"
        ),
        {"principal": principal},
    ).mappings().fetchall()
    for row in agents:
        agent = dict(row)
        pause = outside_access_pause(conn, agent, checks=checks)
        if pause is None:
            continue
        found.append((
            {
                "type": "outside_access",
                "id": str(agent["id"]),
                "agent": {"id": str(agent["id"]), "name": agent["name"]},
                "access": access_on(agent),
                "paused_for": pause.payload(),
            },
            pause.payer,
        ))
    labels = _user_labels(conn, {payer for _, payer in found if payer})
    items = []
    for item, payer in found:
        item["paid_by"] = person_ref(payer, labels)
        items.append(item)
    sources = conn.execute(
        text(
            "SELECT id, name, metadata -> 'sync_paused' AS paused FROM sources "
            "WHERE user_id = :principal AND jsonb_typeof(metadata -> 'sync_paused') = 'object' ORDER BY name, id"
        ),
        {"principal": principal},
    ).mappings().fetchall()
    for row in sources:
        paused: dict[str, Any] = row["paused"] or {}
        items.append({
            "type": "source_sync",
            "id": str(row["id"]),
            "name": row["name"],
            "paused_for": {"reason": paused.get("reason"), "since": paused.get("since")},
        })
    return items


def team_usage_body(conn, team_id: str, period: str) -> dict:
    """The Usage tab's body for one period.

    Args:
        conn: Open connection.
        team_id: The team.
        period: ``current`` or ``previous``.

    Returns:
        ``{success, period {kind, start, end, current}, totals {tokens, cost, people}, split {chats, runs},
        by_person [{user_id, label, role, tokens, cost}], by_agent [{agent_id, name, tokens, cost, requests,
        people, limit_on, published, moved_out, shared_from}], paused [...]}``. ``role`` is None for someone
        no longer in the team; ``name`` None for an agent that can't be read or has moved out; ``published``
        is ``{paid_by}`` while the team's agent has outside access on, else None; ``moved_out`` is True for
        an agent the team no longer owns, whose spend here stays but whose name, owner and payer now are
        someone else's. ``shared_from`` (``{team_id, name}``) marks another team's agent shared with this
        team, whose members' chats count here: named, never moved out, its payer and limit not shown.
    """
    start, end = period_bounds(period)
    usage = TokenUsageRepository(conn).team_usage(team_id, start, end, limit=LIST_LIMIT)
    people = {row["user_id"] for row in usage["by_person"]}
    found = _agents(conn, [row["agent_id"] for row in usage["by_agent"]])
    principal = principal_id(team_id)
    shared_from = _shared_in(
        conn, team_id, {agent_id: agent for agent_id, agent in found.items() if agent.get("user_id") != principal}
    )
    moved_out = {
        agent_id for agent_id, agent in found.items()
        if agent.get("user_id") != principal and agent_id not in shared_from
    }
    agents = {agent_id: agent for agent_id, agent in found.items() if agent.get("user_id") == principal}
    payers = {_published_payer(agent) for agent in agents.values() if access_on(agent)}
    labels = _user_labels(conn, people | {p for p in payers if p})
    roles = _roles_in_team(conn, team_id, people)
    by_person = [
        {
            "user_id": row["user_id"],
            "label": labels.get(row["user_id"]) or row["user_id"],
            "role": roles.get(row["user_id"]),
            "tokens": row["tokens"],
            "cost": row["cost"],
        }
        for row in usage["by_person"]
    ]
    by_agent = []
    for row in usage["by_agent"]:
        origin = shared_from.get(row["agent_id"])
        if origin is not None:
            by_agent.append({
                **row, "moved_out": False, "name": found[row["agent_id"]].get("name"), "limit_on": False,
                "published": None, "shared_from": origin,
            })
            continue
        agent = agents.get(row["agent_id"]) or {}
        by_agent.append({
            **row,
            "moved_out": row["agent_id"] in moved_out,
            "name": agent.get("name"),
            "limit_on": bool(agent) and has_agent_limit(agent),
            "published": (
                {"paid_by": person_ref(_published_payer(agent), labels)} if agent and access_on(agent) else None
            ),
            "shared_from": None,
        })
    return {
        "success": True,
        "period": {
            "kind": settings.QUOTA_PERIOD,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "current": period == "current",
        },
        "totals": usage["totals"],
        "split": usage["split"],
        "by_person": by_person,
        "by_agent": by_agent,
        "paused": paused_items(conn, team_id),
    }


@teams_ns.route("/teams/<string:team_id>/usage")
class TeamUsage(Resource):
    def get(self, team_id):
        """What the team workspace spent this period (``?period=previous`` for the one before).

        The team's Owner and Admins only: 403 ``workspace_role_required``
        below Admin, 404 outside the team. Lists hold at most 200 rows, by
        cost then tokens. See :func:`team_usage_body` for the shape.
        """
        period = request.args.get("period") or "current"
        try:
            with db_readonly() as conn:
                refusal = team_admin_refusal(conn, _current_user(), team_id)
                if refusal is not None:
                    return refusal
                if period not in PERIODS:
                    return make_response(
                        jsonify(
                            {"success": False, "error": "invalid_period", "message": "period is current or previous"}
                        ),
                        400,
                    )
                body = team_usage_body(conn, team_id, period)
            return make_response(jsonify(body), 200)
        except Exception as err:
            logger.error("Team usage failed: %s", err, exc_info=True)
            return make_response(jsonify({"success": False}), 400)
