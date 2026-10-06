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

#: Secret reveals one user may make per minute.
SECRET_REVEALS_PER_MINUTE = 10


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


@monitors_ns.route("/monitors/<string:monitor_id>/secret")
class MonitorSecret(Resource):
    @api.doc(
        description=(
            "The signing secret of one of the caller's webhook monitors, so the owner can configure the sender. "
            "Only the owner's session may read it (never an access token); the model only ever sees its "
            "reference. Rate limited, audited, never cached or logged. 404 when the monitor has no live signed "
            "link, or its secret was never set."
        )
    )
    def get(self, monitor_id: str):
        from docsgpt.monitors.triggers import rate_limited

        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if rate_limited("secret", user_id, SECRET_REVEALS_PER_MINUTE):
            return _err("Too many requests; try again in a minute", 429)
        try:
            revealed = service.reveal_secret(monitor_id, user_id)
        except Exception:
            # Never log the exception text: it could carry the value.
            logger.error("revealing a monitor secret failed (%s)", monitor_id)
            return _err("Failed to read the secret", 500)
        if revealed is None:
            return _err("No signing secret for this monitor", 404)
        response = make_response(jsonify(revealed), 200)
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.doc(
        description=(
            "Set the signing secret of one of the caller's webhook monitors: {secret}. For Stripe and Slack, "
            "which create their own signing secret, this is how the link gets it; for any other signed scheme it "
            "replaces the generated one. Only the owner's session may set it (never an access token). Rate "
            "limited, audited without the value, never logged. 400 for a value that can't be this scheme's "
            "secret, 404 when the monitor has no live signed link."
        )
    )
    def put(self, monitor_id: str):
        from docsgpt.monitors.triggers import rate_limited

        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if rate_limited("secret_set", user_id, SECRET_REVEALS_PER_MINUTE):
            return _err("Too many requests; try again in a minute", 429)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or "secret" not in data:
            return _err("Send {\"secret\": \"...\"}", 400)
        try:
            saved = service.set_secret(monitor_id, user_id, data.get("secret"))
        except ValueError as exc:
            # The message describes the format, never the value.
            return _err(f"That can't be this link's signing secret: {exc}", 400)
        except Exception:
            logger.error("setting a monitor secret failed (%s)", monitor_id)
            return _err("Failed to save the secret", 500)
        if saved is None:
            return _err("No signed link for this monitor", 404)
        response = make_response(jsonify(saved), 200)
        response.headers["Cache-Control"] = "no-store"
        return response


@monitors_ns.route("/monitors/<string:monitor_id>/secret/exposure")
class MonitorSecretExposure(Resource):
    @api.doc(
        description=(
            "Show (or stop showing) one of the caller's webhook monitors' raw signing secret to the assistant: "
            "{exposed: true|false}. Shown, monitor_list gives the assistant the value, which then goes to the model "
            "provider. Only the owner's session may change it (never an access token, never the assistant). Rate "
            "limited and audited. 404 when the monitor has no live signed link with a secret."
        )
    )
    def put(self, monitor_id: str):
        from docsgpt.monitors.triggers import rate_limited

        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if rate_limited("secret_exposure", user_id, SECRET_REVEALS_PER_MINUTE):
            return _err("Too many requests; try again in a minute", 429)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("exposed"), bool):
            return _err("Send {\"exposed\": true} or {\"exposed\": false}", 400)
        try:
            changed = service.set_exposure(monitor_id, user_id, data["exposed"])
        except Exception:
            logger.exception("changing a monitor secret's exposure failed (%s)", monitor_id)
            return _err("Failed to change it", 500)
        if changed is None:
            return _err("No signed link with a secret for this monitor", 404)
        response = make_response(jsonify(changed), 200)
        response.headers["Cache-Control"] = "no-store"
        return response


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
