"""check_job: look at, wait briefly for, or cancel this conversation's background jobs.

A synthetic tool (no ``user_tools`` row), added to every turn that can hand
calls off (``add_check_job_tool``). It only ever sees the jobs of its own
conversation. A ``get`` that finds a job finished takes its result, which
stops the job from also resuming the conversation later.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from docsgpt.agents.tools.base import Tool
from docsgpt.background.results import final_view, model_status, tail_of
from docsgpt.background.service import cancel_job, claim_for_poll, elapsed_seconds, model_summary
from docsgpt.core.settings import settings
from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
from docsgpt.storage.db.session import db_readonly

CHECK_JOB_TOOL_ID = "check_job"
CHECK_JOB = "check_job"

#: Longest a ``get`` waits for a running job.
MAX_WAIT_SECONDS = 30

#: Polls of an unchanged running job after which the model is told to stop.
POLLS_BEFORE_STOP = 10

#: Jobs a listing shows.
LIST_LIMIT = 10


def add_check_job_tool(tools_dict: Dict[str, Any]) -> bool:
    """Add check_job, whole and switched on, to a turn's tools unless another tool uses its name.

    A ``check_job`` row from the user's or agent's config (an older default
    tool, perhaps with its action switched off) is replaced: the tool is
    attached by the server, so no setting can leave hand-offs without it.

    Args:
        tools_dict: The turn's tools; mutated in place.

    Returns:
        Whether the tool is in ``tools_dict`` now.
    """
    for key in [k for k, t in tools_dict.items() if isinstance(t, dict) and t.get("name") == CHECK_JOB]:
        del tools_dict[key]
    tools = [t for t in tools_dict.values() if isinstance(t, dict)]
    # A client tool or MCP action of the same name keeps it.
    if any(a.get("name") == CHECK_JOB for t in tools for a in t.get("actions") or [] if isinstance(a, dict)):
        return False
    actions = [{**meta, "active": True} for meta in CheckJobTool().get_actions_metadata()]
    tools_dict[CHECK_JOB_TOOL_ID] = {"id": CHECK_JOB_TOOL_ID, "name": "check_job", "actions": actions, "config": {}}
    return True


class CheckJobTool(Tool):
    """Check Job

    Check on, wait for or cancel this conversation's background jobs.
    """

    internal = True

    def __init__(self, config: Optional[Dict[str, Any]] = None, user_id: Optional[str] = None) -> None:
        self.config = config or {}
        self.user_id = user_id
        # Polls of each job this turn, with the progress seen last, to stop a polling loop.
        self._polls: Dict[str, Dict[str, Any]] = {}

    def get_actions_metadata(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": CHECK_JOB,
                "description": (
                    "Check a background job of this conversation: a tool call that ran long returns "
                    "`status: running` with a `job_id`. `get` returns its result once it is finished, or its "
                    "progress while it runs; `cancel` asks it to stop. Without a job_id, lists this "
                    "conversation's jobs. A finished job you don't check resumes you with its result anyway, "
                    "so check only when the result is needed now; never poll in a loop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string", "description": "The job id from the running result."},
                        "action": {
                            "type": "string",
                            "enum": ["get", "cancel"],
                            "description": "get (default) or cancel.",
                        },
                        "wait_seconds": {
                            "type": "integer",
                            "description": f"With get, wait up to this long (max {MAX_WAIT_SECONDS}) for it to "
                            "finish. Default 0; keep it unless the job is about to finish and the user waits on "
                            "it in this turn, and never wait on a job you just started.",
                        },
                    },
                    "required": [],
                    "additionalProperties": False,
                },
            }
        ]

    def get_config_requirements(self) -> Dict[str, Any]:
        return {}

    def execute_action(self, action_name: str, **kwargs: Any) -> Dict[str, Any]:
        if action_name != CHECK_JOB:
            return {"status": "error", "error": f"unknown action: {action_name}"}
        conversation_id = self.config.get("conversation_id")
        if not self.user_id or not conversation_id:
            return {"status": "error", "error": "check_job works only inside a conversation."}
        job_id = str(kwargs.get("job_id") or "").strip()
        action = str(kwargs.get("action") or "get").strip().lower()
        if action not in ("get", "cancel"):
            return {"status": "error", "error": "action must be get or cancel."}
        if not job_id:
            if action == "cancel":
                return {"status": "error", "error": "cancel needs a job_id."}
            return self._list(conversation_id)
        job = self._load(job_id, conversation_id)
        if job is None:
            return {"status": "error", "error": f"No job {job_id} in this conversation."}
        if action == "cancel":
            return self._cancel(job)
        wait = self._wait_seconds(kwargs.get("wait_seconds"))
        if self._started_this_turn(job):
            # Waiting here only holds the turn: the finished job resumes the conversation by itself.
            wait = 0
        return self._get(job, conversation_id, wait)

    def _started_this_turn(self, job: Dict[str, Any]) -> bool:
        """Whether this turn handed the job off and the job resumes the conversation when it ends."""
        message_id = self.config.get("message_id")
        return bool(
            message_id and job.get("auto_resume") and str(job.get("origin_message_id") or "") == str(message_id)
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _wait_seconds(value: Any) -> int:
        try:
            seconds = int(float(value))
        except (TypeError, ValueError):
            return 0
        return max(0, min(seconds, MAX_WAIT_SECONDS))

    def _load(self, job_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
        with db_readonly() as conn:
            return BackgroundJobsRepository(conn).get_in_conversation(job_id, self.user_id, conversation_id)

    def _list(self, conversation_id: str) -> Dict[str, Any]:
        with db_readonly() as conn:
            rows = BackgroundJobsRepository(conn).list_for_conversation(
                conversation_id, self.user_id, limit=LIST_LIMIT
            )
        return {"jobs": [model_summary(row) for row in rows]}

    def _cancel(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if job.get("status") != "working":
            return {
                "job_id": str(job["id"]),
                "status": model_status(job.get("status")),
                "note": "The job had already finished; nothing to cancel.",
            }
        cancel_job(str(job["id"]), self.user_id)
        return {
            "job_id": str(job["id"]),
            "status": "working",
            "cancel_requested": True,
            "note": (
                "Cancellation requested. The job stops as soon as its work allows and then ends as cancelled; "
                "a step already under way may still complete."
            ),
        }

    def _get(self, job: Dict[str, Any], conversation_id: str, wait_seconds: int) -> Dict[str, Any]:
        deadline = time.monotonic() + wait_seconds
        while job.get("status") == "working" and time.monotonic() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
            job = self._load(str(job["id"]), conversation_id) or job
        if job.get("status") != "working":
            return self._finished(job)
        return self._running(job)

    def _finished(self, job: Dict[str, Any]) -> Dict[str, Any]:
        row, claimed = claim_for_poll(str(job["id"]))
        view = final_view(row or job, max_chars=int(settings.AUTO_RESUME_MAX_RESULT_CHARS))
        if not claimed:
            state = (row or job).get("delivery_state")
            view["note"] = (view.get("note", "") + " " if view.get("note") else "") + (
                f"This result was already delivered ({state}); don't report it again unless asked."
            )
        return view

    def _running(self, job: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(job["id"])
        progress = job.get("progress") or {}
        signature = (str(progress), job.get("output_tail"))
        seen = self._polls.setdefault(job_id, {"count": 0, "signature": None})
        if seen["signature"] == signature:
            seen["count"] += 1
        else:
            seen["count"], seen["signature"] = 1, signature
        auto_resume = bool(job.get("auto_resume"))
        if self._started_this_turn(job):
            note = (
                "Still running; it was started in this turn, and you are resumed with its result when it "
                "finishes. Tell the user in plain words that it is running and end your turn unless other work "
                "remains."
            )
        elif seen["count"] >= POLLS_BEFORE_STOP:
            note = "Stop polling. End your turn" + (
                "; you will be resumed when it finishes." if auto_resume else " and check again later."
            )
        elif auto_resume:
            note = (
                "Still running; this is not an error. You will be resumed with the result when it finishes, so "
                "don't wait on it again: tell the user it is running and end your turn unless other work remains."
            )
        else:
            note = (
                "Still running; this is not an error. This conversation is not resumed automatically: check "
                "again later, or tell the user it is running."
            )
        out: Dict[str, Any] = {"job_id": job_id, "status": "running", "elapsed_s": elapsed_seconds(job)}
        if not auto_resume:
            # Only a poll-only job needs telling when to look again; otherwise the hint invites polling.
            out["retry_after_s"] = 30
        out["note"] = note
        if progress:
            out["progress"] = progress
        if job.get("output_tail"):
            out["output_tail"] = tail_of(job["output_tail"])
        if job.get("cancel_requested_at"):
            out["cancel_requested"] = True
        if progress.get("waiting_for") == "device":
            out["waiting_for"] = "device"
            out["note"] = (
                "Its device is offline; the command may still be running there, and the job picks up again when "
                "the device reconnects. " + note
            )
        return out
