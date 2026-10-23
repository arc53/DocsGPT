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
"""

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from docsgpt.cache import get_redis_instance

logger = logging.getLogger(__name__)

# How long a worker job waits for the source to be free.
WORKER_WAIT_SECONDS = 3600
# How long an HTTP request waits before answering that the source is busy.
REQUEST_WAIT_SECONDS = 5
_TTL_SECONDS = 600


class SourceBusy(RuntimeError):
    """Another job holds the source's index lock past the wait."""


def lock_key(source_id: str) -> str:
    """The Redis key of a source's index lock."""
    return f"docsgpt:source_index_lock:{source_id}"


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
            logger.warning(f"Source index lock unavailable, running unlocked: {err}")
            return None
        if time.monotonic() >= deadline:
            raise SourceBusy("Another change to this source is still running; try again when it finishes")
        time.sleep(poll_seconds)


def _holds(redis: Any, key: str, token: str) -> bool:
    value = redis.get(key)
    if isinstance(value, bytes):
        value = value.decode()
    return value == token


def _renew_until(stop: threading.Event, redis: Any, key: str, token: str, ttl_seconds: int,
                 renew_seconds: float) -> None:
    """Push the lock's expiry forward every ``renew_seconds`` while this job holds it."""
    while not stop.wait(renew_seconds):
        try:
            if not _holds(redis, key, token):
                logger.warning(f"Lost the source index lock {key}")
                return
            redis.set(key, token, xx=True, ex=ttl_seconds)
        except Exception as err:  # noqa: BLE001 - the expiry still frees it
            logger.warning(f"Could not renew the source index lock {key}: {err}")


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
    redis = get_redis_instance()
    key = lock_key(str(source_id))
    token = uuid.uuid4().hex
    held = None
    if redis is None:
        logger.warning(f"No Redis for the source index lock; {source_id} runs unlocked")
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
                if _holds(redis, key, token):
                    redis.delete(key)
            except Exception as err:  # noqa: BLE001 - the expiry frees it
                logger.warning(f"Could not release the source index lock {key}: {err}")
