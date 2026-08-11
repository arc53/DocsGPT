"""Guardrails catalog and decision-journal routes."""

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from application.api import api
from application.api.user.team_sharing import team_access_for
from application.core.settings import settings
from application.guardrails.checks.patterns import DEFAULT_PII_ENTITIES, PII_PATTERNS
from application.guardrails.config import DEFAULT_BLOCK_MESSAGE, MODES
from application.guardrails.guardrail_creator import GuardrailCreator
from application.guardrails import runtime as guardrails_runtime
from application.guardrails.types import ACTIONS_BY_STAGE, Stage
from application.storage.db.repositories.agents import AgentsRepository
from application.storage.db.repositories.guardrail_events import (
    GuardrailEventsRepository,
)
from application.storage.db.session import db_readonly

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


def _readable_agent(conn, agent_id: str, user: str):
    """Return the agent row when the caller may read it, else None."""
    repo = AgentsRepository(conn)
    agent = repo.get_any(agent_id, user)
    if agent:
        return agent
    if team_access_for(conn, user, "agent", agent_id):
        return repo.get_by_id(agent_id)
    return None


@agents_guardrails_ns.route("/guardrails/events")
class GuardrailEvents(Resource):
    @api.doc(
        params={"agent_id": "Agent ID", "limit": "Max rows (default 100)",
                "offset": "Row offset"},
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
        with db_readonly() as conn:
            agent = _readable_agent(conn, agent_id, user)
            if not agent:
                return make_response(
                    jsonify({"success": False, "message": "Agent not found"}), 404
                )
            # Query on the row's UUID, not the caller's argument: a legacy
            # 24-hex Mongo id resolves fine above but would blow up the cast.
            # Rows stay scoped to the requesting user even on a shared agent —
            # another member's blocked prompts are not this caller's to read.
            events = GuardrailEventsRepository(conn).list_for_agent(
                str(agent["id"]), user, limit=limit, offset=offset
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
            if agent_id:
                agent = _readable_agent(conn, agent_id, user)
                if not agent:
                    return make_response(
                        jsonify({"success": False, "message": "Agent not found"}), 404
                    )
                scoped_id = str(agent["id"])
            summary = GuardrailEventsRepository(conn).summary_for_user(
                user, days=days, agent_id=scoped_id
            )
        return make_response(jsonify({"success": True, **summary}), 200)
