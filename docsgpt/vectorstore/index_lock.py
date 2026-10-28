"""One job at a time rewrites a source's index.

A FAISS index is one file: each job loads it, changes it and saves the whole
of it, so two jobs on one source at once lose whichever saved first. A sync
also wipes and rebuilds the index while it rewrites the source's tree. The
jobs that change a source's chunks (a sync, adding or refreshing Website
pages, removing them, converting to a wiki) take this lock first.

It is a Redis key with an expiry, renewed while the job runs, so a worker that
dies frees it within ``_TTL_SECONDS``. Without Redis (or when Redis errors) the
job runs unlocked, as before the lock existed: a missing lock is a narrower
race, not a reason to fail the job.

``graph_extract_lock`` is the same kind of lock under its own key: one graph
extraction at a time per source, so two runs can't each spend the source's
remaining chunk allowance. It is apart from the index lock, so a page change
doesn't wait for a long extraction.

``connection_fetch_lock`` holds one remote fetch at a time per connection:
sources added together from one GitHub connection download one after the
other instead of sharing out the account's API rate limit.
"""

import logging
import threading
import time
import uuid
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Iterator, Optional

from docsgpt.cache import LOCK_RELEASE_LUA, LOCK_RENEW_LUA, get_redis_instance
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)

# How long a worker job waits for a busy source: half the broker's visibility
# timeout. Tasks are acked late, so a task still running when the visibility
# timeout passes is handed to another worker and runs twice; a job waiting on
# the lock must give up (``SourceBusy``) well before that, and leave the rest
# of the window for its own work once it gets the lock.
WORKER_WAIT_SECONDS = max(0, int(settings.CELERY_VISIBILITY_TIMEOUT) // 2)
# The lock's expiry, pushed forward every ``_RENEW_SECONDS`` while it is held.
_TTL_SECONDS = 600
_RENEW_SECONDS = _TTL_SECONDS / 3


class SourceBusy(RuntimeError):
    """Another job holds the source's index lock past the wait."""


def lock_key(source_id: str) -> str:
    """The Redis key of a source's index lock."""
    return f"docsgpt:source_index_lock:{source_id}"


def graph_extract_lock_key(source_id: str) -> str:
    """The Redis key of a source's graph extraction lock."""
    return f"docsgpt:graph_extract_lock:{source_id}"


def connection_fetch_lock_key(connection_id: str) -> str:
    """The Redis key of a connection's fetch lock."""
    return f"docsgpt:connection_fetch_lock:{connection_id}"


_SOURCE_BUSY = "Another change to this source is still running; try again when it finishes"


def _acquire(
    redis: Any, key: str, token: str, wait_seconds: float, poll_seconds: float, busy_message: str = _SOURCE_BUSY,
) -> Optional[bool]:
    """Take the lock, polling until ``wait_seconds`` pass.

    Returns:
        True when held, ``None`` when Redis failed (run unlocked).

    Raises:
        SourceBusy: Still held by another job after the wait.
    """
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        try:
            if redis.set(key, token, nx=True, ex=_TTL_SECONDS):
                return True
        except Exception as err:  # noqa: BLE001 - run unlocked rather than fail the job
            logger.warning(f"Lock {key} unavailable, running unlocked: {err}")
            return None
        if time.monotonic() >= deadline:
            raise SourceBusy(busy_message)
        time.sleep(poll_seconds)


def _renew_until(stop: threading.Event, redis: Any, key: str, token: str) -> None:
    """Push the lock's expiry forward every ``_RENEW_SECONDS`` while this job holds it."""
    while not stop.wait(_RENEW_SECONDS):
        try:
            if not redis.eval(LOCK_RENEW_LUA, 1, key, token, int(_TTL_SECONDS)):
                logger.warning(f"Lost the lock {key}")
                return
        except Exception as err:  # noqa: BLE001 - the expiry still frees it
            logger.warning(f"Could not renew the lock {key}: {err}")


@contextmanager
def _redis_lock(
    key: str, wait_seconds: float, poll_seconds: float, busy_message: str = _SOURCE_BUSY,
) -> Iterator[None]:
    """Hold the Redis lock ``key`` for the duration of the block, renewing it while held.

    Args:
        key: The lock's Redis key.
        wait_seconds: How long to wait for another job to finish.
        poll_seconds: How often to retry while waiting.
        busy_message: The ``SourceBusy`` message after the wait.

    Yields:
        Nothing; the block runs holding the lock (or unlocked when Redis is missing or failing).

    Raises:
        SourceBusy: Another job held it for all of ``wait_seconds``.
    """
    redis = get_redis_instance()
    token = uuid.uuid4().hex
    held = None
    if redis is None:
        logger.warning(f"No Redis for the lock {key}; the job runs unlocked")
    else:
        held = _acquire(redis, key, token, wait_seconds, poll_seconds, busy_message)
    stop = threading.Event()
    renewer = None
    if held:
        renewer = threading.Thread(target=_renew_until, args=(stop, redis, key, token), daemon=True)
        renewer.start()
    try:
        yield
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=5)
        if held:
            try:
                redis.eval(LOCK_RELEASE_LUA, 1, key, token)
            except Exception as err:  # noqa: BLE001 - the expiry frees it
                logger.warning(f"Could not release the lock {key}: {err}")


def source_index_lock(
    source_id: str, wait_seconds: float = WORKER_WAIT_SECONDS, poll_seconds: float = 1.0
) -> AbstractContextManager[None]:
    """Hold a source's index lock for the block; raises ``SourceBusy`` after ``wait_seconds``."""
    return _redis_lock(lock_key(str(source_id)), wait_seconds, poll_seconds)


def graph_extract_lock(
    source_id: str, wait_seconds: float = WORKER_WAIT_SECONDS, poll_seconds: float = 1.0
) -> AbstractContextManager[None]:
    """Hold a source's graph extraction lock for the block; raises ``SourceBusy`` after ``wait_seconds``."""
    return _redis_lock(graph_extract_lock_key(str(source_id)), wait_seconds, poll_seconds)


def connection_fetch_lock(
    connection_id: str, wait_seconds: float = WORKER_WAIT_SECONDS, poll_seconds: float = 1.0
) -> AbstractContextManager[None]:
    """Hold a connection's fetch lock for the block; raises ``SourceBusy`` after ``wait_seconds``."""
    return _redis_lock(
        connection_fetch_lock_key(str(connection_id)), wait_seconds, poll_seconds,
        busy_message="Another download from this connection is still running; try again when it finishes",
    )
