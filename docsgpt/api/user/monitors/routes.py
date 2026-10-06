"""The Monitors page's routes: list the caller's monitors and pause, resume or cancel one.

Every route is scoped to the caller's own monitors; nobody else's is ever
found (404). Views never carry a monitor's state, token hashes or secrets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.monitors import service
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.monitors import MonitorsRepository
from docsgpt.storage.db.repositories.trigger_links import TriggerLinksRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

monitors_ns = Namespace("monitors", description="The caller's monitors (Settings > Monitors)", path="/api")

#: Monitors one listing returns.
LIST_LIMIT = 200

#: What ``status=live`` keeps.
_LIVE = ("active", "paused")

_ACTIONS = ("pause", "resume", "cancel")
_PAST = {"pause": "paused", "resume": "resumed", "cancel": "cancelled"}


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _err(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _views(conn, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    links = TriggerLinksRepository(conn).list_for_monitors([str(r["id"]) for r in rows])
    return [service.view(row, links_rows=links.get(str(row["id"]), [])) for row in rows]


@monitors_ns.route("/monitors")
class Monitors(Resource):
    @api.doc(
        description=(
            "The caller's monitors, newest first: what each watches, its interval, last check, wakes left, expiry "
            "and links (never tokens or secrets)."
        ),
        params={
            "conversation_id": "Only this conversation's monitors.",
            "status": "live (active and paused) or all (the default).",
        },
    )
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        conversation_id = request.args.get("conversation_id") or None
        if conversation_id and not looks_like_uuid(conversation_id):
            return _err("conversation_id must be a conversation id", 400)
        statuses = _LIVE if request.args.get("status") == "live" else None
        try:
            with db_readonly() as conn:
                rows = MonitorsRepository(conn).list_for_user(
                    user_id, statuses=statuses, conversation_id=conversation_id, limit=LIST_LIMIT
                )
                monitors = _views(conn, rows)
        except Exception:
            logger.exception("listing monitors failed")
            return _err("Failed to list monitors", 500)
        return make_response(jsonify({"monitors": monitors}), 200)


@monitors_ns.route("/monitors/<string:monitor_id>")
class MonitorDetail(Resource):
    @api.doc(description="One of the caller's monitors.")
    def get(self, monitor_id: str):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        with db_readonly() as conn:
            row = MonitorsRepository(conn).get(monitor_id, user_id)
            if row is None:
                return _err("Monitor not found", 404)
            view = _views(conn, [row])[0]
        return make_response(jsonify({"monitor": view}), 200)


@monitors_ns.route("/monitors/<string:monitor_id>/<string:action>")
class MonitorAction(Resource):
    @api.doc(
        description=(
            "Pause, resume or cancel one of the caller's monitors. Cancelling revokes its links and any approval "
            "its source was given; resuming a polled monitor checks it again right away. 409 when the monitor "
            "is not in a state the action applies to."
        ),
        params={"action": "pause, resume or cancel"},
    )
    def post(self, monitor_id: str, action: str):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if action not in _ACTIONS:
            return _err("action must be pause, resume or cancel", 404)
        with db_readonly() as conn:
            if MonitorsRepository(conn).get(monitor_id, user_id) is None:
                return _err("Monitor not found", 404)
        if action == "resume":
            changed = service.resume(monitor_id, user_id)
        else:
            status = "paused" if action == "pause" else "cancelled"
            reason = "paused by the user" if action == "pause" else "cancelled by the user"
            changed = service.end(monitor_id, user_id, status, reason=reason)
        if changed is None:
            return _err(f"This monitor can't be {_PAST[action]} now", 409)
        with db_readonly() as conn:
            view = _views(conn, [changed])[0]
        return make_response(jsonify({"monitor": view}), 200)
