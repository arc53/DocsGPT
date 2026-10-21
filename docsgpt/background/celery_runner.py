"""The ``celery`` runner: an explicit ``background=true`` call run entirely in a worker.

The turn writes the job and queues it; the worker rebuilds the caller's
``ToolExecutor`` (same user, agent, caller rules and connections), resolves
the tool by its row id, runs the call and finishes the job. The call was
already approved, if it needed approval, before it got here.

At most once: the task is never retried or redelivered, because a tool call
may have side effects. A worker that dies mid-call leaves the job's heartbeat
to go stale, and the sweep reports it lost with the verify-before-retrying
note.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from docsgpt.background import jobs, pool
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)


def worker_payload(executor: Any, tool_data: Dict[str, Any], action_name: str, arguments: Any) -> Dict[str, Any]:
    """What a worker needs to rebuild a call: the caller's identity and the call itself.

    The agent API key travels in the task message only, never on the job row.

    Args:
        executor: The turn's ``ToolExecutor``.
        tool_data: The tool row being called.
        action_name: The action.
        arguments: The model's arguments, without ``background`` / ``watch``.

    Returns:
        A JSON-safe dict.
    """
    return {
        "user": executor.user,
        "user_api_key": executor.user_api_key,
        "agent_id": str(executor.agent_id) if executor.agent_id else None,
        "external_caller": bool(executor.external_caller),
        "public_link_caller": bool(executor.public_link_caller),
        "api_write_allowlist": sorted(executor.api_write_allowlist or []),
        "conversation_id": executor.conversation_id,
        "message_id": executor.message_id,
        "tool_row_id": str(tool_data.get("id")) if tool_data.get("id") else None,
        "tool_name": tool_data.get("name"),
        "action_name": action_name,
        "arguments": arguments if isinstance(arguments, dict) else {},
    }


def enqueue(job_id: str, payload: Dict[str, Any]) -> bool:
    """Queue a job for a worker; on failure the job is failed quietly and the call runs in this process.

    Returns:
        True when queued.
    """
    try:
        from docsgpt.api.user.tasks import run_background_tool_call

        run_background_tool_call.apply_async(args=[job_id, payload])
        return True
    except Exception as exc:
        logger.exception("background job %s: queueing it failed; the call runs in this process instead", job_id)
        jobs.finalize(
            job_id,
            status="failed",
            error={"type": type(exc).__name__, "message": "the job could not be queued"},
            deliver=False,
        )
        with db_session() as conn:
            BackgroundJobsRepository(conn).claim_delivery(job_id, "suppressed")
        return False


def _resolve_tool(executor: Any, payload: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Find the called tool among the caller's tools by row id (user tools are keyed by position)."""
    row_id = payload.get("tool_row_id")
    for key, tool_data in executor.get_tools().items():
        if row_id and str(tool_data.get("id")) == row_id:
            return key, tool_data
    return None


def run_job(job_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run a queued background call in this worker and finish its job.

    Args:
        job_id: The job.
        payload: From :func:`worker_payload`.

    Returns:
        A summary for the task result.
    """
    from celery.exceptions import SoftTimeLimitExceeded

    from docsgpt.agents.tool_executor import ToolExecutor, api_tool_action_with_secrets
    from docsgpt.agents.tool_pins import resolve_arguments

    with db_readonly() as conn:
        row = BackgroundJobsRepository(conn).get(job_id)
    if row is None or row.get("status") != "working":
        return {"state": "gone"}
    if row.get("cancel_requested_at"):
        jobs.finalize(job_id, status="cancelled", status_message="cancelled before it started")
        return {"state": "cancelled"}
    with db_session() as conn:
        if not BackgroundJobsRepository(conn).set_runner(job_id, runner="celery", lease_owner=pool.lease_owner()):
            return {"state": "gone"}
    pool.hold(job_id)

    action_name = payload.get("action_name") or row.get("action_name")
    tool = None
    parameters: Dict[str, Any] = {}
    try:
        executor = ToolExecutor(
            user_api_key=payload.get("user_api_key"),
            user=payload.get("user"),
            decoded_token={"sub": payload.get("user")},
            agent_id=payload.get("agent_id"),
            external_caller=bool(payload.get("external_caller")),
            public_link_caller=bool(payload.get("public_link_caller")),
            api_write_allowlist=payload.get("api_write_allowlist") or [],
        )
        executor.conversation_id = payload.get("conversation_id")
        executor.message_id = payload.get("message_id")
        found = _resolve_tool(executor, payload)
        if found is None:
            raise LookupError(f"the tool {payload.get('tool_name')!r} is no longer available")
        tool_key, tool_data = found
        if tool_data["name"] == "api_tool":
            action_data = api_tool_action_with_secrets(tool_data, action_name, executor.user)
        else:
            action_data = next(a for a in tool_data["actions"] if a["name"] == action_name)
        sections = resolve_arguments(
            action_data, payload.get("arguments") or {}, executor._connection_parameters(tool_data)
        )
        parameters = sections["parameters"]
        tool = executor._get_or_load_tool(
            tool_data,
            tool_key,
            action_name,
            headers=sections["headers"],
            query_params=sections["query_params"],
        )
        if tool is None:
            raise LookupError(f"the tool {payload.get('tool_name')!r} could not be loaded")
        kwargs = sections["body"] if tool_data["name"] == "api_tool" else parameters
        value = tool.execute_action(action_name, **kwargs)
    except SoftTimeLimitExceeded:
        jobs.finalize(
            job_id,
            status="failed",
            error={"type": "TimeoutError", "message": "The job ran past its time limit and was stopped."},
        )
        return {"state": "timeout"}
    except Exception as exc:
        logger.exception("background job %s: the call failed in the worker", job_id)
        jobs.complete_from_tool(job_id, tool=tool, action_name=action_name, parameters=parameters, error=exc)
        return {"state": "failed"}
    done = jobs.complete_from_tool(job_id, tool=tool, action_name=action_name, parameters=parameters, value=value)
    return {"state": "finished", "status": (done or {}).get("status")}
