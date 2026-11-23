"""``GET /api/workflow_runs/{run_id}/artifacts/{artifact_id}/download``: a file a run produced.

A native-async Starlette route mounted ahead of Flask in ``docsgpt/asgi.py``,
like the artifact download it shares its serving with, so a large file
streams from the event loop. The caller must be able to read the run (see
``access.py``); a personal access token needs ``artifacts:read`` and, when
restricted to agents, the run must be one of theirs. A run's input documents
are not served here: they are the caller's own uploads, not what it produced.
"""

from __future__ import annotations

import logging
from typing import Mapping, Optional, Tuple

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from docsgpt.api.asgi_auth import authenticate, bind_log_context, json_error
from docsgpt.api.pat.tokens import is_pat
from docsgpt.api.user.artifacts.download import serve_artifact_version
from docsgpt.api.user.workflow_runs.access import RUN_RESTRICTABLE_FAMILIES, visible_run
from docsgpt.storage.db.base_repository import looks_like_uuid
from docsgpt.storage.db.repositories.artifacts import RUN_INPUT_SOURCE, ArtifactsRepository
from docsgpt.storage.db.session import db_readonly

logger = logging.getLogger(__name__)

# The PAT scope this route needs.
DOWNLOAD_SCOPE = "artifacts:read"


def _load_run_version(
    run_id: str,
    artifact_id: str,
    user_id: str,
    allowed_agents: Optional[list],
    query: Mapping[str, str],
) -> Tuple[Optional[dict], Optional[Tuple[str, int]]]:
    """Authorize the caller and fetch the requested version row; runs in a worker thread.

    Args:
        run_id: The run.
        artifact_id: An artifact the run produced.
        user_id: The caller.
        allowed_agents: The token's agent allowlist, or None when unrestricted.
        query: The request's query params (``version`` picks a version).

    Returns:
        ``(version_row, None)`` or ``(None, (message, status))``.
    """
    with db_readonly() as conn:
        if visible_run(conn, run_id, user_id, allowed_agents) is None:
            return None, ("Workflow run not found", 404)
        repo = ArtifactsRepository(conn)
        artifact = repo.get_artifact_in_parent(artifact_id, workflow_run_id=run_id)
        if artifact is None:
            return None, ("Artifact not found", 404)
        version = artifact.get("current_version")
        version_arg = query.get("version")
        if version_arg is not None:
            try:
                version = int(version_arg)
            except ValueError:
                return None, ("Invalid version", 400)
        version_row = repo.get_version(artifact_id, version)
    if version_row is None:
        return None, ("Version not found", 404)
    produced_by = version_row.get("produced_by")
    if isinstance(produced_by, dict) and produced_by.get("source") == RUN_INPUT_SOURCE:
        return None, ("Artifact not found", 404)
    return version_row, None


async def download_run_artifact(request: Request) -> Response:
    """Serve a file a workflow run produced, as the artifact download does."""
    run_id = request.path_params["run_id"]
    artifact_id = request.path_params["artifact_id"]
    if not looks_like_uuid(run_id) or not looks_like_uuid(artifact_id):
        return json_error("Artifact not found", 404)
    decoded, error = await authenticate(request, pat_scope=DOWNLOAD_SCOPE, restrictable=RUN_RESTRICTABLE_FAMILIES)
    if error is not None:
        return error
    if not decoded or not decoded.get("sub"):
        return json_error("Authentication required", 401)
    user_id = decoded["sub"]
    bind_log_context("workflow_runs_download_artifact", user_id)
    allowed_agents = (decoded.get("resource_filter") or {}).get("agents") if is_pat(decoded) else None
    try:
        version_row, failure = await anyio.to_thread.run_sync(
            _load_run_version, run_id, artifact_id, user_id, allowed_agents, request.query_params
        )
        if failure is not None:
            return json_error(*failure)
        return await serve_artifact_version(request, artifact_id, version_row)
    except FileNotFoundError:
        return json_error("File not found", 404)
    except Exception:
        logger.error("Error downloading artifact %s of run %s", artifact_id, run_id, exc_info=True)
        return JSONResponse({"success": False}, status_code=400)


# Mounted in ``docsgpt/asgi.py`` ahead of the Flask catch-all.
run_artifact_download_routes = [
    Route(
        "/api/workflow_runs/{run_id}/artifacts/{artifact_id}/download",
        download_run_artifact,
        methods=["GET"],
    ),
]
