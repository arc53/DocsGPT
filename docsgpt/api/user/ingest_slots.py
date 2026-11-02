"""Per-user cap on running whole-source ingests (``INGEST_MAX_CONCURRENT_PER_USER``).

Each running ingest holds a member of the sorted set ``user:{id}:ingest_slots``
named by its task id and scored by when it last renewed; a thread renews it
while the task runs, and the task removes it when it ends. A task whose worker
was killed stops counting :data:`SLOT_TTL_SECONDS` after its last renewal, so
a crash cannot keep a slot. This is the lease pattern of the SSE connection cap
(``docsgpt/streaming/sse_leases.py``).

A task over the cap is published again with a countdown and gives up its
worker slot without running, so other users' ingests take the slots. The gate
sits outside ``with_idempotency``: waiting for a slot claims no lease and
spends none of the poison guard's attempts, and the task's ``task_dedup`` row
stays queued, so a same-source submit still joins it. A deferred ingest that
has a progress row (a resume) has it bumped, so the reconciler doesn't take
the wait for a stall and queue it again.
"""

from __future__ import annotations

import functools
import inspect
import logging
import random
import threading
import time
from typing import Any, Callable, Optional

from celery.exceptions import Retry

from docsgpt.cache import get_redis_instance
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

# A slot lives this long past its last renewal: three missed renewals.
SLOT_TTL_SECONDS = 120
SLOT_RENEW_SECONDS = 40

# A deferred task runs again after this many seconds, plus up to the jitter,
# so tasks deferred together don't all come back at once.
DEFER_SECONDS = 30
DEFER_JITTER_SECONDS = 15


def slots_key(user: str) -> str:
    """Redis sorted set of the ingests ``user`` is running, scored by last renewal."""
    return f"user:{user}:ingest_slots"


def acquire_slot(redis: Any, user: str, holder: str, cap: int) -> bool:
    """Take one of ``user``'s ``cap`` slots for ``holder``.

    Args:
        redis: A Redis client.
        user: The user whose ingests are counted.
        holder: The task id; a redelivered task keeps the slot it held.
        cap: Most slots the user may hold.

    Returns:
        ``False`` when the user already holds ``cap`` slots; ``True``
        otherwise, including when Redis fails (fail-open).
    """
    key = slots_key(user)
    now = time.time()
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.zremrangebyscore(key, "-inf", now - SLOT_TTL_SECONDS)
        pipe.zadd(key, {holder: now})
        pipe.zcard(key)
        pipe.expire(key, SLOT_TTL_SECONDS)
        results = pipe.execute()
    except Exception:
        logger.debug("ingest slot acquire failed for user=%s; running anyway", user, exc_info=True)
        # EXEC may have run before its reply was lost: give the member back.
        release_slot(redis, user, holder)
        return True
    if int(results[2]) > cap:
        release_slot(redis, user, holder)
        return False
    return True


def renew_slot(redis: Any, user: str, holder: str) -> None:
    """Re-stamp ``holder``'s slot; a slot already pruned or released stays gone."""
    key = slots_key(user)
    try:
        pipe = redis.pipeline(transaction=True)
        pipe.zadd(key, {holder: time.time()}, xx=True)
        pipe.expire(key, SLOT_TTL_SECONDS)
        pipe.execute()
    except Exception:
        logger.debug("ingest slot renewal failed for user=%s", user, exc_info=True)


def release_slot(redis: Any, user: str, holder: str) -> None:
    """Give ``holder``'s slot back; failures are logged, the TTL frees it anyway."""
    try:
        redis.zrem(slots_key(user), holder)
    except Exception:
        logger.debug("ingest slot release failed for user=%s", user, exc_info=True)


def _renew_loop(redis: Any, user: str, holder: str, stop: threading.Event) -> None:
    while not stop.wait(SLOT_RENEW_SECONDS):
        renew_slot(redis, user, holder)


def _requeue(task: Any, countdown: int) -> Any:
    """Publish ``task`` again under its own id and queue, without counting a retry.

    Args:
        task: The bound Celery task.
        countdown: Seconds until it may run.

    Returns:
        The signature that was sent.
    """
    signature = task.signature_from_request(task.request, countdown=countdown, retries=task.request.retries)
    signature.apply_async()
    return signature


def _keep_progress_alive(source_id: Optional[str]) -> None:
    """Bump the ingest's progress row, if it has one, so a wait reads as alive."""
    if not source_id:
        return
    try:
        from docsgpt.storage.db.repositories.ingest_chunk_progress import IngestChunkProgressRepository
        from docsgpt.storage.db.session import db_session

        with db_session() as conn:
            IngestChunkProgressRepository(conn).bump_heartbeat(str(source_id))
    except Exception:
        logger.debug("Could not bump the progress of deferred ingest %s", source_id, exc_info=True)


def _gated_call(fn: Callable[..., Any], self: Any, args: tuple, kwargs: dict) -> Optional[tuple]:
    """The user and task id to gate a call on, or ``None`` when it runs ungated."""
    cap = int(settings.INGEST_MAX_CONCURRENT_PER_USER)
    request = getattr(self, "request", None)
    if cap <= 0 or request is None or getattr(request, "called_directly", True) or getattr(request, "is_eager", False):
        return None
    holder = getattr(request, "id", None)
    try:
        bound = inspect.signature(fn).bind_partial(self, *args, **kwargs).arguments
    except TypeError:
        return None
    user = bound.get("user")
    if not isinstance(holder, str) or not holder or not isinstance(user, str) or not user:
        return None
    return user, holder, cap, bound.get("source_id") or bound.get("doc_id")


def with_ingest_slot(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run a bound ingest task only while its user holds fewer than ``INGEST_MAX_CONCURRENT_PER_USER`` slots.

    Over the cap the task is published again with a countdown and raises
    :class:`celery.exceptions.Retry`, so the worker acks it and frees the
    slot. A direct or eager call, a call with no ``user``, and a missing
    Redis run ungated.
    """

    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        gate = _gated_call(fn, self, args, kwargs)
        redis = get_redis_instance() if gate is not None else None
        if gate is None or redis is None:
            return fn(self, *args, **kwargs)
        user, holder, cap, source_id = gate
        if not acquire_slot(redis, user, holder, cap):
            countdown = DEFER_SECONDS + random.randint(0, DEFER_JITTER_SECONDS)
            logger.info(
                "ingest %s deferred %ss: user %s already runs %s ingest(s)", holder, countdown, user, cap,
                extra={"task_id": holder, "user_id": user, "countdown": countdown},
            )
            _keep_progress_alive(source_id)
            signature = _requeue(self, countdown)
            raise Retry(f"over the per-user ingest cap ({cap}); again in {countdown}s", when=countdown, sig=signature)
        stop = threading.Event()
        renewer = threading.Thread(
            target=_renew_loop, args=(redis, user, holder, stop), daemon=True, name=f"ingest-slot:{holder[:32]}",
        )
        renewer.start()
        try:
            return fn(self, *args, **kwargs)
        finally:
            stop.set()
            renewer.join(timeout=5)
            release_slot(redis, user, holder)

    wrapper._ingest_slot_gated = True  # type: ignore[attr-defined]
    return wrapper
