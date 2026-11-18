"""When a sandbox session was last used by any API or worker process, kept in Redis.

Each process keeps its own ``SandboxManager`` registry and idle clock, while a
Daytona sandbox can be held by several processes at once (they find it again by
its session label). This stamp is the clock they share, so one process's idle
expiry can tell whether another process still uses the sandbox before deleting
it. Daytona's own ``last_activity_at`` is not enough on its own: a live probe
(2026-10-06) saw it lag real toolbox activity by over 100 seconds.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_KEY = "sandbox:last_access:{}"

# Keep a stamp well past any idle TTL, so a process that reaps late (an API
# process only reaps when it opens another session) still finds it.
_KEY_TTL_SECONDS = 24 * 60 * 60

# After a Redis failure, skip it for this long: an outage must not add a
# connect timeout to every sandbox op.
_BACKOFF_SECONDS = 30.0


def _default_redis():
    from docsgpt.cache import get_redis_instance

    return get_redis_instance()


class SharedActivity:
    """Reads and writes the shared last-use stamp of sandbox sessions (best-effort)."""

    def __init__(self, redis_getter: Callable[[], object] = _default_redis) -> None:
        """Use the Redis client ``redis_getter`` returns (None when Redis is not configured)."""
        self._redis_getter = redis_getter
        self._down_until = 0.0

    def _client(self) -> Optional[object]:
        """The Redis client, or None while backing off after a failure."""
        if time.monotonic() < self._down_until:
            return None
        return self._redis_getter()

    def _failed(self, what: str, session_id: str, exc: Exception) -> None:
        """Log a Redis failure and back off for ``_BACKOFF_SECONDS``."""
        self._down_until = time.monotonic() + _BACKOFF_SECONDS
        logger.warning(
            "sandbox activity: %s %s failed; skipping Redis for %ds: %s", what, session_id, int(_BACKOFF_SECONDS), exc
        )

    def touch(self, session_id: str) -> None:
        """Record that this process used ``session_id`` now; never raises."""
        try:
            client = self._client()
            if client is not None:
                client.set(_KEY.format(session_id), repr(time.time()), ex=_KEY_TTL_SECONDS)
        except Exception as exc:  # noqa: BLE001 - a missed stamp must never fail a sandbox op
            self._failed("recording use of", session_id, exc)

    def idle_seconds(self, session_id: str) -> Optional[float]:
        """Seconds since any process last used ``session_id``; None when unknown.

        Unknown means Redis is unavailable, or no stamp exists (never written, or
        older than a day); the caller must then not treat the session as idle.
        """
        try:
            client = self._client()
            raw = client.get(_KEY.format(session_id)) if client is not None else None
        except Exception as exc:  # noqa: BLE001 - unreadable means unknown
            self._failed("reading", session_id, exc)
            return None
        if raw is None:
            return None
        try:
            stamp = float(raw.decode() if isinstance(raw, bytes) else raw)
        except (TypeError, ValueError):
            return None
        return max(0.0, time.time() - stamp)


_instance: Optional[SharedActivity] = None
_instance_lock = threading.Lock()


def shared_activity() -> SharedActivity:
    """The process-wide ``SharedActivity`` (one Redis backoff per process)."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SharedActivity()
        return _instance
