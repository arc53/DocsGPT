"""Guardrails catalog and decision-journal routes."""

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.api.user.resource_access import AccessDenied, ResourceAccess, require
from docsgpt.core.settings import settings
from docsgpt.guardrails.checks.patterns import DEFAULT_PII_ENTITIES, PII_PATTERNS
from docsgpt.guardrails.config import DEFAULT_BLOCK_MESSAGE, MODES
from docsgpt.guardrails.guardrail_creator import GuardrailCreator
from docsgpt.guardrails import runtime as guardrails_runtime
from docsgpt.guardrails.types import ACTIONS_BY_STAGE, Stage
from docsgpt.storage.db.repositories.agents import AgentsRepository
from docsgpt.storage.db.repositories.guardrail_events import (
    EVENT_OUTCOMES,
    GuardrailEventsRepository,
)
from docsgpt.storage.db.session import db_readonly

agents_guardrails_ns = Namespace(
    "guardrails", description="Agent guardrail configuration and audit", path="/api"
)


@agents_guardrails_ns.route("/guardrails/catalog")
class GuardrailCatalog(Resource):
    @api.doc(description="List available guardrail checks and their capabilities")
    def get(self):
        if not request.decoded_token:
            return {"success": False}, 401
        floor = guardrails_runtime.instance_floor()
        return make_response(
            jsonify(
                {
                    "success": True,
                    "enabled": bool(settings.GUARDRAILS_ENABLED),
                    "checks": GuardrailCreator.catalog(),
                    "stages": [s.value for s in Stage],
                    "modes": list(MODES),
                    "actions_by_stage": {
                        stage.value: sorted(a.value for a in actions)
                        for stage, actions in ACTIONS_BY_STAGE.items()
                    },
                    "default_block_message": DEFAULT_BLOCK_MESSAGE,
                    "pii_entities": sorted(PII_PATTERNS),
                    "default_pii_entities": DEFAULT_PII_ENTITIES,
                    # Only which (check, stage) pairs the floor claims, and the
                    # action it imposes. The settings stay server-side: handing
                    # every authenticated user the banned-term list and the
                    # policy prompts makes evading them trivial.
                    "floor": (
                        {
                            "mode": floor.mode,
                            "fail_open": floor.fail_open,
                            "controls": [
                                {
                                    "check": c.check,
                                    "stage": c.stage.value,
                                    "action": c.action.value,
                                }
                                for c in floor.controls
                            ],
                        }
                        if floor and floor.enabled
                        else None
                    ),
                }
            ),
            200,
        )


def _logs_access(conn, agent_id: str, user: str) -> tuple[dict, ResourceAccess]:
    """The agent row and the caller's access, for reading its guardrail journal.

    Args:
        conn: Open database connection.
        agent_id: The agent's id (UUID or legacy).
        user: The caller.

    Returns:
        ``(agent, access)``; rows are read as ``access.owner_id``, so a team
        member with ``view_logs`` sees exactly what the owner sees.

    Raises:
        AccessDenied: 404 when the agent isn't visible, 403 without ``view_logs``.
    """
    ra = require(conn, "agent", agent_id, user, "view_logs")
    agent = AgentsRepository(conn).get_by_id(ra.resource_id)
    if agent is None:
        raise AccessDenied(404, "Agent not found")
    return agent, ra


def _denied(err: AccessDenied):
    return make_response(jsonify({"success": False, "message": err.message}), err.status)


@agents_guardrails_ns.route("/guardrails/events")
class GuardrailEvents(Resource):
    @api.doc(
        params={
            "agent_id": "Agent ID",
            "limit": "Max rows (default 100)",
            "offset": "Row offset",
            "days": "Trailing window in days, clamped to 1-365 (optional; invalid values are ignored)",
            "check": "Exact check name (optional)",
            "outcome": f"One of {', '.join(EVENT_OUTCOMES)} (optional; unknown values are ignored)",
        },
        description="List guardrail decisions recorded for an agent",
    )
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token["sub"]
        agent_id = request.args.get("agent_id")
        if not agent_id:
            return make_response(
                jsonify({"success": False, "message": "agent_id required"}), 400
            )
        try:
            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            return make_response(
                jsonify({"success": False, "message": "limit/offset must be integers"}),
                400,
            )
        # Filters are optional and forgiving: a bad value drops that filter
        # rather than failing the page, so a stale UI state still loads.
        try:
            days = int(request.args["days"])
        except (KeyError, TypeError, ValueError):
            days = None
        check = request.args.get("check") or None
        outcome = request.args.get("outcome")
        if outcome not in EVENT_OUTCOMES:
            outcome = None
        with db_readonly() as conn:
            try:
                agent, ra = _logs_access(conn, agent_id, user)
            except AccessDenied as denied:
                return _denied(denied)
            # Query on the row's UUID, not the caller's argument: a legacy
            # 24-hex Mongo id resolves fine above but would blow up the cast.
            # Rows are the owner's view: ``view_logs`` shows a team member
            # what the owner sees, never other members' own chats.
            events = GuardrailEventsRepository(conn).list_for_agent(
                str(agent["id"]), ra.owner_id, limit=limit, offset=offset,
                days=days, check=check, outcome=outcome,
            )
        return make_response(jsonify({"success": True, "events": events}), 200)


@agents_guardrails_ns.route("/guardrails/summary")
class GuardrailSummary(Resource):
    @api.doc(
        params={
            "days": "Trailing window in days (default 30)",
            "agent_id": "Scope the aggregate to one agent (optional)",
        },
        description="Aggregate guardrail activity for the caller",
    )
    def get(self):
        if not (decoded_token := request.decoded_token):
            return {"success": False}, 401
        user = decoded_token["sub"]
        try:
            days = int(request.args.get("days", 30))
        except (TypeError, ValueError):
            return make_response(
                jsonify({"success": False, "message": "days must be an integer"}), 400
            )
        agent_id = request.args.get("agent_id")
        with db_readonly() as conn:
            scoped_id = None
            scope_user = user
            if agent_id:
                try:
                    agent, ra = _logs_access(conn, agent_id, user)
                except AccessDenied as denied:
                    return _denied(denied)
                scoped_id = str(agent["id"])
                scope_user = ra.owner_id
            summary = GuardrailEventsRepository(conn).summary_for_user(
                scope_user, days=days, agent_id=scoped_id
            )
        return make_response(jsonify({"success": True, **summary}), 200)
