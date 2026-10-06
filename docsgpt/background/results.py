"""What a model is told about a background job: the running hand-off result and the final view.

Every string a model sees about a job is built here, so the wording stays in
one place and the shapes stay stable across ``check_job``, continuation turns
and the user's next message.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: Characters of a final result kept on the job row (head and tail).
STORED_RESULT_MAX_CHARS = 64_000

#: Characters of output kept as a running job's ``output_tail``.
OUTPUT_TAIL_MAX_CHARS = 2_000

LOST_NOTE = (
    "This job was interrupted before it finished and will not report back. It may or may not have taken "
    "effect: verify before retrying, and never re-run a non-idempotent action blindly."
)


def head_tail(text: Any, limit: int) -> str:
    """Bound ``text`` to ``limit`` characters, keeping its head and tail.

    Args:
        text: Any value; non-strings are converted with ``str``.
        limit: The longest string returned.

    Returns:
        ``text`` unchanged when it fits, else its head, a marker and its tail.
    """
    value = text if isinstance(text, str) else str(text)
    if len(value) <= limit:
        return value
    marker = f"\n[... {len(value) - limit} characters omitted ...]\n"
    keep = max(limit - len(marker), 0)
    head = keep * 2 // 3
    tail = keep - head
    return value[:head] + marker + (value[-tail:] if tail else "")


def tail_of(text: Optional[str], limit: int = OUTPUT_TAIL_MAX_CHARS) -> str:
    """The last ``limit`` characters of ``text`` ("" for None)."""
    if not text:
        return ""
    return text if len(text) <= limit else text[-limit:]


def model_status(status: Optional[str]) -> str:
    """A job status as models see it: ``lost`` reads as ``failed`` (MCP Tasks names)."""
    return "failed" if status == "lost" else str(status or "working")


def running_note(job_id: str, auto_resume: bool) -> str:
    """The instruction that comes with a handed-off call's ``running`` result."""
    if auto_resume:
        return (
            f"Still running as background job {job_id}; you are resumed automatically with its result when it "
            "finishes. Do NOT run it again or wait on it with check_job. If nothing else needs doing, tell the user "
            "in plain words that it is running and that you'll follow up here, then end your turn; leave out the "
            "job id and how you are resumed. Never guess the result."
        )
    return (
        f"Still running as background job {job_id}. Do NOT run it again. This conversation is not resumed "
        "automatically: check on it with check_job when the result is needed, or tell the user it is running "
        "and that they can ask for the result later (leave out the job id). Never guess the result."
    )


def running_payload(
    job_id: str,
    *,
    auto_resume: bool,
    elapsed_s: float,
    output_tail: Optional[str] = None,
) -> Dict[str, Any]:
    """The tool result a turn gets for a call that became a background job.

    Args:
        job_id: The job.
        auto_resume: Whether the finished job resumes the conversation.
        elapsed_s: Seconds the call had run when it was handed off.
        output_tail: Output seen so far, if the tool exposes any.

    Returns:
        ``{status: "running", job_id, started_as, elapsed_s, output_tail?, note}``.
    """
    payload: Dict[str, Any] = {
        "status": "running",
        "job_id": str(job_id),
        "started_as": "background",
        "elapsed_s": int(elapsed_s),
    }
    if output_tail:
        payload["output_tail"] = tail_of(output_tail)
    payload["note"] = running_note(str(job_id), auto_resume)
    return payload


def stored_result(text: str, *, status: str, artifacts: Optional[list] = None, artifact_id: Optional[str] = None):
    """The ``result`` a finished job keeps: bounded text plus the files the call produced."""
    out: Dict[str, Any] = {"text": head_tail(text, STORED_RESULT_MAX_CHARS), "status": status}
    if artifact_id:
        out["artifact_id"] = artifact_id
    if artifacts:
        out["artifacts"] = artifacts
    return out


def final_view(job: Dict[str, Any], *, max_chars: int) -> Dict[str, Any]:
    """A finished job as a model reads it: status, result or error, bounded.

    Args:
        job: The ``background_jobs`` row.
        max_chars: Longest result text included (head and tail kept).

    Returns:
        ``{job_id, tool, status, result?, error?, artifacts?, note?}``.
    """
    status = job.get("status")
    view: Dict[str, Any] = {
        "job_id": str(job.get("id")),
        "tool": f"{job.get('tool_name')}.{job.get('action_name')}",
        "status": model_status(status),
    }
    result = job.get("result") or {}
    if isinstance(result, dict) and result.get("text") is not None:
        view["result"] = head_tail(result.get("text") or "", max_chars)
    if isinstance(result, dict) and result.get("artifacts"):
        view["artifacts"] = result["artifacts"]
    error = job.get("error") or {}
    if isinstance(error, dict) and error.get("message"):
        view["error"] = head_tail(str(error["message"]), 2_000)
    if status == "lost":
        view["note"] = LOST_NOTE
    elif status == "cancelled":
        view["note"] = "This job was cancelled."
    return view
