"""Background jobs REST API: what the chat's job card reads, and its Cancel button.

Every route is scoped to the caller's own jobs, and only while the caller can
still see the job's chat or workflow run: a job in a team's chat reads as gone
to someone who left that team, as the chat does. Results are bounded previews;
the model reads full results through ``check_job`` or a continuation turn.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.api.user.workflow_runs.access import visible_run
from docsgpt.background.results import final_view
from docsgpt.background.service import cancel_job, job_summary
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

background_jobs_ns = Namespace("background_jobs", description="Background jobs of tool calls", path="/api")

#: Characters of a finished job's result a preview shows.
RESULT_PREVIEW_CHARS = 2_000

#: Jobs one listing returns.
LIST_LIMIT = 50


def _user_id() -> Optional[str]:
    decoded = getattr(request, "decoded_token", None)
    return decoded.get("sub") if isinstance(decoded, dict) else None


def _err(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _chat_visible(conn, conversation_id: str, user_id: str) -> bool:
    """Whether the caller can still see the chat (a team chat needs their membership)."""
    return ConversationsRepository(conn).get(str(conversation_id), user_id) is not None


def _visible_job(conn, job_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """The caller's job while its chat or workflow run is still theirs to see, else None.

    Args:
        conn: A database connection.
        job_id: The job's id.
        user_id: The caller.

    Returns:
        The job row, or None when it is missing, someone else's, or its chat or
        run is out of the caller's reach (they left the team it belongs to).
    """
    row = BackgroundJobsRepository(conn).get(job_id, user_id=user_id)
    if row is None:
        return None
    if row.get("conversation_id"):
        return row if _chat_visible(conn, row["conversation_id"], user_id) else None
    if row.get("workflow_run_id"):
        return row if visible_run(conn, str(row["workflow_run_id"]), user_id, None) is not None else None
    return row


def _detail(job: Dict[str, Any]) -> Dict[str, Any]:
    out = job_summary(job)
    if job.get("status") != "working":
        view = final_view(job, max_chars=RESULT_PREVIEW_CHARS)
        for key in ("result", "error", "artifacts", "note"):
            if view.get(key):
                out[key] = view[key]
    return out


@background_jobs_ns.route("/background_jobs")
class BackgroundJobs(Resource):
    @api.doc(
        description="List the caller's background jobs of one conversation, newest first (no result bodies).",
        params={"conversation_id": {"description": "The conversation whose jobs to list.", "required": True}},
    )
    def get(self):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        conversation_id = request.args.get("conversation_id", "")
        if not looks_like_uuid(conversation_id):
            return _err("conversation_id is required", 400)
        try:
            with db_readonly() as conn:
                if not _chat_visible(conn, conversation_id, user_id):
                    rows = None
                else:
                    rows = BackgroundJobsRepository(conn).list_for_conversation(
                        conversation_id, user_id, limit=LIST_LIMIT
                    )
        except Exception:
            logger.exception("listing background jobs failed")
            return _err("Failed to list background jobs", 500)
        if rows is None:
            return _err("Conversation not found", 404)
        return make_response(jsonify({"jobs": [job_summary(row) for row in rows]}), 200)


@background_jobs_ns.route("/background_jobs/<string:job_id>")
class BackgroundJob(Resource):
    @api.doc(description="One background job: its state, progress and, once finished, a result preview.")
    def get(self, job_id: str):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        try:
            with db_readonly() as conn:
                row = _visible_job(conn, job_id, user_id)
        except Exception:
            logger.exception("reading a background job failed")
            return _err("Failed to read the background job", 500)
        if row is None:
            return _err("Job not found", 404)
        return make_response(jsonify(_detail(row)), 200)


@background_jobs_ns.route("/background_jobs/<string:job_id>/cancel")
class CancelBackgroundJob(Resource):
    @api.doc(
        description=(
            "Ask a running background job to stop. It ends as cancelled once its work really stops; a step "
            "already under way may still complete."
        )
    )
    def post(self, job_id: str):
        user_id = _user_id()
        if not user_id:
            return _err("Unauthorized", 401)
        try:
            with db_readonly() as conn:
                visible = _visible_job(conn, job_id, user_id) is not None
            row = cancel_job(job_id, user_id) if visible else None
        except Exception:
            logger.exception("cancelling a background job failed")
            return _err("Failed to cancel the background job", 500)
        if row is None:
            return _err("Job not found", 404)
        return make_response(jsonify(_detail(row)), 200)
