"""Activity REST API.

``GET /api/activity/now`` is what the Now page and the sidebar marks read.
``POST /api/messages/<id>/cancel`` stops a chat answer from outside its chat:
a stream otherwise ends only when its connection closes.
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from sqlalchemy import text

from docsgpt.activity.flags import request_stop
from docsgpt.activity.now import build_now
from docsgpt.api import api
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

activity_ns = Namespace("activity", description="What runs now and what is planned", path="/api")


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _err(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


@activity_ns.route("/activity/now")
class ActivityNow(Resource):
    @api.doc(
        description=(
            "What runs for the caller now (chat answers, background jobs, scheduled, webhook and "
            "workflow runs, ingests), what waits for them (tool approvals, schedules paused after "
            "failures), what runs in the next 24 hours, and the counts the sidebar shows."
        ),
    )
    def get(self):
        """Return the caller's Now snapshot.

        Returns:
            A Flask response with ``running``, ``needs_you``, ``up_next``,
            ``approval_conversations``, ``failed_conversations`` and ``stats``.
        """
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        try:
            with db_readonly() as conn:
                snapshot = build_now(conn, user_id)
        except Exception:
            logger.exception("activity: building the Now snapshot failed")
            return _err("Failed to load activity", 500)
        return make_response(jsonify(snapshot), 200)


@activity_ns.route("/messages/<string:message_id>/cancel")
class MessageCancel(Resource):
    @api.doc(
        description=(
            "Stop the caller's chat answer that is still being written. The stream ends as if its "
            "client had disconnected and keeps what it wrote. Answers 202 once the request is stored; "
            "the stream sees it within a few seconds, or when a long tool call returns."
        ),
    )
    def post(self, message_id: str):
        """Ask a running answer to stop.

        Args:
            message_id: The answer's message id.

        Returns:
            202 when the stop was requested, 404 when the caller has no such
            message, 409 when it is not running, 503 without Redis.
        """
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if not looks_like_uuid(message_id):
            return _err("Message not found", 404)
        with db_readonly() as conn:
            status = conn.execute(
                text(
                    "SELECT status FROM conversation_messages "
                    "WHERE id = CAST(:id AS uuid) AND user_id = :user_id"
                ),
                {"id": message_id, "user_id": user_id},
            ).scalar()
        if status is None:
            return _err("Message not found", 404)
        if status not in ("pending", "streaming"):
            return _err("The answer is not running", 409)
        if not request_stop(message_id):
            return _err("Stopping is unavailable right now", 503)
        return make_response(jsonify({"success": True}), 202)
