"""The per-process pool that runs hand-off-able tool calls, and the lease on the jobs it holds.

A dedicated, bounded pool: never the WSGI threadpool. A call that finds every
slot busy runs inline on the request thread, exactly as before background
jobs existed, so a saturated pool degrades to the old behaviour instead of
queueing.

Jobs a process runs itself (``inprocess`` and ``celery`` runners) carry this
process's lease. One daemon thread stamps their ``heartbeat_at`` every
:data:`HEARTBEAT_SECONDS`; a process that dies stops stamping, and the
reconciler marks its jobs ``lost`` once the heartbeat is
``BACKGROUND_LEASE_STALE_SECONDS`` old.
"""

from __future__ import annotations

import contextvars
import logging
import os
import socket
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional, Set

logger = logging.getLogger(__name__)

#: Seconds between heartbeats of the jobs this process holds.
HEARTBEAT_SECONDS = 10


def stale_seconds() -> int:
    """Heartbeat age after which the reconciler declares a held job lost (``BACKGROUND_LEASE_STALE_SECONDS``)."""
    from docsgpt.core.settings import settings

    return int(settings.BACKGROUND_LEASE_STALE_SECONDS)

_lock = threading.Lock()
_pid: Optional[int] = None
_executor: Optional[ThreadPoolExecutor] = None
_slots: Optional[threading.BoundedSemaphore] = None
_lease_owner: Optional[str] = None
_held: Set[str] = set()
_heartbeat_thread: Optional[threading.Thread] = None


def _reset_for_process() -> None:
    """Start fresh state in a new (forked) process; caller holds ``_lock``."""
    global _pid, _executor, _slots, _lease_owner, _held, _heartbeat_thread
    from docsgpt.core.settings import settings

    size = max(1, int(settings.BACKGROUND_POOL_SIZE))
    _pid = os.getpid()
    _executor = ThreadPoolExecutor(max_workers=size, thread_name_prefix="bg-tool")
    _slots = threading.BoundedSemaphore(size)
    _lease_owner = f"{socket.gethostname()}:{_pid}:{uuid.uuid4().hex[:8]}"
    _held = set()
    _heartbeat_thread = None


def _ensure() -> None:
    with _lock:
        if _pid != os.getpid() or _executor is None:
            _reset_for_process()


def lease_owner() -> str:
    """This process's lease id: ``host:pid:nonce``."""
    _ensure()
    assert _lease_owner is not None
    return _lease_owner


def try_submit(fn: Callable[[], object]) -> Optional[Future]:
    """Run ``fn`` on a pool thread, or return None when every slot is busy.

    The caller's context variables (log context, trace) travel with the call.

    Args:
        fn: The work; its return value or exception becomes the future's.

    Returns:
        The future, or None when the pool is full (run the call inline then).
    """
    _ensure()
    assert _slots is not None and _executor is not None
    if not _slots.acquire(blocking=False):
        return None
    ctx = contextvars.copy_context()
    slots = _slots

    def _run():
        try:
            return ctx.run(fn)
        finally:
            slots.release()

    try:
        return _executor.submit(_run)
    except RuntimeError:
        # Interpreter shutdown: the pool no longer takes work.
        slots.release()
        return None


def hold(job_id: str) -> None:
    """Start heartbeating a job this process runs."""
    _ensure()
    global _heartbeat_thread
    with _lock:
        _held.add(str(job_id))
        if _heartbeat_thread is None or not _heartbeat_thread.is_alive():
            _heartbeat_thread = threading.Thread(target=_heartbeat_loop, name="bg-job-heartbeat", daemon=True)
            _heartbeat_thread.start()


def release(job_id: str) -> None:
    """Stop heartbeating a job (it finished, or another runner took it)."""
    with _lock:
        _held.discard(str(job_id))


def held() -> Set[str]:
    """Ids of the jobs this process holds (a copy)."""
    with _lock:
        return set(_held)


def beat_once() -> int:
    """Stamp the heartbeat of every job this process holds; returns rows touched."""
    if not held():
        return 0
    from docsgpt.storage.db.repositories.background_jobs import BackgroundJobsRepository
    from docsgpt.storage.db.session import db_session

    with db_session() as conn:
        return BackgroundJobsRepository(conn).heartbeat(lease_owner())


def _heartbeat_loop() -> None:
    stop = threading.Event()
    while not stop.wait(HEARTBEAT_SECONDS):
        if not held():
            # Exit when idle; the next ``hold`` starts a new thread.
            with _lock:
                if not _held:
                    global _heartbeat_thread
                    _heartbeat_thread = None
                    return
        try:
            beat_once()
        except Exception:
            # A missed beat is retried in HEARTBEAT_SECONDS; the stale threshold allows several misses.
            logger.warning("background job heartbeat failed", exc_info=True)
