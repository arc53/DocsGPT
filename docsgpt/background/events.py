"""SSE events for background jobs (``job.updated``) and continuation turns (``conversation.continued``)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from docsgpt.background.results import job_notices
from docsgpt.events.publisher import publish_user_event

logger = logging.getLogger(__name__)

JOB_UPDATED = "job.updated"
CONVERSATION_CONTINUED = "conversation.continued"


def publish_job_updated(job: Dict[str, Any]) -> None:
    """Tell the user's open tabs a job changed: ``{job_id, conversation_id, status, progress, tool_name, ...}``.

    Best-effort; a publish failure is logged and never raised.

    Args:
        job: The ``background_jobs`` row after the change.
    """
    user_id = job.get("user_id")
    if not user_id:
        return
    conversation_id = job.get("conversation_id")
    payload = {
        "job_id": str(job.get("id")),
        "conversation_id": str(conversation_id) if conversation_id else None,
        "status": job.get("status"),
        "progress": job.get("progress") or {},
        "tool_name": job.get("tool_name"),
        "action_name": job.get("action_name"),
        "status_message": job.get("status_message"),
        "notices": job_notices(job),
    }
    scope = {"kind": "conversation", "id": str(conversation_id)} if conversation_id else {"kind": "job"}
    try:
        publish_user_event(str(user_id), JOB_UPDATED, payload, scope=scope)
    except Exception:
        logger.exception("job.updated publish failed for job %s", job.get("id"))


def publish_conversation_continued(
    user_id: str, conversation_id: str, message_id: Optional[str], source: str
) -> None:
    """Tell the user's open tabs a continuation turn added a message: ``{conversation_id, message_id, source}``."""
    try:
        publish_user_event(
            str(user_id),
            CONVERSATION_CONTINUED,
            {
                "conversation_id": str(conversation_id),
                "message_id": str(message_id) if message_id else None,
                "source": source,
            },
            scope={"kind": "conversation", "id": str(conversation_id)},
        )
    except Exception:
        logger.exception("conversation.continued publish failed for %s", conversation_id)
