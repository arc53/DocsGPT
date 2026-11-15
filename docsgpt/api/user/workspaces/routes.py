"""``/api/workspaces`` and ``/api/workspace_moves``: where a person works, and moving items between workspaces.

``GET /api/workspaces`` lists Personal and every team the caller is in, with
their role there. A move is planned with ``POST /api/workspace_moves/plan``
and applied with ``POST /api/workspace_moves``, sending back the plan's
fingerprint; the rules live in :mod:`docsgpt.workspaces.move`. Personal access
tokens can't call these routes yet: the token rule table refuses any route it
doesn't list.
"""

from __future__ import annotations

from typing import Optional

from flask import Response, current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource, fields

from docsgpt.api import api
from docsgpt.storage.db.repositories.teams import TeamsRepository
from docsgpt.storage.db.repositories.users import UsersRepository
from docsgpt.storage.db.session import db_readonly, db_session
from docsgpt.workspaces.context import PERSONAL
# The module, not its names: it imports the user API, which imports this module.
from docsgpt.workspaces import move as move_service
from docsgpt.workspaces.principal import principal_id
from docsgpt.workspaces.roles import from_stored_role, role_rank

workspaces_ns = Namespace("workspaces", description="Workspaces and moving items between them", path="/api")

_MOVE_MODEL = api.model(
    "WorkspaceMove",
    {
        "to": fields.Raw(required=True, description='{workspace: "personal" | team id, folder_id?}'),
        "items": fields.Raw(required=True, description="[{type: agent|source|tool|prompt|folder, id}]"),
        "fingerprint": fields.String(description="The plan's fingerprint (apply only)"),
    },
)


def _user() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _unauthorized() -> Response:
    return make_response(jsonify({"success": False, "message": "Unauthorized"}), 401)


def _team_role(row: dict) -> Optional[str]:
    if row.get("is_owner"):
        return "owner"
    roles = [r for r in (from_stored_role(s) for s in row.get("stored_roles") or []) if r]
    return max(roles, key=role_rank) if roles else None


def list_workspaces(conn, user: str) -> list[dict]:
    """Personal, then each team the person is in, by name.

    Args:
        conn: Open connection.
        user: The caller.

    Returns:
        list[dict]: ``{id: "personal", kind, name}`` first, then ``{id, kind: "team", name, slug, role,
        member_count, principal_label}`` per team.
    """
    teams = TeamsRepository(conn).workspaces_for(user)
    labels = UsersRepository(conn).principal_labels(principal_id(t["id"]) for t in teams)
    out = [{"id": PERSONAL, "kind": PERSONAL, "name": "Personal"}]
    for team in teams:
        team_id = str(team["id"])
        out.append({
            "id": team_id,
            "kind": "team",
            "name": team.get("name"),
            "slug": team.get("slug"),
            "role": _team_role(team),
            "member_count": int(team.get("member_count") or 0),
            "principal_label": labels.get(principal_id(team_id)),
        })
    return out


@workspaces_ns.route("/workspaces")
class Workspaces(Resource):
    @api.doc(description="Personal and every team the caller is in, with the caller's role in each")
    def get(self):
        user = _user()
        if not user:
            return _unauthorized()
        with db_readonly() as conn:
            workspaces = list_workspaces(conn, user)
        return make_response(jsonify({"workspaces": workspaces}), 200)


@workspaces_ns.route("/workspace_moves/plan")
class WorkspaceMovePlan(Resource):
    @api.expect(_MOVE_MODEL)
    @api.doc(
        description=(
            "Plan a move to a team (the person who owns the items, Editor or above there) or out of one to the "
            "caller's Personal (an Admin): what comes along, what can't, who gains or loses access, and the "
            "fingerprint to apply it with. Changes nothing."
        )
    )
    def post(self):
        user = _user()
        if not user:
            return _unauthorized()
        try:
            move = move_service.parse_move_request(request.get_json(silent=True))
            with db_readonly() as conn:
                plan = move_service.plan_move(conn, user, move)
        except move_service.MoveError as err:
            return err.response()
        return make_response(jsonify({"success": True, "plan": plan.body}), 200)


@workspaces_ns.route("/workspace_moves")
class WorkspaceMoves(Resource):
    @api.expect(_MOVE_MODEL)
    @api.doc(
        description=(
            "Apply a planned move in one transaction. Answers 409 move_plan_changed with the fresh plan when "
            "the fingerprint no longer matches, 409 move_would_borrow naming the agents with outside access "
            "that would use a moved item (and counting those the caller can't open), 403 move_needs_admin "
            "when a moving agent has outside access and the caller isn't a team Admin, and 409 "
            "credentials_unreadable naming a tool whose saved secret can't be re-sealed."
        )
    )
    def post(self):
        user = _user()
        if not user:
            return _unauthorized()
        plan = None
        try:
            move = move_service.parse_move_request(request.get_json(silent=True))
            with db_session() as conn:
                plan = move_service.apply_move(conn, user, move)
        except move_service.MoveError as err:
            return err.response()
        except Exception as err:
            if plan is not None:
                # The move was written but its commit failed: nothing points at its avatar copies.
                move_service.discard_copied_images(plan)
            current_app.logger.error("Workspace move failed: %s", err, exc_info=True)
            return make_response(
                jsonify({"success": False, "error": "move_failed", "message": "The move failed; nothing changed"}),
                500,
            )
        return make_response(jsonify({"success": True, "moved": plan.body}), 200)
