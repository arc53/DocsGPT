"""Admin > Guardrails: the rules every agent follows, MCP description warnings, and the injection model's cost.

Behind ``@admin_required``. The floor is the ``GuardrailsConfig`` fragment
every agent inherits and cannot weaken, existing agents included; saving it
takes effect in this process at once and in every other within
``floor.TTL_SECONDS``. Members see only which controls the floor claims, from
``GET /api/guardrails/catalog``. The GET also says what the injection model
costs on this server, from this process's measured speed: nothing here loads,
warms or times the model.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import jsonify, make_response, request
from flask_restx import Resource
from pydantic import ValidationError

from docsgpt import decisions
from docsgpt.api.admin.routes import _actor, admin_ns
from docsgpt.api.user.authz import admin_required
from docsgpt.core.settings import settings
from docsgpt.decisions import features
from docsgpt.guardrails import floor as floor_store
from docsgpt.guardrails.config import GuardrailsConfig
from docsgpt.storage.db.repositories.auth_events import AuthEventsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


def _rounded(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 3)


def injection_model() -> dict:
    """The injection model as the admin pages show it.

    ``predicted_input_s`` is the measured prediction for the check on a user
    message on this machine, ``None`` before the model has been measured.
    ``timeout_s`` is the default stage deadline the chat-time check runs
    within.
    """
    info = decisions.model_info()
    return {
        "enabled": bool(settings.DECISION_INJECTION_ENABLED and decisions.available()),
        "runtime": info.runtime if info else None,
        "predicted_input_s": _rounded(decisions.predict_s(features.shape_of(features.INJECTION_INPUT))),
        "timeout_s": features.budget(features.INJECTION_INPUT),
    }


def validation_error(field: str, err: ValidationError) -> str:
    """The first error of a guardrails config as an admin reads it, e.g. ``floor.controls.0: unknown check 'x'``.

    Args:
        field: The body field that failed.
        err: The validation error.
    """
    errors = err.errors()
    if not errors:
        return f"{field} is invalid"
    first = errors[0]
    location = ".".join(str(part) for part in (field, *first.get("loc", ())) if part != "__root__")
    return f"{location}: {str(first.get('msg', 'invalid')).replace('Value error, ', '')}"


def audit(conn, event: str, changes: dict) -> None:
    """Record an instance setting change under the acting admin, with no target.

    Args:
        conn: Database connection in the writing transaction.
        event: The ``auth_events`` event name.
        changes: ``{field: [before, after]}`` for the fields that changed.
    """
    actor = _actor()
    AuthEventsRepository(conn).insert(
        actor or "unknown",
        event,
        ip=request.remote_addr,
        user_agent=request.headers.get("User-Agent"),
        metadata={"by": actor, "via": "admin_api", "changes": changes},
        actor_id=actor or "unknown",
        target_id=None,
    )


def _settings(conn) -> dict[str, Any]:
    return {
        "floor": floor_store.stored(conn),
        "mcp_description_warnings": floor_store.mcp_description_warnings(conn),
    }


def _body(values: dict) -> dict:
    return {"success": True, **values, "injection_model": injection_model()}


def _bad(message: str):
    return make_response(jsonify({"success": False, "message": message}), 400)


@admin_ns.route("/admin/guardrails")
class AdminGuardrailsResource(Resource):
    @admin_required
    def get(self):
        """The floor every agent follows, whether MCP tool descriptions are scored, and the injection model's cost."""
        with db_readonly() as conn:
            values = _settings(conn)
        return make_response(jsonify(_body(values)), 200)

    @admin_required
    def put(self):
        """Store the body's `floor` (an agent guardrails object, or null for none) and/or `mcp_description_warnings`."""
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not ({"floor", "mcp_description_warnings"} & set(body)):
            return _bad("Send floor, mcp_description_warnings or both")
        floor: Optional[GuardrailsConfig] = None
        if body.get("floor") is not None:
            if not isinstance(body["floor"], dict):
                return _bad("floor must be an object or null")
            try:
                floor = GuardrailsConfig.model_validate(body["floor"])
            except ValidationError as err:
                return _bad(validation_error("floor", err))
        warnings = body.get("mcp_description_warnings")
        if "mcp_description_warnings" in body and not isinstance(warnings, bool):
            return _bad("mcp_description_warnings must be true or false")
        with db_session() as conn:
            before = _settings(conn)
            if "floor" in body:
                floor_store.save(conn, floor)
            if "mcp_description_warnings" in body:
                floor_store.set_mcp_description_warnings(conn, warnings)
            after = _settings(conn)
            changes = {key: [before[key], value] for key, value in after.items() if before[key] != value}
            if changes:
                audit(conn, "guardrails_settings_set", changes)
        floor_store.invalidate()
        logger.info("guardrails_settings_updated", extra={"admin": _actor(), "fields": sorted(changes)})
        return make_response(jsonify(_body(after)), 200)
