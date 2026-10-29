"""Workflow runs: list them and read one run's steps, final state and files.

A run is read by the person who started it, with a session or a personal
access token holding ``runs:read``; the files themselves download through
``download.py`` (``artifacts:read``). The id to ask for is the
``workflow_run_id`` a chat stream sends first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import current_app, jsonify, make_response, request
from flask_restx import Namespace, Resource

from docsgpt.agents.workflows.schemas import ExecutionStatus
from docsgpt.api import api
from docsgpt.api.pat.rules import allowed_ids
from docsgpt.api.user.utils import get_user_id
from docsgpt.api.user.workflow_runs.access import run_agent_id, visible_run
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.artifacts import ArtifactsRepository
from docsgpt.storage.db.repositories.workflow_runs import WorkflowRunsRepository
from docsgpt.storage.db.session import db_readonly

workflow_runs_ns = Namespace("workflow_runs", description="Workflow run results", path="/api")

# A state value larger than this (as JSON) is left out of ``state`` and named
# in ``state_truncated``; ``?state_key=`` returns it whole.
STATE_VALUE_MAX_BYTES = 32 * 1024

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_INCLUDES = frozenset({"steps", "state", "artifacts"})
_STATUSES = frozenset(status.value for status in ExecutionStatus)
_STEP_FIELDS = ("node_id", "node_type", "status", "started_at", "completed_at", "duration_ms", "error", "tool_calls")
_ITEM_FIELDS = ("item_index", "status", "started_at", "completed_at", "duration_ms", "error")


def _error(message: str, status: int):
    return make_response(jsonify({"success": False, "message": message}), status)


def _parse_time(value: str) -> Optional[datetime]:
    """An ISO 8601 timestamp as an aware datetime (naive means UTC); None when unparseable."""
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _duration_ms(run: dict) -> Optional[int]:
    started = _parse_time(run.get("started_at")) if run.get("started_at") else None
    ended = _parse_time(run.get("ended_at")) if run.get("ended_at") else None
    if started is None or ended is None:
        return None
    return int((ended - started).total_seconds() * 1000)


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _run_error(run: dict) -> Optional[str]:
    """Why a failed run failed: its first failed step's error, else the reaper's note."""
    if run.get("status") != ExecutionStatus.FAILED.value:
        return None
    for step in run.get("steps") or []:
        if isinstance(step, dict) and step.get("status") == ExecutionStatus.FAILED.value and step.get("error"):
            return str(step["error"])
    result = run.get("result")
    if isinstance(result, dict) and result.get("failed_reason") and result.get("error"):
        return str(result["error"])
    return None


def _summary(run: dict) -> Dict[str, Any]:
    """A run's identity and timing, as the list and the detail share it."""
    inputs = run.get("inputs") if isinstance(run.get("inputs"), dict) else {}
    out: Dict[str, Any] = {
        "id": str(run.get("id")),
        "workflow_id": str(run["workflow_id"]) if run.get("workflow_id") else None,
        "agent_id": run_agent_id(run),
        "status": run.get("status"),
        "query": inputs.get("query"),
        "started_by": inputs.get("started_by"),
        "started_at": _iso(run.get("started_at")),
        "ended_at": _iso(run.get("ended_at")),
        "duration_ms": _duration_ms(run),
        "progress": run.get("progress"),
    }
    if "step_count" in run:
        out["step_count"] = run.get("step_count")
    return out


def _step(step: dict) -> Dict[str, Any]:
    """A step log entry without its state delta (the final state is served on its own)."""
    out = {field: step.get(field) for field in _STEP_FIELDS}
    items = step.get("items")
    if isinstance(items, list) and items:
        out["items"] = [_item(item) for item in items if isinstance(item, dict)]
    return out


def _item(item: dict) -> Dict[str, Any]:
    out = {field: item.get(field) for field in _ITEM_FIELDS}
    out["steps"] = [_step(step) for step in item.get("steps") or [] if isinstance(step, dict)]
    return out


def _json_size(value: Any) -> int:
    return len(json.dumps(value, default=str).encode("utf-8"))


def _capped_state(state: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The final state with every value over ``STATE_VALUE_MAX_BYTES`` left out and listed."""
    kept: Dict[str, Any] = {}
    truncated: List[Dict[str, Any]] = []
    for key, value in state.items():
        size = _json_size(value)
        if size > STATE_VALUE_MAX_BYTES:
            truncated.append({"key": key, "bytes": size})
        else:
            kept[key] = value
    return kept, truncated


def _artifact(run_id: str, row: dict) -> Dict[str, Any]:
    artifact_id = str(row.get("id"))
    return {
        "id": artifact_id,
        "kind": row.get("kind"),
        "title": row.get("title"),
        "filename": row.get("current_filename"),
        "mime_type": row.get("current_mime_type"),
        "current_version": row.get("current_version"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "download_url": f"/api/workflow_runs/{run_id}/artifacts/{artifact_id}/download",
    }


def _agent_allowlist() -> Optional[set]:
    """A personal access token's agent allowlist; None for sessions and unrestricted tokens."""
    return allowed_ids(request, "agents")


@workflow_runs_ns.route("/workflow_runs")
class WorkflowRunList(Resource):
    @api.doc(
        description="List the workflow runs you started, newest first",
        params={
            "agent_id": "Only runs of this agent",
            "since": "Only runs started at or after this ISO 8601 moment",
            "status": "Only runs in this status: pending, running, completed or failed",
            "limit": f"Most runs to return, 1 to {_MAX_LIMIT} (default {_DEFAULT_LIMIT})",
        },
    )
    def get(self):
        user_id = get_user_id()
        if not user_id:
            return _error("Authentication required", 401)
        args = request.args
        agent_id = args.get("agent_id") or None
        if agent_id is not None and not looks_like_uuid(agent_id):
            return _error("Invalid agent_id", 400)
        status = args.get("status") or None
        if status is not None and status not in _STATUSES:
            return _error(f"status must be one of: {', '.join(sorted(_STATUSES))}", 400)
        since = None
        if args.get("since"):
            since = _parse_time(args["since"])
            if since is None:
                return _error("since must be an ISO 8601 timestamp", 400)
        try:
            limit = int(args.get("limit") or _DEFAULT_LIMIT)
        except ValueError:
            return _error("limit must be a number", 400)
        if not 1 <= limit <= _MAX_LIMIT:
            return _error(f"limit must be between 1 and {_MAX_LIMIT}", 400)
        try:
            with db_readonly() as conn:
                rows = WorkflowRunsRepository(conn).list_for_user(
                    user_id,
                    agent_id=agent_id,
                    agent_ids=_agent_allowlist(),
                    since=since,
                    status=status,
                    limit=limit,
                )
        except Exception as err:
            current_app.logger.error(f"Error listing workflow runs: {err}", exc_info=True)
            return _error("Could not list workflow runs", 500)
        return make_response(jsonify({"success": True, "runs": [_summary(row) for row in rows]}), 200)


@workflow_runs_ns.route("/workflow_runs/<string:run_id>")
class WorkflowRunDetail(Resource):
    @api.doc(
        description=(
            "One workflow run you started: status and timing, plus its steps, final state and produced "
            "files on request"
        ),
        params={
            "include": "Comma-separated extras: steps, state, artifacts",
            "state_key": "Return only this key of the final state, in full",
        },
    )
    def get(self, run_id: str):
        user_id = get_user_id()
        if not user_id:
            return _error("Authentication required", 401)
        include = {part.strip() for part in (request.args.get("include") or "").split(",") if part.strip()}
        unknown = include - _INCLUDES
        if unknown:
            return _error(f"include accepts: {', '.join(sorted(_INCLUDES))}", 400)
        state_key = request.args.get("state_key")
        try:
            with db_readonly() as conn:
                run = visible_run(conn, run_id, user_id, _agent_allowlist())
                if run is None:
                    return _error("Workflow run not found", 404)
                artifacts = (
                    ArtifactsRepository(conn).list_artifacts(workflow_run_id=run_id, include_run_inputs=False)
                    if "artifacts" in include
                    else None
                )
        except Exception as err:
            current_app.logger.error(f"Error reading workflow run: {err}", exc_info=True)
            return _error("Could not read the workflow run", 500)

        payload = _summary(run)
        payload["error"] = _run_error(run)
        if "steps" in include:
            payload["steps"] = [_step(step) for step in run.get("steps") or [] if isinstance(step, dict)]
        state = run.get("result") if isinstance(run.get("result"), dict) else {}
        if state_key is not None:
            if state_key not in state:
                return _error("No such key in the run's state", 404)
            payload["state"] = {state_key: state[state_key]}
        elif "state" in include:
            payload["state"], payload["state_truncated"] = _capped_state(state)
        if artifacts is not None:
            payload["artifacts"] = [_artifact(str(run["id"]), row) for row in artifacts]
        return make_response(jsonify({"success": True, "run": payload}), 200)
