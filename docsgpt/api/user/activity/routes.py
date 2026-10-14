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
from docsgpt.activity.history import KINDS, STATUSES, list_history
from docsgpt.activity.now import build_now
from docsgpt.activity.planned import WindowError, build_planned, parse_window, parse_zone
from docsgpt.api import api
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

activity_ns = Namespace("activity", description="What runs now and what is planned", path="/api")


def _user_id() -> Optional[str]:
    """The caller's user id from the decoded token, or ``None``."""
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _err(message: str, status: int):
    """A ``{"success": false, "message": ...}`` response with ``status``."""
    return make_response(jsonify({"success": False, "message": message}), status)


@activity_ns.route("/activity/now")
class ActivityNow(Resource):
    @api.doc(
        description=(
            "What runs for the caller now (chat answers, background jobs, scheduled, webhook and "
            "workflow runs, ingests), what waits for them (tool approvals, schedules paused after "
            "failures), what runs in the next 24 hours, and the 24-hour counts."
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


@activity_ns.route("/activity/planned")
class ActivityPlanned(Resource):
    @api.doc(
        description=(
            "The caller's calendar for a window: planned schedule runs (from cron or run_at), past "
            "and in-flight runs with their status, coming knowledge syncs (one event per frequency "
            "each time it fires, kind sync), and monitors as date ranges. The window may span at "
            "most 62 days. A frequent schedule with more events than one schedule may list is "
            "summed up per day in tz: one event per day and routine state, with count and until."
        ),
        params={
            "from": {"description": "Window start, ISO 8601.", "required": True},
            "to": {"description": "Window end (exclusive), ISO 8601.", "required": True},
            "tz": {"description": "The viewer's IANA time zone, which days are split in (default UTC)."},
        },
    )
    def get(self):
        """Return the caller's calendar window.

        Returns:
            A Flask response with ``from``, ``to``, ``events`` (schedule and
            sync events, by ``kind``), ``monitors`` and ``truncated``, or 400
            for a bad window or time zone.
        """
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        try:
            start, end = parse_window(request.args.get("from"), request.args.get("to"))
            tz = parse_zone(request.args.get("tz"))
        except WindowError as exc:
            return _err(str(exc), 400)
        try:
            with db_readonly() as conn:
                window = build_planned(conn, user_id, start, end, tz=tz)
        except Exception:
            logger.exception("activity: building the calendar failed")
            return _err("Failed to load the calendar", 500)
        return make_response(jsonify(window), 200)


def _int_arg(name: str, default: int) -> int:
    """Query parameter ``name`` as an int, ``default`` when absent or not a number."""
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


@activity_ns.route("/activity/history")
class ActivityHistory(Resource):
    @api.doc(
        description=(
            "The caller's finished runs of every kind, newest first: scheduled, webhook and workflow "
            "runs, background jobs, and monitor wakes, with one status vocabulary."
        ),
        params={
            "kind": f"One of {', '.join(KINDS)}; all when left out.",
            "status": f"One of {', '.join(STATUSES)} (failed includes timed out); all when left out.",
            "q": "Text matched against the run, agent and conversation names.",
            "days": "How far back to look (default 30, at most 90).",
            "limit": "Rows per page (default 50, at most 200).",
            "offset": "Rows to skip.",
        },
    )
    def get(self):
        """Return one page of the caller's finished runs.

        Returns:
            A Flask response with ``runs`` and ``has_more``, or 400 for an
            unknown ``kind`` or ``status``.
        """
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        try:
            with db_readonly() as conn:
                page = list_history(
                    conn,
                    user_id,
                    kind=request.args.get("kind") or None,
                    status=request.args.get("status") or None,
                    query=request.args.get("q") or None,
                    days=_int_arg("days", 30),
                    limit=_int_arg("limit", 50),
                    offset=_int_arg("offset", 0),
                )
        except ValueError as exc:
            return _err(str(exc), 400)
        except Exception:
            logger.exception("activity: listing history failed")
            return _err("Failed to load history", 500)
        return make_response(jsonify(page), 200)


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
            message, 409 when it is not running (finished, or paused for a
            tool approval), 503 without Redis.
        """
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        if not looks_like_uuid(message_id):
            return _err("Message not found", 404)
        with db_readonly() as conn:
            row = conn.execute(
                text(
                    "SELECT m.status, EXISTS ("
                    "  SELECT 1 FROM pending_tool_state p"
                    "  WHERE p.conversation_id = m.conversation_id AND p.user_id = m.user_id"
                    "    AND p.status = 'pending'"
                    "    AND p.agent_config ->> 'reserved_message_id' = m.id::text"
                    ") AS paused "
                    "FROM conversation_messages m "
                    "WHERE m.id = CAST(:id AS uuid) AND m.user_id = :user_id"
                ),
                {"id": message_id, "user_id": user_id},
            ).first()
        if row is None:
            return _err("Message not found", 404)
        # A paused answer has no stream to see the request; the flag would
        # outlive it and stop the resumed answer, which reuses the message id.
        if row.status not in ("pending", "streaming") or row.paused:
            return _err("The answer is not running", 409)
        if not request_stop(message_id):
            return _err("Stopping is unavailable right now", 503)
        return make_response(jsonify({"success": True}), 202)
