"""Job lifecycle: create a job at hand-off, and finish it once, from whichever runner gets there.

``finalize`` is the single exit: it writes the final row (once), settles the
``tool_call_attempts`` journal row the turn left ``proposed``, updates the
origin message's tool-call entry so a reload shows the outcome, publishes
``job.updated`` and hands the job to delivery.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from docsgpt.background import pool
from docsgpt.background.context import BackgroundContext
from docsgpt.background.events import publish_job_updated
from docsgpt.background.results import LOST_NOTE, stored_result, tail_of
from docsgpt.core.settings import settings
from docsgpt.storage.db.redaction import redact_secrets
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.repositories.conversations import ConversationsRepository
from docsgpt.storage.db.repositories.tool_call_attempts import ToolCallAttemptsRepository
from docsgpt.storage.db.session import db_readonly, db_session

logger = logging.getLogger(__name__)

#: Longest string argument kept on the job row; a long code body keeps its head.
_ARG_VALUE_MAX_CHARS = 8_000

#: Tools whose jobs are code runs (``kind = code_exec``).
_CODE_TOOLS = frozenset({"code_executor"})


def redact_args(arguments: Any) -> Dict[str, Any]:
    """The call's arguments as stored on the job: secrets redacted, long strings cut.

    Args:
        arguments: The model's arguments.

    Returns:
        A JSON-safe dict.
    """
    if not isinstance(arguments, dict):
        return {}

    def _bound(value: Any) -> Any:
        if isinstance(value, str) and len(value) > _ARG_VALUE_MAX_CHARS:
            return value[:_ARG_VALUE_MAX_CHARS] + f"...[{len(value) - _ARG_VALUE_MAX_CHARS} more characters]"
        if isinstance(value, dict):
            return {k: _bound(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_bound(v) for v in value]
        return value

    return _bound(redact_secrets(arguments))


def job_kind(tool_name: Optional[str]) -> str:
    """``code_exec`` for code runs, ``tool_call`` for everything else."""
    return "code_exec" if tool_name in _CODE_TOOLS else "tool_call"


def create_job(
    context: BackgroundContext,
    *,
    tool_name: str,
    action_name: str,
    journal_key: str,
    arguments: Any,
    runner: str = "inprocess",
    watch: Optional[dict] = None,
    external: Optional[dict] = None,
    output_tail: Optional[str] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Write the job row for a call being handed off, before the turn hears its id.

    Args:
        context: The turn's background context.
        tool_name: The tool's name.
        action_name: The action called.
        journal_key: The call's turn-scoped key (``tool_call_attempts``).
        arguments: The model's arguments (redacted here).
        runner: Who finishes the job.
        watch: The call's ``watch`` spec.
        external: Runner handles.
        output_tail: Output seen so far.

    Returns:
        ``(row, created)``.
    """
    with db_session() as conn:
        row, created = BackgroundJobsRepository(conn).create(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            origin_message_id=context.origin_message_id,
            tool_call_id=journal_key,
            agent_id=context.agent_id,
            tool_name=tool_name,
            action_name=action_name,
            kind=job_kind(tool_name),
            args=redact_args(arguments),
            runner=runner,
            # A celery job takes its lease when a worker starts it.
            lease_owner=pool.lease_owner() if runner == "inprocess" else None,
            auto_resume=context.auto_resume(),
            watch=watch,
            external=external,
            output_tail=tail_of(output_tail) if output_tail else None,
            max_seconds=int(settings.BACKGROUND_JOB_MAX_SECONDS),
        )
    if created:
        publish_job_updated(row)
    return row, created


def within_caps(context: BackgroundContext) -> bool:
    """Whether the conversation and the user may start another background job."""
    conversation_cap = int(settings.BACKGROUND_MAX_JOBS_PER_CONVERSATION)
    user_cap = int(settings.BACKGROUND_MAX_JOBS_PER_USER)
    if conversation_cap <= 0 or user_cap <= 0:
        return False
    with db_readonly() as conn:
        repo = BackgroundJobsRepository(conn)
        if repo.count_working(conversation_id=context.conversation_id) >= conversation_cap:
            return False
        return repo.count_working(user_id=context.user_id) < user_cap


def tool_outputs(tool: Any, action_name: str, parameters: Dict[str, Any]) -> Tuple[Optional[str], List[dict]]:
    """The files a finished call produced, read off the tool as the executor does.

    Args:
        tool: The tool instance that ran the call.
        action_name: The action called.
        parameters: The call's resolved parameters.

    Returns:
        ``(artifact_id, artifacts)``.
    """
    artifact_id: Optional[str] = None
    artifacts: List[dict] = []
    get_artifact_id = getattr(tool, "get_artifact_id", None)
    if callable(get_artifact_id):
        try:
            value = get_artifact_id(action_name, **parameters)
            if value is not None:
                artifact_id = str(value).strip() or None
        except Exception:
            logger.exception("background job: reading artifact_id failed")
    get_artifacts = getattr(tool, "get_artifacts", None)
    if callable(get_artifacts):
        try:
            artifacts = [
                {"id": str(a["id"]).strip(), "filename": a.get("filename"), "ref": a.get("ref")}
                for a in (get_artifacts(action_name, **parameters) or [])
                if isinstance(a, dict) and a.get("id")
            ]
        except Exception:
            logger.exception("background job: reading artifacts failed")
    # Images a tool queued for this turn's model can't reach a later one.
    drain = getattr(tool, "drain_native_parts", None)
    if callable(drain):
        try:
            drain()
        except Exception:
            logger.debug("background job: draining native parts failed", exc_info=True)
    return artifact_id, artifacts


def complete_from_tool(
    job_id: str,
    *,
    tool: Any,
    action_name: str,
    parameters: Dict[str, Any],
    value: Any = None,
    error: Optional[BaseException] = None,
) -> Optional[Dict[str, Any]]:
    """Finish a job from the tool call that ran it: shape the result as the executor would.

    Args:
        job_id: The job.
        tool: The tool instance.
        action_name: The action called.
        parameters: The resolved parameters (artifact lookups take them).
        value: The tool's return value.
        error: The exception the call raised, if it raised.

    Returns:
        The finished row, or None when the job was already final.
    """
    from docsgpt.agents.tool_executor import (
        bound_result_full,
        result_status,
        sanitize_tool_result,
    )

    if error is not None:
        return finalize(
            job_id,
            status="failed",
            error={"type": type(error).__name__, "message": str(error) or type(error).__name__},
        )
    result = sanitize_tool_result(value)
    artifact_id, artifacts = tool_outputs(tool, action_name, parameters)
    text_value = bound_result_full(str(result))
    in_band = result_status(result)
    return finalize(
        job_id,
        status="completed" if in_band == "completed" else "failed",
        result=stored_result(text_value, status=in_band, artifacts=artifacts, artifact_id=artifact_id),
    )


def finalize(
    job_id: str,
    *,
    status: str,
    result: Optional[dict] = None,
    error: Optional[dict] = None,
    output_tail: Optional[str] = None,
    status_message: Optional[str] = None,
    deliver: bool = True,
    stale_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Write a job's final state once, settle its journal row and tool-call entry, and deliver it.

    A job whose cancellation was requested ends ``cancelled`` whatever the
    call returned; its result is kept so check_job can still show it.

    Args:
        job_id: The job.
        status: ``completed``, ``failed``, ``cancelled`` or ``lost``.
        result: The stored result (see ``results.stored_result``).
        error: ``{type, message}`` for a failure.
        output_tail: The last output seen.
        status_message: A short human-readable state.
        deliver: Hand the finished job to delivery (resume the conversation).
        stale_seconds: Finish only if the heartbeat is at least this old.

    Returns:
        The finished row, or None when another path finished it first.
    """
    pool.release(job_id)
    try:
        with db_session() as conn:
            repo = BackgroundJobsRepository(conn)
            current = repo.get(job_id)
            if current is None or current.get("status") != "working":
                return None
            if current.get("cancel_requested_at") and status in ("completed", "failed"):
                status = "cancelled"
            row = repo.finish(
                job_id,
                status=status,
                result=result,
                error=error,
                output_tail=output_tail,
                status_message=status_message,
                retention_days=int(settings.BACKGROUND_RESULT_RETENTION_DAYS),
                stale_seconds=stale_seconds,
            )
            if row is None:
                return None
            _settle_journal(conn, row)
            _patch_origin_entry(conn, row)
    except Exception:
        logger.exception("background job %s: final write failed", job_id)
        return None
    publish_job_updated(row)
    if deliver:
        _deliver(row)
    return row


def _settle_journal(conn: Any, row: Dict[str, Any]) -> None:
    """Close the ``tool_call_attempts`` row the turn left ``proposed`` when it handed the call off.

    The turn has already finalized, so nothing else will confirm it: a call
    that produced a result goes straight to ``confirmed``, one that raised or
    was lost to ``failed``.
    """
    key = row.get("tool_call_id")
    if not key:
        return
    repo = ToolCallAttemptsRepository(conn)
    result = row.get("result") or {}
    user_id = row.get("user_id")
    if row.get("status") in ("completed", "failed", "cancelled") and isinstance(result, dict) and "text" in result:
        repo.mark_executed(
            key, result.get("text"), message_id=None, artifact_id=result.get("artifact_id"), user_id=user_id
        )
        return
    error = row.get("error") or {}
    message = error.get("message") if isinstance(error, dict) else None
    if row.get("status") == "lost":
        message = message or LOST_NOTE
    repo.mark_failed(key, f"background job {row.get('status')}: {message or 'no result'}", user_id=user_id)


def _patch_origin_entry(conn: Any, row: Dict[str, Any]) -> None:
    """Show the outcome on the turn's tool-call entry, so a reload stops showing it as running."""
    message_id = row.get("origin_message_id")
    if not message_id:
        return
    result = row.get("result") or {}
    in_band = result.get("status") if isinstance(result, dict) else None
    patch: Dict[str, Any] = {
        "status": "completed" if row.get("status") == "completed" and in_band != "error" else "error",
        "job_status": row.get("status"),
    }
    if isinstance(result, dict):
        if result.get("artifacts"):
            patch["artifacts"] = result["artifacts"]
        if result.get("artifact_id"):
            patch["artifact_id"] = result["artifact_id"]
    ConversationsRepository(conn).patch_tool_call(str(message_id), str(row["id"]), patch)


def _deliver(row: Dict[str, Any]) -> None:
    """Hand a finished job to delivery; a failure here leaves it for the reconciler's sweep."""
    from docsgpt.background.wake import on_job_finished

    try:
        on_job_finished(row)
    except Exception:
        logger.exception("background job %s: delivery failed; the sweep retries it", row.get("id"))
