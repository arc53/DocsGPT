"""Taking a team's items outside the team: its policy, its shares with whole other teams, and what each side reads.

A team picks who may take its items outside (``teams.outside_policy``, see
:mod:`docsgpt.workspaces.outside`). Admins and the Owner change it while it
isn't locked; once locked only the Owner may (``PUT
/api/teams/<id>/outside_policy``, never through a token). ``GET
/api/teams/<id>/outside`` lists, for every member, the team's items shared
with other teams and its agents with outside access on.

Sharing a team's agent, source, tool or prompt with another team goes through
the grants route like a personal share, but lands in ``team_item_shares``: the
whole receiving team, at Viewer level, by someone the policy lets take items
outside who is also in the receiving team. The share outlives whoever made it.
In the owning team, whoever may take items outside, and its Admins and Owner
always (locked too), may stop it; in the receiving team, its Admins and Owner.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Response, jsonify, make_response, request
from flask_restx import Resource
from sqlalchemy import text

from docsgpt.api.user.resource_access import (
    AccessDenied,
    ResourceAccess,
    best_effort,
    borrowed_refusal,
    build_team,
    require,
    resolve,
    resource_owner,
)
from docsgpt.quotas.pause import PayerChecks
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.team_item_shares import TeamItemSharesRepository
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.user_tools import UserToolsRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.locks import lock_owner_items
from docsgpt.workspaces.outside import (
    CODE_POLICY_OWNER_ONLY,
    CODE_TEAM_LOCKED,
    POLICIES,
    POLICY_LOCKED,
    may_set_policy,
    may_take_outside,
    team_policy,
)
from docsgpt.workspaces.principal import canonical_team_id, principal_id, team_of_principal
from docsgpt.workspaces.roles import role_at_least, team_role_for

from .routes import (
    OUTSIDE_ACCESS_ON_SQL,
    _audit,
    _current_user,
    _resource_rows,
    _user_labels,
    person_ref,
    teams_ns,
)

logger = logging.getLogger(__name__)

# Error codes of a share with another team refused for its shape or its people.
CODE_WHOLE_TEAM_ONLY = "team_share_whole_team_only"
CODE_VIEWER_ONLY = "team_share_viewer_only"
CODE_NOT_MEMBER = "team_share_not_member"
CODE_SAME_TEAM = "team_share_same_team"
CODE_ROLE_REQUIRED = "workspace_role_required"

# Why a share with another team gives no access right now.
PAUSED_TEAM_LOCKED = CODE_TEAM_LOCKED


def _error(status: int, code: str, message: str) -> Response:
    return make_response(jsonify({"success": False, "error": code, "message": message}), status)


def can_set_outside_policy(role: Optional[str], policy: Optional[str]) -> bool:
    """Whether someone with ``role`` in a team may change its policy from ``policy`` to any other.

    Args:
        role: Their role in the team (``owner``, ``admin``, ``editor``, ``viewer``) or None.
        policy: The team's policy now.

    Returns:
        bool: True for the Owner, and for an Admin while the team isn't locked.
    """
    return any(may_set_policy(role, policy, new) for new in POLICIES if new != policy)


def policy_fields(team: dict, role: Optional[str]) -> dict:
    """``outside_policy`` and ``can_set_outside_policy`` of a team row, as the caller reads them.

    Args:
        team: The team row (``outside_policy`` from ``teams``).
        role: The caller's role in the team, or None.

    Returns:
        dict: The two fields; an unknown stored value reads as ``locked``, as everywhere.
    """
    policy = team.get("outside_policy")
    policy = policy if policy in POLICIES else POLICY_LOCKED
    return {"outside_policy": policy, "can_set_outside_policy": can_set_outside_policy(role, policy)}


def _may_revoke_as_owner(role: Optional[str], policy: str) -> bool:
    """The owning side: whoever may take items outside, and its Admins and Owner always (locked too)."""
    return role_at_least(role, "admin") or may_take_outside(role, policy)


def _receiving_agents(conn, receiving_team_id: str, rows: list[dict]) -> dict[tuple[str, str], Optional[list]]:
    """The receiving team's agents that use each shared source, tool or prompt (None for an agent).

    Read as the receiving team's principal, so only that team's own agents count: those are what stop
    when the share ends.

    Returns:
        dict: ``(type, id) -> [{id, name}]``; None where it couldn't be read, and for a shared agent.
    """
    # Lazy: resource_usage pulls in the sharing helpers, which import the teams routes.
    from docsgpt.api.user.resource_usage import attach_used_by

    out: dict[tuple[str, str], Optional[list]] = {}
    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        if row["resource_type"] == "agent":
            out[("agent", str(row["resource_id"]))] = None
        else:
            by_kind.setdefault(row["resource_type"], []).append({"id": str(row["resource_id"])})
    for kind, items in by_kind.items():
        attach_used_by(conn, principal_id(receiving_team_id), kind, items, deletable_ids=[])
        for item in items:
            used = item.get("used_by")
            out[(kind, item["id"])] = (
                [{"id": a["id"], "name": a.get("name")} for a in used["agents"]] if used is not None else None
            )
    return out


def _used_by(conn, rows: list[dict]) -> dict[tuple[str, tuple[str, str]], Optional[list]]:
    """:func:`_receiving_agents` for share rows into several teams, keyed ``(receiving team, (type, id))``."""
    out: dict[tuple[str, tuple[str, str]], Optional[list]] = {}
    for team_id in {str(r["team_id"]) for r in rows}:
        mine = [r for r in rows if str(r["team_id"]) == team_id]
        found = best_effort(conn, "who uses a shared item", lambda: _receiving_agents(conn, team_id, mine), {})
        out.update({(team_id, key): value for key, value in found.items()})
    return out


def _live_rows(conn, rows: list[dict]) -> list[dict]:
    """The share rows whose item is still the owning team's: a stale or forced row is left out."""
    return [
        row for row in rows
        if resource_owner(conn, row["resource_type"], str(row["resource_id"])) == principal_id(row["owner_team_id"])
    ]


def outside_share_rows(
    conn, owner_team_id: str, role: Optional[str], policy: str, resource: Optional[tuple[str, str]] = None
) -> list[dict]:
    """The owning team's shares with other teams, newest first, as its members read them.

    Args:
        conn: Open connection.
        owner_team_id: The owning team.
        role: The reader's role there (decides ``can_revoke``).
        policy: The team's policy (``paused_reason`` while locked, and ``can_revoke``).
        resource: Only the shares of this ``(type, id)``, when given.

    Returns:
        list[dict]: ``{id, resource_type, resource_id, resource_name, team_id, name, shared_by {user_id,
        label}, created_at, can_revoke, used_by_count, paused_reason}``; ``team_id`` / ``name`` are the
        receiving team's, ``used_by_count`` the receiving team's agents that use it (None for an agent),
        ``paused_reason`` ``team_locked`` while the owning team is locked.
    """
    rows = TeamItemSharesRepository(conn).list_from(owner_team_id)
    if resource is not None:
        rows = [r for r in rows if r["resource_type"] == resource[0] and str(r["resource_id"]) == resource[1]]
    rows = _live_rows(conn, rows)
    names = _resource_rows(conn, rows)
    labels = _user_labels(conn, {r["shared_by"] for r in rows})
    can_revoke = _may_revoke_as_owner(role, policy)
    used = _used_by(conn, rows)
    out = []
    for row in rows:
        key = (row["resource_type"], str(row["resource_id"]))
        agents = used.get((str(row["team_id"]), key))
        out.append({
            "id": str(row["id"]),
            "resource_type": row["resource_type"],
            "resource_id": str(row["resource_id"]),
            "resource_name": (names.get(key) or {}).get("name"),
            "team_id": str(row["team_id"]),
            "name": row.get("team_name"),
            "shared_by": person_ref(row["shared_by"], labels),
            "created_at": row.get("created_at"),
            "can_revoke": can_revoke,
            "used_by_count": len(agents) if agents is not None else None,
            "paused_reason": PAUSED_TEAM_LOCKED if policy == POLICY_LOCKED else None,
        })
    return out


def incoming_share_rows(conn, user: str, team_id: str, resource_type: Optional[str] = None) -> list[dict]:
    """The items other teams share with ``team_id``, as rows of its grants list.

    Args:
        conn: Open connection.
        user: The reader, a member of ``team_id``.
        team_id: The receiving team.
        resource_type: Only this kind, when given.

    Returns:
        list[dict]: Grant-shaped rows (``resource_type``, ``resource_id``, ``resource_name``,
        ``access_level`` ``viewer``, ``target_user_id`` None, ``owner_id``, ``granted_by`` and its label,
        ``created_at``) plus ``origin`` ``team_shared``, ``shared_from`` ``{team_id, name}``,
        ``paused_reason`` (``team_locked`` while the owning team is locked), ``can_revoke`` (the receiving
        team's Admins and Owner: "Remove from this team"), ``used_by`` (``[{id, name}]``, this team's agents
        that stop using it when the share ends; None for an agent or when it can't be read) and ``caller``
        (the reader's access, None while paused).
    """
    rows = _live_rows(conn, TeamItemSharesRepository(conn).list_into(team_id, resource_type))
    names = _resource_rows(conn, rows)
    used = _used_by(conn, rows)
    labels = _user_labels(conn, {r["shared_by"] for r in rows})
    can_revoke = role_at_least(team_role_for(conn, user, team_id), "admin")
    out = []
    for row in rows:
        kind, rid, owner_team = row["resource_type"], str(row["resource_id"]), str(row["owner_team_id"])
        locked = team_policy(conn, owner_team) == POLICY_LOCKED
        ra = None if locked else resolve(conn, kind, rid, user)
        out.append({
            "id": str(row["id"]),
            "team_id": str(row["team_id"]),
            "resource_type": kind,
            "resource_id": rid,
            "resource_name": (names.get((kind, rid)) or {}).get("name"),
            "access_level": "viewer",
            "target_user_id": None,
            "owner_id": principal_id(owner_team),
            "owner_label": None,
            "target_user_label": None,
            "granted_by": row["shared_by"],
            "granted_by_label": labels.get(row["shared_by"]),
            "created_at": row.get("created_at"),
            "origin": "team_shared",
            "shared_from": {"team_id": owner_team, "name": row.get("owner_team_name")},
            "paused_reason": PAUSED_TEAM_LOCKED if locked else None,
            "can_revoke": can_revoke,
            "used_by": used.get((str(row["team_id"]), (kind, rid))),
            "caller": ra.payload() if ra else None,
        })
    return out


def _warning_kind(conn, ra: ResourceAccess) -> str:
    """Which warning the share dialog shows: ``agent``, ``source``, ``prompt``, ``tool_stored`` or ``tool_member``.

    A tool on each person's own account (a member-mode connection) runs on each receiver's account;
    any other tool runs on the owning team's stored one, the warning that also covers a mode that
    can't be read.
    """
    if ra.resource_type != "tool":
        return ra.resource_type

    def _mode() -> str:
        tool = UserToolsRepository(conn).get_by_id(ra.resource_id) or {}
        if not tool.get("connection_id"):
            # A team's member-mode tool names only its service: each person signs in with their own account.
            return "tool_member" if tool.get("credential_mode") == "member" else "tool_stored"
        from docsgpt.connectors import service
        from docsgpt.connectors.resolve import MODE_MEMBER, resolve_connection

        resolved = resolve_connection(tool, tool.get("user_id"), conn=conn, policies=service.load_policies(conn))
        return "tool_member" if resolved.mode == MODE_MEMBER else "tool_stored"

    return best_effort(conn, "a shared tool's account", _mode, "tool_stored")


# The custom models an agent runs on: its default, its model list and the agent nodes of its workflow's
# current graph, kept to the agent's owner's own (anyone else's never runs), enabled, by name.
_AGENT_TEAM_MODELS_SQL = text(
    """
    WITH agent AS (
        SELECT * FROM agents WHERE id = CAST(:agent AS uuid) AND user_id = :owner
    ), named AS (
        SELECT lower(default_model_id) AS m FROM agent
        UNION SELECT lower(e) FROM agent, jsonb_array_elements_text(
            CASE WHEN jsonb_typeof(agent.models) = 'array' THEN agent.models ELSE '[]'::jsonb END) e
        UNION SELECT lower(COALESCE(n.config -> 'config' ->> 'model_id', n.config ->> 'model_id'))
        FROM agent
        JOIN workflows w ON w.id = agent.workflow_id AND w.user_id = :owner
        JOIN workflow_nodes n ON n.workflow_id = w.id AND n.graph_version = w.current_graph_version
            AND n.node_type = 'agent'
    )
    SELECT m.id::text AS id, m.display_name AS name FROM user_custom_models m
    WHERE m.user_id = :owner AND m.enabled AND lower(m.id::text) IN (SELECT m FROM named WHERE m IS NOT NULL)
    ORDER BY m.display_name, m.id
    """
)


def _team_models(conn, ra: ResourceAccess) -> list[dict]:
    """The owning team's custom models a team agent runs on, so the share dialog can say so.

    Members of a team the agent is shared with, and outside callers, run it on these models with the
    owning team's key. Anything but an agent names none.

    Returns:
        list[dict]: ``{id, name}`` by name; empty when it can't be read.
    """
    if ra.resource_type != "agent" or not ra.owner_id:
        return []
    return best_effort(
        conn, "an agent's team models",
        lambda: [dict(r._mapping) for r in conn.execute(
            _AGENT_TEAM_MODELS_SQL, {"agent": ra.resource_id, "owner": ra.owner_id},
        ).fetchall()],
        [],
    )


def share_targets(conn, user: str, ra: ResourceAccess, shared_with: set[str]) -> list[dict]:
    """The teams the caller may share a team item with: theirs, but not its own or one that has it.

    Args:
        conn: Open connection.
        user: The caller.
        ra: Their access to the item (a member of the owning team).
        shared_with: The teams it is shared with already.

    Returns:
        list[dict]: ``{team_id, name}`` by name; empty without ``share_outside``.
    """
    if not ra.can("share_outside"):
        return []
    return [
        {"team_id": str(t["id"]), "name": t.get("name")}
        for t in TeamsRepository(conn).workspaces_for(user)
        if str(t["id"]) != ra.team_id and str(t["id"]) not in shared_with
    ]


def owner_dialog_fields(conn, ra: ResourceAccess, user: str) -> dict:
    """What the share dialog of a team item adds for a member of the owning team.

    Returns:
        dict: ``outside_policy``, ``outside_shares`` (:func:`outside_share_rows` of this item),
        ``share_targets`` (:func:`share_targets`), ``warning_kind`` (:func:`_warning_kind`) and
        ``team_models`` (:func:`_team_models`: the team's custom models an agent runs on, ``[{id, name}]``).
    """
    policy = team_policy(conn, ra.team_id)
    shares = outside_share_rows(conn, ra.team_id, ra.team_role, policy, (ra.resource_type, ra.resource_id))
    return {
        "outside_policy": policy,
        "outside_shares": shares,
        "share_targets": share_targets(conn, user, ra, {s["team_id"] for s in shares}),
        "warning_kind": _warning_kind(conn, ra),
        "team_models": _team_models(conn, ra),
    }


def receiver_dialog(conn, ra: ResourceAccess) -> dict:
    """The share dialog of an item another team shared with the reader's team.

    Only where it lives for them and where it comes from: nothing of the owning team (its size, its
    outside access, the other teams it shares with), and nothing to share it on with.
    """
    team = TeamsRepository(conn).get(ra.via_team_id) or {}
    return {
        **ra.payload(),
        "success": True,
        "shares": [],
        "workspace": {"kind": "team", "team_id": ra.via_team_id, "name": team.get("name")},
        "outside_shares": [],
        "share_targets": [],
    }


def _borrowed_agent_refusal(conn, agent_id: str, user: str) -> Optional[Response]:
    """The 403 that keeps an agent using items shared into its team from being passed to another team."""
    # Lazy: graph_checks imports the workflow routes, which import most of the user API.
    from docsgpt.api.user.agents.graph_checks import agent_borrowed_refs

    agent = AgentsRepository(conn).get_by_id(agent_id) or {}
    borrowed = agent_borrowed_refs(conn, agent)
    if not borrowed:
        return None
    body, status = borrowed_refusal(conn, borrowed, user, agent)
    them = "it" if len(borrowed) == 1 else "them"
    body["message"] = body["error"] = (
        "This agent uses tools or sources it doesn't own, and an agent that uses someone else's tools or "
        f"sources can't be shared with another team. Remove {them} from the agent first."
    )
    return make_response(jsonify(body), status)


def _team_connection_refusal(conn, resource_type: str, resource_id: str) -> Optional[Response]:
    """The 409 that keeps a tool on the team's account, or an agent using one, from another team.

    Args:
        conn: Open connection.
        resource_type: The shared item's kind.
        resource_id: The item.

    Returns:
        The refusal, or None for an item that runs on no team account.
    """
    # Lazy: graph_checks imports the workflow routes, which import most of the user API.
    from docsgpt.api.user.agents.graph_checks import (
        agent_team_connection_tools,
        team_connection_outside_body,
        team_connection_tools,
    )

    if resource_type == "tool":
        tools = team_connection_tools(conn, [resource_id])
    elif resource_type == "agent":
        tools = agent_team_connection_tools(conn, AgentsRepository(conn).get_by_id(resource_id) or {})
    else:
        return None
    if not tools:
        return None
    body = team_connection_outside_body(tools)
    if resource_type == "tool":
        body["message"] = f'"{tools[0]["name"]}" is signed in to the team\'s account, so it stays inside the team.'
    return make_response(jsonify(body), 409)


def share_team_item(
    conn, user: str, team_id: str, resource_type: str, resource_id: str, access_level: str,
    target_user_id: Optional[str],
) -> tuple[Optional[Response], Optional[dict]]:
    """Share a team's item with the whole of another team, inside the caller's transaction.

    Args:
        conn: Open connection in a transaction.
        user: The caller.
        team_id: The receiving team (from the URL).
        resource_type: ``agent``, ``source``, ``tool`` or ``prompt``.
        resource_id: The item, owned by a team's principal.
        access_level: What the body asked for; only ``viewer``.
        target_user_id: A member the body named; a team item goes to the whole team only.

    Returns:
        ``(refusal, None)``, or ``(None, share)`` with the share row and ``created`` (False when the
        team already had it; nothing is written or audited then).
    """
    if resolve(conn, resource_type, resource_id, user) is None:
        return _error(404, "not_found", f"{resource_type.capitalize()} not found"), None
    if target_user_id:
        return _error(400, CODE_WHOLE_TEAM_ONLY, "A team's item is shared with a whole team, not one member"), None
    if access_level != "viewer":
        return _error(400, CODE_VIEWER_ONLY, "Another team gets a team's item at Viewer level only"), None
    owner = resource_owner(conn, resource_type, resource_id)
    owner_team = team_of_principal(owner)
    receiving = canonical_team_id(team_id)
    if owner_team is None or receiving is None:
        return _error(404, "not_found", f"{resource_type.capitalize()} not found"), None
    if receiving == owner_team:
        return _error(400, CODE_SAME_TEAM, "This item already belongs to that team"), None
    # Before the policy row, as every outside-access write takes them: a move of the item waits for
    # this share, and the policy can't change under it.
    lock_owner_items(conn, owner)
    policy = team_policy(conn, owner_team, lock="share")
    role = team_role_for(conn, user, owner_team)
    if role is not None and policy == POLICY_LOCKED:
        return _error(403, CODE_TEAM_LOCKED, "This team is locked: its items can't be shared outside it"), None
    try:
        ra = require(conn, resource_type, resource_id, user, "share_outside")
    except AccessDenied as denied:
        if denied.status == 404:
            return _error(404, "not_found", denied.message), None
        return _error(403, CODE_ROLE_REQUIRED, "Your role in this team can't share its items outside it"), None
    if ra.via_team_id or ra.team_id != owner_team:
        # Belt and braces: only the owning team's own members ever hold ``share_outside``.
        return _error(403, CODE_ROLE_REQUIRED, "Only the team that owns this item can share it"), None
    if team_role_for(conn, user, receiving) is None:
        return _error(403, CODE_NOT_MEMBER, "You can only share with a team you are in"), None
    refusal = _team_connection_refusal(conn, resource_type, ra.resource_id)
    if refusal is not None:
        return refusal, None
    if resource_type == "agent":
        refusal = _borrowed_agent_refusal(conn, ra.resource_id, user)
        if refusal is not None:
            return refusal, None
    share = TeamItemSharesRepository(conn).share(owner_team, receiving, resource_type, ra.resource_id, user)
    if share.get("created"):
        _audit(
            conn, user, "team.item_shared_with_team", team_id=owner_team, to_team_id=receiving,
            resource_type=resource_type, resource_id=ra.resource_id,
        )
    return None, share


def revoke_team_item(conn, user: str, team_id: str, resource_type: str, resource_id: str) -> Response:
    """Stop sharing a team's item with ``team_id``, from either side.

    The owning team: whoever its policy lets take items outside, and its Admins and Owner always,
    locked too. The receiving team: its Admins and Owner. Anyone else in either team gets 403,
    anyone in neither 404. Audited with the ``side`` that removed it.

    Args:
        conn: Open connection in a transaction.
        user: The caller.
        team_id: The receiving team (from the URL).
        resource_type: The item's kind.
        resource_id: The item.

    Returns:
        The response: ``{success, side}``, ``success`` False when there was no such share.
    """
    receiving = canonical_team_id(team_id)
    row = TeamItemSharesRepository(conn).get(team_id, resource_type, resource_id) if receiving else None
    owner_team = str(row["owner_team_id"]) if row else team_of_principal(
        resource_owner(conn, resource_type, resource_id)
    )
    owner_role = team_role_for(conn, user, owner_team) if owner_team else None
    receiving_role = team_role_for(conn, user, receiving) if receiving else None
    if owner_role is not None and _may_revoke_as_owner(owner_role, team_policy(conn, owner_team)):
        side = "owner"
    elif role_at_least(receiving_role, "admin"):
        side = "receiver"
    elif owner_role is not None or receiving_role is not None:
        return _error(403, CODE_ROLE_REQUIRED, "Your role can't stop this share")
    else:
        return _error(404, "not_found", "Not found")
    revoked = TeamItemSharesRepository(conn).revoke(team_id, resource_type, resource_id) if row else False
    if revoked:
        _audit(
            conn, user, "team.item_unshared_from_team", team_id=owner_team, to_team_id=receiving,
            resource_type=resource_type, resource_id=str(row["resource_id"]), side=side,
        )
    return make_response(jsonify({"success": revoked, "side": side}), 200)


def _published_agents(conn, team_id: str, role: str, policy: str, user: str) -> list[dict]:
    """The team's agents with an API key, public link or webhook on, each with its ``outside_access`` block."""
    # Imported here: the agents package pulls in most of the API.
    from docsgpt.api.user.agents import sharing as agent_sharing

    rows = conn.execute(
        text(f"SELECT a.* FROM agents a WHERE a.user_id = :principal AND {OUTSIDE_ACCESS_ON_SQL} ORDER BY a.name, a.id"),
        {"principal": principal_id(team_id)},
    ).mappings().fetchall()
    checks = PayerChecks()
    out = []
    for row in rows:
        agent = dict(row)
        ra = build_team("agent", str(agent["id"]), agent["user_id"], role, policy=policy)
        out.append({
            "agent_id": str(agent["id"]),
            "name": agent.get("name"),
            "outside_access": agent_sharing.outside_access_state(conn, agent, ra, user, checks=checks),
        })
    return out


@teams_ns.route("/teams/<string:team_id>/outside_policy")
class TeamOutsidePolicy(Resource):
    def put(self, team_id):
        """Change who may take the team's items outside: ``admins``, ``editors`` or ``locked``.

        Admins and the Owner while it isn't locked; once locked only the Owner (403
        ``policy_owner_only`` for an Admin), and an instance admin gets no way in (404 outside the
        team; ownership is transferred instead). The team row is locked for the change. A change is
        audited as ``team.outside_policy_changed``; the same policy again answers ``changed: false``.
        """
        user = _current_user()
        if not user:
            return make_response(jsonify({"success": False, "message": "Authentication required"}), 401)
        new = (request.get_json(silent=True) or {}).get("policy")
        if not isinstance(new, str) or new not in POLICIES:
            return _error(400, "invalid_policy", "policy is admins, editors or locked")
        try:
            with db_session() as conn:
                role = team_role_for(conn, user, team_id) if looks_like_uuid(str(team_id)) else None
                if role is None:
                    return _error(404, "team_not_found", "Not found")
                current = team_policy(conn, team_id, lock="update")
                if not may_set_policy(role, current, new):
                    if role_at_least(role, "admin"):
                        return _error(403, CODE_POLICY_OWNER_ONLY, "Only the team's Owner can unlock it")
                    return _error(403, CODE_ROLE_REQUIRED, "This needs the admin role")
                changed = new != current
                if changed:
                    TeamsRepository(conn).set_outside_policy(team_id, new)
                    _audit(conn, user, "team.outside_policy_changed", team_id=str(team_id), before=current, after=new)
            return make_response(
                jsonify({
                    "success": True,
                    "changed": changed,
                    "outside_policy": new,
                    "can_set_outside_policy": can_set_outside_policy(role, new),
                }),
                200,
            )
        except Exception as err:
            logger.error("Set outside policy failed: %s", err, exc_info=True)
            return make_response(jsonify({"success": False}), 400)


@teams_ns.route("/teams/<string:team_id>/outside")
class TeamOutside(Resource):
    def get(self, team_id):
        """What the team takes outside: its items shared with other teams, and its agents with outside access.

        Every member reads it (404 to anyone else): ``outside_policy``, ``can_set_outside_policy``,
        ``shares`` (see :func:`outside_share_rows`; ``can_revoke`` per the reader) and ``published``
        (``{agent_id, name, outside_access}``, the agent page's block, read-only here).
        """
        user = _current_user()
        if not user:
            return make_response(jsonify({"success": False, "message": "Authentication required"}), 401)
        try:
            with db_readonly() as conn:
                role = team_role_for(conn, user, team_id) if looks_like_uuid(str(team_id)) else None
                if role is None:
                    return _error(404, "team_not_found", "Not found")
                team_id = canonical_team_id(team_id)
                policy = team_policy(conn, team_id)
                body = {
                    "success": True,
                    "outside_policy": policy,
                    "can_set_outside_policy": can_set_outside_policy(role, policy),
                    "shares": outside_share_rows(conn, team_id, role, policy),
                    "published": _published_agents(conn, team_id, role, policy, user),
                }
            return make_response(jsonify(body), 200)
        except Exception as err:
            logger.error("List outside shares failed: %s", err, exc_info=True)
            return make_response(jsonify({"success": False}), 400)
