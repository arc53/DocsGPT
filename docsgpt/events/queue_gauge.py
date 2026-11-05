"""Point-in-time gauge of the Celery queues on the Redis broker.

kombu's Redis transport keeps each queue as one list per priority step
(``ingest``, ``ingest\\x06\\x163``, ...): a publish ``LPUSH``es, a worker
``BRPOP``s the plain list first, so the right end of the first non-empty list
is the next message to run.

Celery messages carry no publish time, so "how long has the head of the queue
waited" is tracked across gauge runs instead: the head's task id and the time
it was first seen there live in ``gauge:queue_head:<queue>``. While the same
task stays at the head, its wait grows by one gauge interval per run; when it
moves, the wait starts again from zero. It is a lower bound with one-interval
resolution, which is enough to see an ingest lane that has stopped draining.

In-flight work is reported by the workers, not read from kombu's ``unacked``
hash: once a task outlives the broker's visibility timeout, kombu restores its
message and drops it from that hash while the task still holds its slot. Each
running task is a member of ``gauge:in_flight:<queue>``, scored by when its
entry expires; a thread in each worker process pushes the expiry forward every
:data:`IN_FLIGHT_RENEW_SECONDS`, so a task whose worker died stops counting
after :data:`IN_FLIGHT_TTL_SECONDS`.

The beat task in ``docsgpt/api/user/tasks.py`` adds the numbers to its
``sse_gauge`` event.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Iterable, Optional

from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

# kombu.transport.redis: Channel.sep and PRIORITY_STEPS.
PRIORITY_SEP = "\x06\x16"
PRIORITY_STEPS = (0, 3, 6, 9)

HEAD_KEY_TTL_SECONDS = 86400

# A running task's entry lives this long past its last renewal; three missed
# renewals before a dead worker's task stops counting.
IN_FLIGHT_TTL_SECONDS = 90
IN_FLIGHT_RENEW_SECONDS = 30

_broker_client = None
_broker_lock = threading.Lock()

# Tasks this process is running: task id -> queue.
_running: dict = {}
_running_lock = threading.Lock()
_renewer_pid: Optional[int] = None
_renewer_lock = threading.Lock()


def head_key(queue: str) -> str:
    """Redis key holding the head-of-line task id for ``queue`` and when it was first seen."""
    return f"gauge:queue_head:{queue}"


def in_flight_key(queue: str) -> str:
    """Redis sorted set of the tasks running from ``queue``, scored by expiry."""
    return f"gauge:in_flight:{queue}"


def broker_redis():
    """Return a Redis client for the Celery broker, or ``None`` if the broker is not Redis.

    The cache client reads ``CACHE_REDIS_URL``, which may be a different
    database, so the gauge opens its own. Short socket timeouts keep a dead
    connection from hanging the beat task.
    """
    global _broker_client
    url = settings.CELERY_BROKER_URL or ""
    if not url.startswith(("redis://", "rediss://")):
        return None
    if _broker_client is None:
        with _broker_lock:
            if _broker_client is None:
                import redis

                _broker_client = redis.Redis.from_url(
                    url,
                    socket_timeout=5,
                    socket_connect_timeout=2,
                    health_check_interval=30,
                )
    return _broker_client


def _queue_keys(queue: str) -> list:
    return [queue if not pri else f"{queue}{PRIORITY_SEP}{pri}" for pri in PRIORITY_STEPS]


def _head_identity(raw) -> str:
    """The task id (and eta) of a queued payload, or a digest of it when it cannot be parsed.

    A task deferred by the per-user ingest cap is published again under its
    own id with a new eta, so the eta tells the new message from the old one.
    """
    try:
        headers = json.loads(raw)["headers"]
        task_id = headers["id"]
        if task_id:
            eta = headers.get("eta")
            return f"{task_id}@{eta}" if eta else str(task_id)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        # Not a kombu JSON envelope; fall back to identifying it by its bytes.
        pass
    data = raw if isinstance(raw, bytes) else str(raw).encode()
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- worker side: running tasks ---------------------------------------------


def task_started(task_id: str, queue: str, now: Optional[float] = None) -> None:
    """Count ``task_id`` as running from ``queue`` until it finishes or stops being renewed."""
    client = broker_redis()
    if client is None or not task_id or not queue:
        return
    with _running_lock:
        _running[task_id] = queue
    _ensure_renewer()
    _write_entries(client, [(task_id, queue)], time.time() if now is None else now)


def task_finished(task_id: str) -> None:
    """Stop counting ``task_id`` as running."""
    with _running_lock:
        queue = _running.pop(task_id, None)
    if queue is None:
        return
    client = broker_redis()
    if client is not None:
        client.zrem(in_flight_key(queue), task_id)


def renew_in_flight(now: Optional[float] = None) -> None:
    """Push the expiry of every task this process is running forward."""
    with _running_lock:
        entries = list(_running.items())
    client = broker_redis()
    if not entries or client is None:
        return
    _write_entries(client, entries, time.time() if now is None else now)


def _write_entries(client, entries: list, now: float) -> None:
    expires_at = now + IN_FLIGHT_TTL_SECONDS
    pipe = client.pipeline(transaction=False)
    for task_id, queue in entries:
        pipe.zadd(in_flight_key(queue), {task_id: expires_at})
        # The set outlives its last renewal by one TTL, so an idle queue leaves no key.
        pipe.expire(in_flight_key(queue), IN_FLIGHT_TTL_SECONDS)
    pipe.execute()


def _ensure_renewer() -> None:
    """Start this process's renewal thread once (again in a forked child)."""
    global _renewer_pid
    pid = os.getpid()
    if _renewer_pid == pid:
        return
    with _renewer_lock:
        if _renewer_pid == pid:
            return
        threading.Thread(target=_renew_loop, name="queue-gauge-in-flight", daemon=True).start()
        _renewer_pid = pid


def _renew_loop() -> None:
    while True:
        time.sleep(IN_FLIGHT_RENEW_SECONDS)
        try:
            renew_in_flight()
        except Exception:
            logger.debug("in-flight renewal failed", exc_info=True)


def _reset_after_fork() -> None:
    """A forked child runs none of its parent's tasks and needs its own locks."""
    global _running_lock, _renewer_lock
    _running.clear()
    _running_lock = threading.Lock()
    _renewer_lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


# --- beat side: the gauge ---------------------------------------------------


def measure_celery_queues(redis_client, queues: Iterable[str], now: Optional[float] = None) -> dict:
    """Measure depth, head-of-line wait and in-flight count for each queue.

    Args:
        redis_client: A ``redis.Redis`` client on the broker database.
        queues: Queue names, as declared in ``celeryconfig.task_queues``.
        now: Current time in seconds; defaults to ``time.time()``.

    Returns:
        ``{queue: {"depth": int, "wait_s": int, "in_flight": int}}``.
    """
    now = time.time() if now is None else now
    queues = list(dict.fromkeys(queues))

    reads = redis_client.pipeline(transaction=False)
    for queue in queues:
        keys = _queue_keys(queue)
        for key in keys:
            reads.llen(key)
        for key in keys:
            reads.lindex(key, -1)
        reads.get(head_key(queue))
        # Entries past their expiry belong to tasks whose worker stopped renewing them.
        reads.zremrangebyscore(in_flight_key(queue), "-inf", now)
        reads.zcard(in_flight_key(queue))
    results = reads.execute()

    snapshot: dict = {}
    writes = redis_client.pipeline(transaction=False)
    step = 2 * len(PRIORITY_STEPS) + 3
    for i, queue in enumerate(queues):
        chunk = results[i * step:(i + 1) * step]
        lengths = chunk[:len(PRIORITY_STEPS)]
        tails = chunk[len(PRIORITY_STEPS):2 * len(PRIORITY_STEPS)]
        stored = chunk[2 * len(PRIORITY_STEPS)]
        in_flight = int(chunk[-1] or 0)
        depth = int(sum(lengths))
        head = next((tail for length, tail in zip(lengths, tails) if length and tail is not None), None)

        wait_s = 0
        if head is None:
            writes.delete(head_key(queue))
        else:
            identity = _head_identity(head)
            previous = None
            if stored:
                try:
                    previous = json.loads(stored)
                except (ValueError, TypeError, UnicodeDecodeError):
                    previous = None
            if previous and previous.get("id") == identity:
                wait_s = max(0, int(now - float(previous.get("since", now))))
            else:
                writes.set(head_key(queue), json.dumps({"id": identity, "since": now}), ex=HEAD_KEY_TTL_SECONDS)

        snapshot[queue] = {"depth": depth, "wait_s": wait_s, "in_flight": in_flight}
    writes.execute()
    return snapshot


def queue_log_fields(snapshot: dict) -> dict:
    """Flatten a snapshot into ``queue_<name>_<metric>`` log attributes."""
    fields = {}
    for queue, metrics in snapshot.items():
        name = "".join(ch if ch.isalnum() else "_" for ch in queue.lower())
        for metric, value in metrics.items():
            fields[f"queue_{name}_{metric}"] = value
    return fields
