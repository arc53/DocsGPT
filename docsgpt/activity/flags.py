"""Short-lived Redis state for work that has no row of its own while it runs.

Two kinds live here:

- **Stop requests** for a chat answer. A stream only ends when its HTTP
  connection closes, so a Stop from another page sets a flag the stream's
  heartbeat thread polls; the stream then ends as a client abort would,
  saving what it has.
- **Webhook run markers.** A webhook run is a Celery task with no database row
  until it finishes, so the worker marks it here for the Now page.

Every helper is best-effort: without Redis, a stop request reports failure and
markers are simply not listed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from docsgpt.cache import get_redis_instance

logger = logging.getLogger(__name__)

#: How long a stop request waits for its stream to see it.
STOP_TTL_SECONDS = 15 * 60

#: Key prefix of a chat answer's stop request.
_STOP_PREFIX = "activity:stop:"
#: Hash of a user's in-flight webhook runs: field = run id, value = JSON.
_RUNS_PREFIX = "activity:runs:"


def request_stop(message_id: str) -> bool:
    """Ask the stream writing ``message_id`` to stop.

    Args:
        message_id: The message row the stream is writing.

    Returns:
        True when the request was stored.
    """
    redis = get_redis_instance()
    if redis is None:
        return False
    try:
        redis.set(f"{_STOP_PREFIX}{message_id}", "1", ex=STOP_TTL_SECONDS)
        return True
    except Exception:
        logger.exception("activity: storing a stop request failed for %s", message_id)
        return False


def stop_requested(message_id: str) -> bool:
    """Whether someone asked the stream writing ``message_id`` to stop.

    Args:
        message_id: The message row the stream is writing.

    Returns:
        True when a stop request is waiting. False when Redis is unreachable.
    """
    redis = get_redis_instance()
    if redis is None:
        return False
    try:
        return bool(redis.exists(f"{_STOP_PREFIX}{message_id}"))
    except Exception:
        return False


def clear_stop(message_id: str) -> None:
    """Drop a stop request once its stream has ended.

    Args:
        message_id: The message row the stream was writing.
    """
    redis = get_redis_instance()
    if redis is None:
        return
    try:
        redis.delete(f"{_STOP_PREFIX}{message_id}")
    except Exception:
        pass


def mark_run_started(user_id: str, run_id: str, info: Dict[str, Any], *, ttl_seconds: int) -> None:
    """Record an in-flight run that has no database row yet.

    Args:
        user_id: The run's owner.
        run_id: A unique id (the Celery task id).
        info: What the Now page shows (``kind``, ``agent_id``, ``agent_name``).
        ttl_seconds: The longest the run can last; a marker older than this is
            ignored even if the worker died before clearing it.
    """
    redis = get_redis_instance()
    if redis is None or not user_id or not run_id:
        return
    now = time.time()
    value = {**info, "id": run_id, "started_at": now, "expires_at": now + ttl_seconds}
    key = f"{_RUNS_PREFIX}{user_id}"
    try:
        redis.hset(key, run_id, json.dumps(value))
        redis.expire(key, ttl_seconds)
    except Exception:
        logger.exception("activity: marking run %s failed", run_id)


def mark_run_finished(user_id: str, run_id: str) -> None:
    """Remove an in-flight run marker.

    Args:
        user_id: The run's owner.
        run_id: The id given to ``mark_run_started``.
    """
    redis = get_redis_instance()
    if redis is None or not user_id or not run_id:
        return
    try:
        redis.hdel(f"{_RUNS_PREFIX}{user_id}", run_id)
    except Exception:
        logger.exception("activity: clearing run %s failed", run_id)


def list_runs(user_id: str, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """The user's in-flight runs that have not outlived their ceiling.

    Args:
        user_id: The owner.
        now: The current UNIX time (tests).

    Returns:
        Marker dicts, oldest first.
    """
    redis = get_redis_instance()
    if redis is None or not user_id:
        return []
    current = time.time() if now is None else now
    try:
        raw = redis.hgetall(f"{_RUNS_PREFIX}{user_id}") or {}
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for value in raw.values():
        try:
            item = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict) and float(item.get("expires_at") or 0) > current:
            out.append(item)
    return sorted(out, key=lambda item: item.get("started_at") or 0)
