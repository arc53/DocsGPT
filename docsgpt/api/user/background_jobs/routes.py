"""Background jobs REST API: what the chat's job card reads, and its Cancel button.

Every route is scoped to the caller's own jobs. Results are bounded previews;
the model reads full results through ``check_job`` or a continuation turn.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.api import api
from docsgpt.background.results import final_view
from docsgpt.background.service import cancel_job, job_summary
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
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
                rows = BackgroundJobsRepository(conn).list_for_conversation(
                    conversation_id, user_id, limit=LIST_LIMIT
                )
        except Exception:
            logger.exception("listing background jobs failed")
            return _err("Failed to list background jobs", 500)
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
                row = BackgroundJobsRepository(conn).get(job_id, user_id=user_id)
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
            row = cancel_job(job_id, user_id)
        except Exception:
            logger.exception("cancelling a background job failed")
            return _err("Failed to cancel the background job", 500)
        if row is None:
            return _err("Job not found", 404)
        return make_response(jsonify(_detail(row)), 200)
