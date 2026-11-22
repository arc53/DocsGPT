"""A limit on OCR requests in flight to one endpoint, shared by every worker process.

A hosted OCR API rate-limits a deployment as a whole, while each file's
pages are sent by its own thread pool (``OCR_DEEPSEEK_CONCURRENCY``) in
whichever worker process parses it. Several ingests at once would each
spend the full per-file concurrency against one quota, so every page request
also takes a slot here first.

The slots live in Redis (``CACHE_REDIS_URL``) as expiring leases: a sorted
set of lease ids scored by when they lapse, so a worker that dies holding a
slot gives it back once its lease runs out. The allowed count adapts: a 429
halves it (never below one) and a run of clean responses raises it by one
again, never above ``OCR_MAX_IN_FLIGHT``. Without a reachable Redis the same
limit and adaptation apply within the process.

Taking a slot is three commands in one ``MULTI``: drop lapsed leases, add
ours, count. A count over the limit removes ours again and waits. Every
holder saw a count that included every earlier holder, so no more than the
limit ever hold a slot at once, without a Lua script. A held lease is renewed
while its request runs, so a slow response never outlives it; only a worker
that died stops renewing. The allowed count and the run of clean responses
change together in one ``WATCH``ed transaction, so two 429s at once halve it
twice.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

#: Clean responses in a row that raise the allowed count by one.
CLEAN_RUN_TO_GROW = 10
#: How long a Redis that failed is left alone before it is tried again.
_REDIS_RETRY_SECONDS = 30.0
#: How long the adapted limit is remembered without any traffic.
_STATE_TTL_SECONDS = 3600
#: Polling interval while waiting for a slot, before jitter.
_POLL_SECONDS = 0.1
_KEY_PREFIX = "docsgpt:ocr:inflight"


def _now() -> float:
    """Wall-clock seconds; a module attribute so tests can move it."""
    return time.time()


def _sleep(seconds: float) -> None:
    """Wait for a slot; a module attribute so tests can skip it."""
    time.sleep(seconds)


def _redis_client() -> Optional[Any]:
    """The shared Redis client, or ``None`` when there is none."""
    try:
        from docsgpt.cache import get_redis_instance

        return get_redis_instance()
    except Exception:  # noqa: BLE001 - no Redis means the per-process limit
        return None


class InFlightLimiter:
    """Slots for the requests in flight to one OCR endpoint.

    Attributes:
        key: The Redis key prefix for this endpoint.
        cap: Most requests ever allowed in flight (``OCR_MAX_IN_FLIGHT``).
        lease_seconds: How long a slot is held at most when its holder never gives it back.
    """

    def __init__(self, key: str, cap: int, lease_seconds: float) -> None:
        self.key = key
        self.cap = max(1, int(cap))
        self.lease_seconds = max(1.0, float(lease_seconds))
        self._redis_down_until = 0.0
        # The per-process fallback.
        self._cond = threading.Condition()
        self._local_in_flight = 0
        self._local_allowed = self.cap
        self._local_clean = 0

    # -- Redis -------------------------------------------------------------

    def _redis(self) -> Optional[Any]:
        if _now() < self._redis_down_until:
            return None
        return _redis_client()

    def _redis_failed(self, err: Exception) -> None:
        logger.warning(
            "OCR request limiter could not reach Redis (%s); limiting within this process for %.0fs",
            err,
            _REDIS_RETRY_SECONDS,
        )
        self._redis_down_until = _now() + _REDIS_RETRY_SECONDS

    @property
    def _leases(self) -> str:
        return f"{self.key}:leases"

    @property
    def _limit_key(self) -> str:
        return f"{self.key}:limit"

    @property
    def _clean_key(self) -> str:
        return f"{self.key}:clean"

    def _parse_allowed(self, raw: Any) -> int:
        if raw is None:
            return self.cap
        try:
            return max(1, min(self.cap, int(float(raw))))
        except (TypeError, ValueError):
            return self.cap

    def _redis_allowed(self, client: Any) -> int:
        return self._parse_allowed(client.get(self._limit_key))

    def _try_redis_slot(self, client: Any) -> Optional[str]:
        """Take a Redis slot when one is free; ``None`` when all are held.

        Raises:
            Exception: Redis failed; a lease this call added is taken back first (best effort).
        """
        lease = uuid.uuid4().hex
        now = _now()
        pipe = client.pipeline(transaction=True)
        pipe.zremrangebyscore(self._leases, "-inf", now)
        pipe.zadd(self._leases, {lease: now + self.lease_seconds})
        pipe.zcard(self._leases)
        pipe.expire(self._leases, int(self.lease_seconds * 2) + 1)
        try:
            held = int(pipe.execute()[2])
            if held <= self._redis_allowed(client):
                return lease
        except Exception:
            # The lease may be in: a slot nobody uses would block others until it lapses.
            try:
                client.zrem(self._leases, lease)
            except Exception:  # noqa: BLE001 - it lapses on its own
                pass
            raise
        client.zrem(self._leases, lease)
        return None

    def _keep_alive(self, lease: str, stop: threading.Event) -> None:
        """Push a held lease's expiry on until ``stop`` is set (the request finished)."""
        while not stop.wait(self.lease_seconds / 3):
            client = _redis_client()
            if client is None:
                continue
            try:
                client.zadd(self._leases, {lease: _now() + self.lease_seconds}, xx=True)
            except Exception:  # noqa: BLE001 - tried again on the next beat
                logger.debug("Could not renew an OCR request slot", exc_info=True)

    # -- slots --------------------------------------------------------------

    def _acquire(self) -> Tuple[str, Optional[str]]:
        """Wait for a slot; returns ``("redis", lease)`` or ``("local", None)``."""
        while True:
            client = self._redis()
            if client is not None:
                try:
                    lease = self._try_redis_slot(client)
                except Exception as err:  # noqa: BLE001 - fall back to the process limit
                    self._redis_failed(err)
                else:
                    if lease is not None:
                        return "redis", lease
                    _sleep(_POLL_SECONDS + random.uniform(0, _POLL_SECONDS))
                    continue
            with self._cond:
                if self._local_in_flight < self._local_allowed:
                    self._local_in_flight += 1
                    return "local", None
                # Wake up now and then: Redis may be back, or the limit raised.
                self._cond.wait(timeout=1.0)

    def _release(self, where: str, lease: Optional[str]) -> None:
        if where == "local":
            with self._cond:
                self._local_in_flight = max(0, self._local_in_flight - 1)
                self._cond.notify()
            return
        client = _redis_client()
        if client is None:
            return
        try:
            client.zrem(self._leases, lease)
        except Exception:  # noqa: BLE001 - the lease lapses on its own
            logger.debug("Could not give back an OCR request slot; its lease will lapse", exc_info=True)

    @contextmanager
    def slot(self) -> Iterator[None]:
        """Hold one slot for the duration of a request, renewing a Redis lease while it runs."""
        where, lease = self._acquire()
        stop = threading.Event()
        if where == "redis" and lease:
            threading.Thread(
                target=self._keep_alive, args=(lease, stop), name="ocr-slot-lease", daemon=True,
            ).start()
        try:
            yield
        finally:
            stop.set()
            self._release(where, lease)

    # -- adaptation ---------------------------------------------------------

    def allowed(self) -> int:
        """How many requests may be in flight now."""
        client = self._redis()
        if client is not None:
            try:
                return self._redis_allowed(client)
            except Exception as err:  # noqa: BLE001
                self._redis_failed(err)
        with self._cond:
            return self._local_allowed

    def _redis_adapt(self, client: Any, rate_limited: bool) -> int:
        """Change the shared allowed count and clean run together, in one ``WATCH``ed transaction."""
        result: Dict[str, int] = {}

        def update(pipe: Any) -> None:
            current = self._parse_allowed(pipe.get(self._limit_key))
            try:
                clean = int(pipe.get(self._clean_key) or 0)
            except (TypeError, ValueError):
                clean = 0
            if rate_limited:
                allowed, clean = max(1, current // 2), 0
            else:
                allowed, clean = current, clean + 1
                if clean >= CLEAN_RUN_TO_GROW:
                    allowed, clean = min(self.cap, current + 1), 0
            pipe.multi()
            pipe.set(self._limit_key, allowed, ex=_STATE_TTL_SECONDS)
            pipe.set(self._clean_key, clean, ex=_STATE_TTL_SECONDS)
            result["allowed"] = allowed

        client.transaction(update, self._limit_key, self._clean_key)
        return result["allowed"]

    def record_rate_limited(self) -> int:
        """Halve the allowed count after a 429 (never below one); returns the new count."""
        client = self._redis()
        if client is not None:
            try:
                return self._redis_adapt(client, rate_limited=True)
            except Exception as err:  # noqa: BLE001
                self._redis_failed(err)
        with self._cond:
            self._local_allowed = max(1, self._local_allowed // 2)
            self._local_clean = 0
            return self._local_allowed

    def record_success(self) -> None:
        """Count a clean response; a run of them raises the allowed count by one, up to the cap."""
        client = self._redis()
        if client is not None:
            try:
                self._redis_adapt(client, rate_limited=False)
                return
            except Exception as err:  # noqa: BLE001
                self._redis_failed(err)
        with self._cond:
            self._local_clean += 1
            if self._local_clean >= CLEAN_RUN_TO_GROW:
                self._local_clean = 0
                if self._local_allowed < self.cap:
                    self._local_allowed += 1
                    self._cond.notify()


_registry: Dict[Tuple[str, int], InFlightLimiter] = {}
_registry_lock = threading.Lock()


def limiter_for(engine: str, endpoint: str, lease_seconds: float, cap: Optional[int] = None) -> InFlightLimiter:
    """The process's limiter for one engine and endpoint.

    Args:
        engine: The engine's name (``deepseek``).
        endpoint: The URL its requests go to; two engines at one URL share slots.
        lease_seconds: How long a slot is held at most (a request's timeout, plus margin).
        cap: Most requests in flight; ``OCR_MAX_IN_FLIGHT`` when ``None``.
    """
    if cap is None:
        from docsgpt.core.settings import settings

        cap = int(settings.OCR_MAX_IN_FLIGHT)
    digest = hashlib.sha256(f"{engine}|{endpoint}".encode("utf-8")).hexdigest()[:16]
    key = f"{_KEY_PREFIX}:{engine}:{digest}"
    with _registry_lock:
        limiter = _registry.get((key, int(cap)))
        if limiter is None:
            limiter = _registry[(key, int(cap))] = InFlightLimiter(key, int(cap), lease_seconds)
        return limiter


def reset_limiters() -> None:
    """Forget every process-local limiter (tests)."""
    with _registry_lock:
        _registry.clear()
