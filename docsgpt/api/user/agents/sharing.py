"""Agent management sharing functionality."""

import datetime
import secrets
from typing import Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import fields, Namespace, Resource
from sqlalchemy import text as _sql_text

from docsgpt.api import api
from docsgpt.api.audit import record_event
from docsgpt.core.settings import settings
from docsgpt.api.user.agents.graph_checks import refuse_borrowed_outside_access, refuse_unfinished_graph
from docsgpt.api.user.agents.starters import stored_starters
from docsgpt.api.user.base import resolve_tool_details
from docsgpt.api.user.resource_access import (
    AccessDenied,
    ResourceAccess,
    best_effort,
    require,
    resolve,
)
from docsgpt.api.user.received_shares import in_request_workspace
from docsgpt.quotas.pause import PayerChecks, outside_access_pause
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.agents import AgentsRepository, agent_row_to_dict, expose_prompt_preset
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.utils import generate_image_url
from docsgpt.workspaces.locks import lock_owner_items
from docsgpt.workspaces.principal import is_principal_id

agents_sharing_ns = Namespace(
    "agents", description="Agent management operations", path="/api"
)


# A caller who reached an agent only through its public link may chat with it
# and pin it; a team grant, when there is one, gives more. ``origin: link``
# says so outright, so the composer knows the publisher pays for the chat
# rather than reading it from the fields a grant would add.
LINK_SHARED_ACCESS = {"access": "viewer", "allowed_actions": ["pin", "use"], "origin": "link"}


def access_payer_fields(ra: ResourceAccess, agent: dict, user: str, *, turning_on: bool) -> dict:
    """The ``access_payer_id`` write that goes with outside access a team Admin sets up: that Admin pays for it.

    A team has no credit, so whoever turns on a team agent's first way in
    (key, public link or webhook) pays for the traffic that comes in through
    them all. Turning on a second way in, rotating something already on, or
    any other save keeps the payer: only Take over moves it. It is filled in
    when none is recorded. A personal agent records none: its owner pays.

    Args:
        ra: The caller's access to the agent (from ``require(..., "manage_access_details")``).
        agent: The agent row before the write.
        user: The caller.
        turning_on: True when this write turns outside access on (a new key, link or webhook).

    Returns:
        dict: ``{"access_payer_id": user}`` to merge into the agent update, or ``{}``.
    """
    if not ra.is_team_item or is_principal_id(user):
        return {}
    if not agent.get("access_payer_id") or (turning_on and not outside_access_kinds(agent)):
        return {"access_payer_id": user}
    return {}


def outside_access_kinds(agent: dict) -> list[str]:
    """Which ways in from outside are switched on, in a fixed order: ``api_key``, ``public_link``, ``webhook``.

    Args:
        agent: The agent row.

    Returns:
        list[str]: The kinds that are on; empty when none is.
    """
    switched_on = {
        "api_key": bool(agent.get("key")),
        "public_link": bool(agent.get("shared") and agent.get("shared_token")),
        "webhook": bool(agent.get("incoming_webhook_token")),
    }
    return [kind for kind, on in switched_on.items() if on]


def outside_access_state(
    conn, agent: dict, ra: ResourceAccess, user: str, *, checks: Optional[PayerChecks] = None
) -> dict:
    """An agent's ``outside_access`` block: what is on, who pays, why it is paused and whether ``user`` may take over.

    Who pays, and why and until when it is paused, are for a reader who
    manages the access (``manage_access_details``, or the person owner);
    anyone else (a team item's share dialog) reads only what is on.

    Args:
        conn: Open database connection.
        agent: The agent row.
        ra: The reader's access to the agent.
        user: The reader.
        checks: The request's :class:`PayerChecks`, to share across a list; a fresh one when None.

    Returns:
        dict: ``api_key``, ``public_link``, ``webhook`` (bools); ``paid_by`` (``{user_id, label}`` of a team
        agent's payer, the label their email when on file, else their id; None on a personal agent, whose
        owner pays, and while nothing is on or nobody pays); ``paused_for`` (``{reason, until}`` or None);
        ``can_take_over`` (a team agent with something on, the reader holds ``manage_access_details`` and
        is not already the payer). ``paid_by`` and ``paused_for`` are None for a reader without
        ``manage_access_details``.
    """
    kinds = outside_access_kinds(agent)
    manages = ra.can("manage_access_details")
    payer = agent.get("access_payer_id") if (ra.is_team_item and kinds) else None
    paid_by = None
    if payer and manages:
        paid_by = {"user_id": payer, "label": UsersRepository(conn).emails_for([payer]).get(payer) or payer}
    pause = best_effort(
        conn, "the agent's outside-access pause", lambda: outside_access_pause(conn, agent, checks=checks), None,
    ) if manages else None
    return {
        "api_key": "api_key" in kinds,
        "public_link": "public_link" in kinds,
        "webhook": "webhook" in kinds,
        "paid_by": paid_by,
        "paused_for": pause.payload() if pause else None,
        "can_take_over": bool(
            ra.is_team_item and kinds and manages
            and not is_principal_id(user) and payer != user
        ),
    }


def _link_access(conn, agent_id: str, user_id) -> dict:
    """The ``access`` payload for an agent the caller reached by share link.

    Args:
        conn: Open database connection.
        agent_id: The agent's id.
        user_id: The caller, or None when anonymous.

    Returns:
        The caller's own access (owner or a team grant) when they have one,
        else viewer with ``pin`` and ``use``. Another team's agent shared
        with the caller's team lives in that team (the one the request is
        made from, when several receive it), so the page follows it there.
    """
    if user_id:
        ra = in_request_workspace(conn, resolve(conn, "agent", agent_id, user_id), user_id)
        if ra is not None:
            return ra.payload()
    return dict(LINK_SHARED_ACCESS)


def _serialize_agent_basic(agent: dict) -> dict:
    """Shape a PG agent row into the API response dict.

    The owner's user id is deliberately not included: a share link is public.
    """
    source_id = agent.get("source_id")
    return {
        "id": str(agent["id"]),
        "name": agent.get("name", ""),
        "image": (
            generate_image_url(
                agent["image"], agent["id"], agent.get("user_id")
            )
            if agent.get("image")
            else ""
        ),
        "description": agent.get("description", ""),
        "starters": stored_starters(agent),
        "source": str(source_id) if source_id else "",
        "chunks": str(agent["chunks"]) if agent.get("chunks") is not None else "0",
        "retriever": agent.get("retriever", "classic") or "classic",
        "prompt_id": str(agent["prompt_id"]) if agent.get("prompt_id") else "default",
        "tools": agent.get("tools", []) or [],
        "tool_details": resolve_tool_details(agent.get("tools", []) or []),
        "agent_type": agent.get("agent_type", "") or "",
        "status": agent.get("status", "") or "",
        "json_schema": agent.get("json_schema"),
        "limited_token_mode": agent.get("limited_token_mode", False),
        "token_limit": agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"],
        "limited_request_mode": agent.get("limited_request_mode", False),
        "request_limit": agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"],
        "created_at": agent.get("created_at", ""),
        "updated_at": agent.get("updated_at", ""),
        "shared": bool(agent.get("shared", False)),
        "shared_token": agent.get("shared_token", "") or "",
        "shared_metadata": agent.get("shared_metadata", {}) or {},
    }


@agents_sharing_ns.route("/shared_agent")
class SharedAgent(Resource):
    @api.doc(
        params={
            "token": "Shared token of the agent",
        },
        description="Get a shared agent by token or ID",
    )
    def get(self):
        shared_token = request.args.get("token")

        if not shared_token:
            return make_response(
                jsonify({"success": False, "message": "Token or ID is required"}), 400
            )
        try:
            with db_readonly() as conn:
                shared_agent = AgentsRepository(conn).find_by_shared_token(
                    shared_token,
                )
            if not shared_agent:
                return make_response(
                    jsonify({"success": False, "message": "Shared agent not found"}),
                    404,
                )
            agent_id = str(shared_agent["id"])
            data = _serialize_agent_basic(shared_agent)

            if data["tools"]:
                enriched_tools = []
                for detail in data["tool_details"]:
                    enriched_tools.append(detail.get("name", ""))
                data["tools"] = enriched_tools
            decoded_token = getattr(request, "decoded_token", None)
            user_id = decoded_token.get("sub") if decoded_token else None
            if user_id:
                owner_id = shared_agent.get("user_id")

                if user_id != owner_id:
                    with db_session() as conn:
                        users_repo = UsersRepository(conn)
                        users_repo.upsert(user_id)
                        users_repo.add_shared(user_id, agent_id)
            with db_readonly() as conn:
                data.update(_link_access(conn, agent_id, user_id))
            return make_response(jsonify(data), 200)
        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agent: {err}")
            return make_response(jsonify({"success": False}), 400)


@agents_sharing_ns.route("/shared_agents")
class SharedAgents(Resource):
    @api.doc(description="Get shared agents explicitly shared with the user")
    def get(self):
        try:
            decoded_token = request.decoded_token
            if not decoded_token:
                return make_response(jsonify({"success": False}), 401)
            user_id = decoded_token.get("sub")

            with db_session() as conn:
                users_repo = UsersRepository(conn)
                user_doc = users_repo.upsert(user_id)
                shared_with_ids = (
                    user_doc.get("agent_preferences", {}).get("shared_with_me", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                # Keep only UUID-shaped ids; ObjectId leftovers are stripped below.
                uuid_ids = [sid for sid in shared_with_ids if looks_like_uuid(sid)]
                non_uuid_ids = [sid for sid in shared_with_ids if not looks_like_uuid(sid)]

                if uuid_ids:
                    result = conn.execute(
                        _sql_text(
                            "SELECT * FROM agents "
                            "WHERE id = ANY(CAST(:ids AS uuid[])) "
                            "AND shared = true"
                        ),
                        {"ids": uuid_ids},
                    )
                    shared_agents = [expose_prompt_preset(dict(row._mapping)) for row in result.fetchall()]
                else:
                    shared_agents = []

                found_ids_set = {str(agent["id"]) for agent in shared_agents}
                stale_ids = [sid for sid in uuid_ids if sid not in found_ids_set]
                stale_ids.extend(non_uuid_ids)
                if stale_ids:
                    users_repo.remove_shared_bulk(user_id, stale_ids)

                pinned_ids = set(
                    user_doc.get("agent_preferences", {}).get("pinned", [])
                    if isinstance(user_doc.get("agent_preferences"), dict)
                    else []
                )
                access_by_id = {
                    str(agent["id"]): _link_access(conn, str(agent["id"]), user_id)
                    for agent in shared_agents
                }

            list_shared_agents = []
            for agent in shared_agents:
                agent_id_str = str(agent["id"])
                list_shared_agents.append(
                    {
                        "id": agent_id_str,
                        "name": agent.get("name", ""),
                        "description": agent.get("description", ""),
                        "starters": stored_starters(agent),
                        "image": (
                            generate_image_url(
                                agent["image"], agent["id"], agent.get("user_id")
                            )
                            if agent.get("image")
                            else ""
                        ),
                        "tools": agent.get("tools", []) or [],
                        "tool_details": resolve_tool_details(
                            agent.get("tools", []) or []
                        ),
                        "agent_type": agent.get("agent_type", "") or "",
                        "status": agent.get("status", "") or "",
                        "json_schema": agent.get("json_schema"),
                        "limited_token_mode": agent.get("limited_token_mode", False),
                        "token_limit": agent.get("token_limit") or settings.DEFAULT_AGENT_LIMITS["token_limit"],
                        "limited_request_mode": agent.get("limited_request_mode", False),
                        "request_limit": agent.get("request_limit") or settings.DEFAULT_AGENT_LIMITS["request_limit"],
                        "created_at": agent.get("created_at", ""),
                        "updated_at": agent.get("updated_at", ""),
                        "pinned": agent_id_str in pinned_ids,
                        "shared": bool(agent.get("shared", False)),
                        "shared_token": agent.get("shared_token", "") or "",
                        "shared_metadata": agent.get("shared_metadata", {}) or {},
                        **access_by_id[agent_id_str],
                    }
                )

            return make_response(jsonify(list_shared_agents), 200)
        except Exception as err:
            current_app.logger.error(f"Error retrieving shared agents: {err}")
            return make_response(jsonify({"success": False}), 400)


@agents_sharing_ns.route("/share_agent")
class ShareAgent(Resource):
    @api.expect(
        api.model(
            "ShareAgentModel",
            {
                "id": fields.String(required=True, description="ID of the agent"),
                "shared": fields.Boolean(
                    required=True, description="Share or unshare the agent"
                ),
                "username": fields.String(
                    required=False, description="Name of the user"
                ),
            },
        )
    )
    @api.doc(description="Share or unshare an agent")
    def put(self):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")

        data = request.get_json()
        if not data:
            return make_response(
                jsonify({"success": False, "message": "Missing JSON body"}), 400
            )
        agent_id = data.get("id")
        shared = data.get("shared")
        username = data.get("username", "")

        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "ID is required"}), 400
            )
        if shared is None:
            return make_response(
                jsonify(
                    {
                        "success": False,
                        "message": "Shared parameter is required and must be true or false",
                    }
                ),
                400,
            )
        shared_token = None
        try:
            with db_session() as conn:
                repo = AgentsRepository(conn)
                # The public link is an access detail; it is written as the owner.
                try:
                    ra = require(conn, "agent", agent_id, user, "manage_access_details")
                except AccessDenied as denied:
                    return make_response(
                        jsonify({"success": False, "message": denied.message}), denied.status
                    )
                owner_id = ra.owner_id
                agent = repo.get_by_id(ra.resource_id)
                if not agent:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}), 404
                    )
                if shared:
                    # Anyone with the link runs the agent's graph: a workflow
                    # agent's must be a finished one.
                    refusal = refuse_unfinished_graph(conn, agent)
                    # A new link reaches people the owner never shared with:
                    # not for an agent using someone else's tool or source.
                    # Replacing a link it has opens nothing new.
                    if refusal is None and not (agent.get("shared") and agent.get("shared_token")):
                        # A move of the owner's items runs wholly before this check or after this link.
                        lock_owner_items(conn, owner_id)
                        # Lock, then read again: a save that held the lock has committed the items it added.
                        agent = repo.get_by_id(ra.resource_id)
                        if not agent:
                            return make_response(
                                jsonify({"success": False, "message": "Agent not found"}), 404
                            )
                        refusal = refuse_borrowed_outside_access(conn, agent, user)
                    if refusal is not None:
                        return refusal
                    shared_metadata = {
                        "shared_by": username,
                        "shared_at": datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat(),
                    }
                    shared_token = secrets.token_urlsafe(32)
                    # A team Admin who turns the link on pays for its traffic.
                    already_on = bool(agent.get("shared") and agent.get("shared_token"))
                    repo.update(
                        str(agent["id"]), owner_id,
                        {
                            "shared": True,
                            "shared_token": shared_token,
                            "shared_metadata": shared_metadata,
                            **access_payer_fields(ra, agent, user, turning_on=not already_on),
                        },
                    )
                else:
                    repo.update(
                        str(agent["id"]), owner_id,
                        {
                            "shared": False,
                            "shared_token": None,
                            "shared_metadata": None,
                        },
                    )
        except Exception as err:
            current_app.logger.error(f"Error sharing/unsharing agent: {err}", exc_info=True)
            return make_response(jsonify({"success": False, "error": "Failed to update agent sharing status"}), 400)
        return make_response(
            jsonify({"success": True, "shared_token": shared_token}), 200
        )


def _refusal(status: int, error: str, message: str):
    return make_response(jsonify({"success": False, "error": error, "message": message}), status)


@agents_sharing_ns.route("/agents/<string:agent_id>/outside_access/take_over")
class TakeOverOutsideAccess(Resource):
    @api.doc(
        description=(
            "Become the person who pays for a team agent's outside access (its API key, public link and "
            "webhook). Needs the Admin role in the team; not available on a personal agent, whose owner "
            "pays. Returns {success, outside_access, changed}; changed is false when the caller already "
            "pays. Refusals: 404 agent_not_found, 403 workspace_role_required, 409 take_over_team_only, "
            "409 no_outside_access."
        ),
    )
    def post(self, agent_id):
        decoded_token = request.decoded_token
        if not decoded_token:
            return make_response(jsonify({"success": False}), 401)
        user = decoded_token.get("sub")
        try:
            with db_session() as conn:
                ra = resolve(conn, "agent", agent_id, user)
                if ra is None:
                    return _refusal(404, "agent_not_found", "Agent not found")
                if not ra.is_team_item:
                    return _refusal(
                        409, "take_over_team_only", "Only a team's agent can be taken over: here its owner pays.",
                    )
                if is_principal_id(user) or not ra.can("manage_access_details"):
                    return _refusal(
                        403, "workspace_role_required", "Taking over needs the admin role in the team",
                    )
                # Locked, so two Admins taking over at once each see the payer the other left.
                agent = agent_row_to_dict(
                    conn.execute(
                        _sql_text("SELECT * FROM agents WHERE id = CAST(:id AS uuid) FOR UPDATE"),
                        {"id": ra.resource_id},
                    ).fetchone()
                )
                if not agent:
                    return _refusal(404, "agent_not_found", "Agent not found")
                kinds = outside_access_kinds(agent)
                if not kinds:
                    return _refusal(409, "no_outside_access", "This agent has no API key, public link or webhook")
                previous = agent.get("access_payer_id")
                changed = previous != user
                if changed:
                    # A bookkeeping column: the agent's updated_at stays.
                    AgentsRepository(conn).update(str(agent["id"]), ra.owner_id, {"access_payer_id": user})
                    agent["access_payer_id"] = user
                    record_event(
                        conn,
                        "team.outside_access_taken_over",
                        actor=user,
                        team_id=ra.team_id,
                        agent_id=str(agent["id"]),
                        access=kinds,
                        **{"from": previous, "to": user},
                    )
                state = outside_access_state(conn, agent, ra, user)
        except Exception as err:
            current_app.logger.error(f"Error taking over outside access: {err}", exc_info=True)
            return make_response(jsonify({"success": False}), 400)
        return make_response(jsonify({"success": True, "outside_access": state, "changed": changed}), 200)
