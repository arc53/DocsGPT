"""One job at a time rewrites a source's index.

A FAISS index is one file: each job loads it, changes it and saves the whole
of it, so two jobs on one source at once lose whichever saved first. A sync
also wipes and rebuilds the index while it rewrites the source's tree. The
jobs that change a source's chunks (a sync, adding or refreshing Website
pages, removing them, converting to a wiki) take this lock first.

It is a Redis key with an expiry, renewed while the job runs, so a worker that
dies frees it within ``ttl_seconds``. Without Redis (or when Redis errors) the
job runs unlocked, as before the lock existed: a missing lock is a narrower
race, not a reason to fail the job.

``graph_extract_lock`` is the same kind of lock under its own key: one graph
extraction at a time per source, so two runs can't each spend the source's
remaining chunk allowance. It is apart from the index lock, so a page change
doesn't wait for a long extraction.
"""

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from docsgpt.cache import get_redis_instance
from docsgpt.core.settings import settings

logger = logging.getLogger(__name__)


def worker_wait_seconds(visibility_timeout: int) -> int:
    """How long a worker job waits for a busy source: half the broker's visibility timeout.

    Tasks are acked late, so a task still running when the visibility timeout
    passes is handed to another worker and runs twice. A job waiting on the
    lock is still running: it must give up (``SourceBusy``) well before that,
    and leave the rest of the window for its own work once it gets the lock.

    Args:
        visibility_timeout: ``CELERY_VISIBILITY_TIMEOUT`` in seconds.

    Returns:
        The wait in seconds.
    """
    return max(0, int(visibility_timeout) // 2)


# How long a worker job waits for the source to be free; derived from the
# visibility timeout so a waiting task is never redelivered.
WORKER_WAIT_SECONDS = worker_wait_seconds(settings.CELERY_VISIBILITY_TIMEOUT)
_TTL_SECONDS = 600

# Check the token and act in one step on the server: a separate GET then
# SET/DEL could act on a lock another job took in between.
#: Pushes the expiry forward only while the key holds this job's token.
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
#: Deletes the key only while it holds this job's token.
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


class SourceBusy(RuntimeError):
    """Another job holds the source's index lock past the wait."""


def lock_key(source_id: str) -> str:
    """The Redis key of a source's index lock."""
    return f"docsgpt:source_index_lock:{source_id}"


def graph_extract_lock_key(source_id: str) -> str:
    """The Redis key of a source's graph extraction lock."""
    return f"docsgpt:graph_extract_lock:{source_id}"


def _acquire(redis: Any, key: str, token: str, ttl_seconds: int, wait_seconds: float,
             poll_seconds: float) -> Optional[bool]:
    """Take the lock, polling until ``wait_seconds`` pass.

    Returns:
        True when held, ``None`` when Redis failed (run unlocked).

    Raises:
        SourceBusy: Still held by another job after the wait.
    """
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        try:
            if redis.set(key, token, nx=True, ex=ttl_seconds):
                return True
        except Exception as err:  # noqa: BLE001 - run unlocked rather than fail the job
            logger.warning(f"Lock {key} unavailable, running unlocked: {err}")
            return None
        if time.monotonic() >= deadline:
            raise SourceBusy("Another change to this source is still running; try again when it finishes")
        time.sleep(poll_seconds)


def _renew_until(stop: threading.Event, redis: Any, key: str, token: str, ttl_seconds: int,
                 renew_seconds: float) -> None:
    """Push the lock's expiry forward every ``renew_seconds`` while this job holds it."""
    while not stop.wait(renew_seconds):
        try:
            if not redis.eval(_RENEW_LUA, 1, key, token, int(ttl_seconds)):
                logger.warning(f"Lost the lock {key}")
                return
        except Exception as err:  # noqa: BLE001 - the expiry still frees it
            logger.warning(f"Could not renew the lock {key}: {err}")


@contextmanager
def _redis_lock(
    key: str,
    wait_seconds: float,
    ttl_seconds: int,
    poll_seconds: float,
    renew: bool,
    renew_seconds: Optional[float],
) -> Iterator[None]:
    """Hold the Redis lock ``key`` for the duration of the block (see ``source_index_lock``).

    Args:
        key: The lock's Redis key.
        wait_seconds: How long to wait for another job to finish.
        ttl_seconds: The lock's expiry, renewed while held.
        poll_seconds: How often to retry while waiting.
        renew: Renew the expiry in a background thread while held.
        renew_seconds: How often to renew; a third of ``ttl_seconds`` by default.

    Yields:
        Nothing; the block runs holding the lock.

    Raises:
        SourceBusy: Another job held it for all of ``wait_seconds``.
    """
    redis = get_redis_instance()
    token = uuid.uuid4().hex
    held = None
    if redis is None:
        logger.warning(f"No Redis for the lock {key}; the job runs unlocked")
    else:
        held = _acquire(redis, key, token, ttl_seconds, wait_seconds, poll_seconds)
    stop = threading.Event()
    renewer = None
    if held and renew:
        renewer = threading.Thread(
            target=_renew_until,
            args=(stop, redis, key, token, ttl_seconds, renew_seconds or ttl_seconds / 3),
            daemon=True,
        )
        renewer.start()
    try:
        yield
    finally:
        stop.set()
        if renewer is not None:
            renewer.join(timeout=5)
        if held:
            try:
                redis.eval(_RELEASE_LUA, 1, key, token)
            except Exception as err:  # noqa: BLE001 - the expiry frees it
                logger.warning(f"Could not release the lock {key}: {err}")


@contextmanager
def source_index_lock(
    source_id: str,
    wait_seconds: float = WORKER_WAIT_SECONDS,
    ttl_seconds: int = _TTL_SECONDS,
    poll_seconds: float = 1.0,
    renew: bool = True,
    renew_seconds: Optional[float] = None,
) -> Iterator[None]:
    """Hold a source's index lock for the duration of the block.

    Args:
        source_id: The source.
        wait_seconds: How long to wait for another job to finish.
        ttl_seconds: The lock's expiry, renewed while held.
        poll_seconds: How often to retry while waiting.
        renew: Renew the expiry in a background thread while held.
        renew_seconds: How often to renew; a third of ``ttl_seconds`` by default.

    Yields:
        Nothing; the block runs holding the lock.

    Raises:
        SourceBusy: Another job held it for all of ``wait_seconds``.
    """
    with _redis_lock(lock_key(str(source_id)), wait_seconds, ttl_seconds, poll_seconds, renew, renew_seconds):
        yield


@contextmanager
def graph_extract_lock(
    source_id: str,
    wait_seconds: float = WORKER_WAIT_SECONDS,
    ttl_seconds: int = _TTL_SECONDS,
    poll_seconds: float = 1.0,
    renew: bool = True,
    renew_seconds: Optional[float] = None,
) -> Iterator[None]:
    """Hold a source's graph extraction lock for the duration of the block.

    Each extraction reads how much of the source's chunk cap is left and
    spends it; two at once would each spend all of it. This lock runs them
    one at a time. It is not the index lock: page changes and syncs go on
    while a graph is extracted.

    Args:
        source_id: The source.
        wait_seconds: How long to wait for another extraction to finish.
        ttl_seconds: The lock's expiry, renewed while held.
        poll_seconds: How often to retry while waiting.
        renew: Renew the expiry in a background thread while held.
        renew_seconds: How often to renew; a third of ``ttl_seconds`` by default.

    Yields:
        Nothing; the block runs holding the lock.

    Raises:
        SourceBusy: Another extraction held it for all of ``wait_seconds``.
    """
    key = graph_extract_lock_key(str(source_id))
    with _redis_lock(key, wait_seconds, ttl_seconds, poll_seconds, renew, renew_seconds):
        yield
