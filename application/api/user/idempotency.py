"""Per-Celery-task idempotency wrapper backed by ``task_dedup``."""

from __future__ import annotations

import functools
import logging
import threading
import uuid
from typing import Any, Callable, Optional

from application.storage.db.repositories.idempotency import IdempotencyRepository
from application.storage.db.session import db_readonly, db_session


logger = logging.getLogger(__name__)


# Poison-loop cap; transient-failure headroom without infinite retry.
MAX_TASK_ATTEMPTS = 5

# 30s heartbeat / 60s TTL → ~2 missed ticks of slack before reclaim.
LEASE_TTL_SECONDS = 60
LEASE_HEARTBEAT_INTERVAL = 30

# 10 × 60s ≈ 5 min of deferral before giving up on a held lease.
LEASE_RETRY_MAX = 10


def with_idempotency(task_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Short-circuit on completed key; gate concurrent runs via a lease.

    Entry short-circuits:
      - completed row → return cached result
      - live lease held → retry(countdown=LEASE_TTL_SECONDS)
      - attempt_count > MAX_TASK_ATTEMPTS → poison-loop alert
    Success writes ``completed``; exceptions leave ``pending`` for
    autoretry until the poison-loop guard trips.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(self, *args: Any, idempotency_key: Any = None, **kwargs: Any) -> Any:
            key = idempotency_key if isinstance(idempotency_key, str) and idempotency_key else None
            if key is None:
                return fn(self, *args, idempotency_key=idempotency_key, **kwargs)

            cached = _lookup_completed(key)
            if cached is not None:
                logger.info(
                    "idempotency hit for task=%s key=%s — returning cached result",
                    task_name, key,
                )
                return cached

            owner_id = str(uuid.uuid4())
            attempt = _try_claim_lease(
                key, task_name, _safe_task_id(self), owner_id,
            )
            if attempt is None:
                # Live lease held by another worker. Re-queue and bail
                # quickly — by the time the retry fires (LEASE_TTL
                # seconds), Worker 1 has either finalised (we'll hit
                # ``_lookup_completed`` and return cached) or its lease
                # has expired and we can claim.
                logger.info(
                    "idempotency: live lease held; deferring task=%s key=%s",
                    task_name, key,
                )
                raise self.retry(
                    countdown=LEASE_TTL_SECONDS,
                    max_retries=LEASE_RETRY_MAX,
                )

            if attempt > MAX_TASK_ATTEMPTS:
                logger.error(
                    "idempotency poison-loop guard: task=%s key=%s attempts=%s",
                    task_name, key, attempt,
                    extra={
                        "alert": "idempotency_poison_loop",
                        "task_name": task_name,
                        "idempotency_key": key,
                        "attempts": attempt,
                    },
                )
                poisoned = {
                    "success": False,
                    "error": "idempotency poison-loop guard tripped",
                    "attempts": attempt,
                }
                _finalize(key, poisoned, status="failed")
                return poisoned

            heartbeat_thread, heartbeat_stop = _start_lease_heartbeat(
                key, owner_id,
            )
            try:
                result = fn(self, *args, idempotency_key=idempotency_key, **kwargs)
                _finalize(key, result, status="completed")
                return result
            except Exception:
                # Drop the lease so the next retry doesn't wait LEASE_TTL.
                _release_lease(key, owner_id)
                raise
            finally:
                _stop_lease_heartbeat(heartbeat_thread, heartbeat_stop)

        return wrapper

    return decorator


def _lookup_completed(key: str) -> Any:
    """Return cached ``result_json`` if a completed row exists for ``key``, else None."""
    with db_readonly() as conn:
        row = IdempotencyRepository(conn).get_task(key)
    if row is None:
        return None
    if row.get("status") != "completed":
        return None
    return row.get("result_json")


def _try_claim_lease(
    key: str, task_name: str, task_id: str, owner_id: str,
) -> Optional[int]:
    """Atomic CAS; returns ``attempt_count`` or ``None`` when held.

    DB outage → treated as ``attempt=1`` so transient failures don't
    block all task execution; reconciler repairs the lease columns.
    """
    try:
        with db_session() as conn:
            return IdempotencyRepository(conn).try_claim_lease(
                key=key,
                task_name=task_name,
                task_id=task_id,
                owner_id=owner_id,
                ttl_seconds=LEASE_TTL_SECONDS,
            )
    except Exception:
        logger.exception(
            "idempotency lease-claim failed for key=%s task=%s", key, task_name,
        )
        return 1


def _finalize(key: str, result_json: Any, *, status: str) -> None:
    """Best-effort terminal write. Never let DB outage fail the task."""
    try:
        with db_session() as conn:
            IdempotencyRepository(conn).finalize_task(
                key=key, result_json=result_json, status=status,
            )
    except Exception:
        logger.exception(
            "idempotency finalize failed for key=%s status=%s", key, status,
        )


def _release_lease(key: str, owner_id: str) -> None:
    """Best-effort lease release on the wrapper's exception path."""
    try:
        with db_session() as conn:
            IdempotencyRepository(conn).release_lease(key, owner_id)
    except Exception:
        logger.exception("idempotency release-lease failed for key=%s", key)


def _start_lease_heartbeat(
    key: str, owner_id: str,
) -> tuple[threading.Thread, threading.Event]:
    """Spawn a daemon thread that bumps ``lease_expires_at`` every
    :data:`LEASE_HEARTBEAT_INTERVAL` seconds until ``stop_event`` fires.

    Mirrors ``application.worker._start_ingest_heartbeat`` so the two
    durability heartbeats share shape and cadence.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_lease_heartbeat_loop,
        args=(key, owner_id, stop_event, LEASE_HEARTBEAT_INTERVAL),
        daemon=True,
        name=f"idempotency-lease-heartbeat:{key[:32]}",
    )
    thread.start()
    return thread, stop_event


def _stop_lease_heartbeat(
    thread: threading.Thread, stop_event: threading.Event,
) -> None:
    """Signal the heartbeat thread to exit and join with a short timeout."""
    stop_event.set()
    thread.join(timeout=10)


def _lease_heartbeat_loop(
    key: str,
    owner_id: str,
    stop_event: threading.Event,
    interval: int,
) -> None:
    """Refresh the lease until ``stop_event`` is set or ownership is lost.

    A failed refresh (rowcount 0) means another worker stole the lease
    after expiry — at that point the damage is already possible, so we
    log and keep ticking. Don't escalate to thread death; the main task
    body needs to keep running so its outcome is at least *recorded*.
    """
    while not stop_event.wait(interval):
        try:
            with db_session() as conn:
                still_owned = IdempotencyRepository(conn).refresh_lease(
                    key=key, owner_id=owner_id, ttl_seconds=LEASE_TTL_SECONDS,
                )
            if not still_owned:
                logger.warning(
                    "idempotency lease lost mid-task for key=%s "
                    "(another worker may have taken over)",
                    key,
                )
        except Exception:
            logger.exception(
                "idempotency lease-heartbeat tick failed for key=%s", key,
            )


def _safe_task_id(task_self: Any) -> str:
    """Best-effort extraction of ``self.request.id`` from a Celery task."""
    try:
        request = getattr(task_self, "request", None)
        task_id: Optional[str] = (
            getattr(request, "id", None) if request is not None else None
        )
    except Exception:
        task_id = None
    return task_id or "unknown"
