"""Who may poll a Celery task through ``GET /api/task_status``.

Every task published while serving a request records its poller in Redis
under ``task_owner:<task_id>``, kept as long as Celery keeps the result:

- the caller's ``sub`` for a session, PAT or OIDC request;
- an empty string for a request without one (agent webhook, agent
  ``api_key`` upload, ``/v1``). Those integrations poll without a session,
  so the unguessable task id is their only credential.

Tasks published outside a request (by the worker or beat) record nothing
and cannot be polled.
"""

import logging
from typing import Any, Optional

from flask import has_request_context, request

from docsgpt.cache import get_redis_instance

logger = logging.getLogger(__name__)

_KEY_PREFIX = "task_owner:"

# Published on every search with a session; nothing polls it, so skip the write.
_UNPOLLED_TASKS = frozenset({"docsgpt.vectorstore.embeddings_tasks.embed_texts"})


class TaskOwnersUnavailable(Exception):
    """Redis could not be reached to look up a task's owner."""


def record_on_publish(sender: Optional[str] = None, headers: Optional[dict] = None, **_: Any) -> None:
    """Record the requesting user as the poller of a task being published.

    Connected to Celery's ``before_task_publish``. Never raises: a failed
    write leaves the task unpollable rather than failing the dispatch.

    Args:
        sender: The task name.
        headers: The message headers; ``id`` is the task id.
    """
    task_id = (headers or {}).get("id")
    if not task_id or sender in _UNPOLLED_TASKS or not has_request_context():
        return
    decoded_token = getattr(request, "decoded_token", None)
    owner = decoded_token.get("sub") if isinstance(decoded_token, dict) else None
    redis_client = get_redis_instance()
    if redis_client is None:
        logger.warning("No Redis to record the owner of task %s; it cannot be polled", task_id)
        return
    from docsgpt.celeryconfig import result_expires

    try:
        redis_client.set(f"{_KEY_PREFIX}{task_id}", owner or "", ex=result_expires)
    except Exception as err:
        logger.warning("Could not record the owner of task %s: %s", task_id, err)


def get_task_owner(task_id: str) -> Optional[str]:
    """Return who may poll a task.

    Args:
        task_id: The Celery task id.

    Returns:
        The owner's user id, an empty string for a task any holder of the id
        may poll, or None for a task with no record.

    Raises:
        TaskOwnersUnavailable: Redis is not configured or not reachable.
    """
    redis_client = get_redis_instance()
    if redis_client is None:
        raise TaskOwnersUnavailable()
    try:
        raw = redis_client.get(f"{_KEY_PREFIX}{task_id}")
    except Exception as err:
        raise TaskOwnersUnavailable() from err
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else str(raw)
