"""The beat scheduler: RedBeat, kept running when its Redis lock or Redis itself goes away.

RedBeat lets one beat schedule at a time through a lock in Redis that expires after
``redbeat_lock_timeout`` seconds unless each tick extends it. Three things stopped it for good:

* A tick after the process was paused past that timeout (a Mac that slept) fails to extend the
  expired lock, the error ends the beat loop, and the worker carries on with no scheduler.
* At startup RedBeat waits for the lock in ``beat_init``, polling every ``max_interval`` (300 s),
  so a lock left by a beat that died kept a restarted one idle for up to five minutes.
* Redis not answering yet when beat starts (a login where the worker comes up first) ends it.

Here the lock is taken without waiting, on the tick: a beat without it stands by and tries again
every :func:`standby_seconds`, and one that loses it takes it back unless another beat has.

RedBeat also oversleeps. A tick sleeps until the soonest of the entries it read: those due by their
score, plus one entry it peeks at after them. When that one entry turns out to be due as well, it is
sent, and only the sent entries' own intervals are left. Two 5-minute tasks sent together then put beat
to sleep for 300 s while the 30 s tasks wait, which is also longer than the lock lives. So each tick's
sleep is cut to the due time of the next entry the tick did not read, read back from Redis after it.
"""

import logging
import time
from typing import Callable

from celery.signals import beat_init
from redbeat.schedulers import LUA_EXTEND_TO_SCRIPT, RedBeatScheduler, acquire_distributed_beat_lock, get_redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import LockError, MasterDownError, ReadOnlyError
from redis.exceptions import TimeoutError as RedisTimeoutError

logger = logging.getLogger("celery.beat")

# The lock is taken on the first tick instead, without blocking the beat loop.
beat_init.disconnect(acquire_distributed_beat_lock)

# Redis down, slow, still loading its data (BusyLoadingError is a ConnectionError), a replica
# answering READONLY during a failover, or one that lost its primary (MASTERDOWN): all pass, so beat
# waits them out.
REDIS_UNAVAILABLE = (RedisConnectionError, RedisTimeoutError, ReadOnlyError, MasterDownError)
#: Longest wait between attempts to reach Redis while beat starts.
STARTUP_RETRY_MAX_SECONDS = 30


def standby_seconds(lock_timeout: float, max_interval: float) -> float:
    """How long a beat without the lock waits before trying for it again: a sixth of its timeout."""
    return max(1.0, min(float(max_interval), lock_timeout / 6))


class DocsGPTScheduler(RedBeatScheduler):
    """RedBeat that takes its lock without blocking and survives losing it or Redis."""

    #: Whether this beat holds the lock; schedules only while it does.
    holding_lock = False
    #: Replaced in tests.
    sleep: Callable[[float], None] = staticmethod(time.sleep)

    def setup_schedule(self) -> None:
        """Store the static entries in Redis, waiting for Redis rather than failing when it is not up yet."""
        wait = 1
        while True:
            try:
                super().setup_schedule()
                return
            except REDIS_UNAVAILABLE as exc:
                logger.warning("beat: Redis is not reachable yet (%s); retrying in %ss", exc, wait)
                self.sleep(wait)
                wait = min(wait * 2, STARTUP_RETRY_MAX_SECONDS)

    def tick(self, min=min, **kwargs) -> float:
        """Send the due tasks while holding the lock; otherwise wait and try for it again."""
        if not self.lock_key:
            return super().tick(min=min, **kwargs)
        standby = standby_seconds(self.lock_timeout, self.max_interval)
        try:
            if not self._hold_lock():
                return standby
            started = self.app.now().timestamp()
            return self._until_next_entry(super().tick(min=min, **kwargs), started)
        except LockError:
            # Lost between the check and RedBeat's own extend; the next tick takes it back.
            self.holding_lock = False
            return standby
        except REDIS_UNAVAILABLE as exc:
            logger.warning("beat: Redis is not reachable (%s); retrying in %ss", exc, standby)
            return standby

    def _until_next_entry(self, interval: float, started: float) -> float:
        """``interval``, cut to the time left until the next entry in Redis is due.

        Scores are whole seconds. RedBeat's tick read every entry scored up to the second it ``started``
        in, so only later scores count; an entry it read there but found not due yet is in ``interval``.
        Sending can take long enough to cross into a later second, and an entry scored there was not read
        (RedBeat peeks at one entry only). Its wait is then 0, so beat ticks again at once and reads it as
        due; that tick started in its second, so the entry is not counted again. Waking on a score is at
        most a second early, and the tick after that sleeps the rest.

        Args:
            interval: The sleep RedBeat's tick asked for.
            started: When the tick started, as a UNIX timestamp.

        Returns:
            The seconds to sleep: ``interval``, or less when an entry is due sooner.
        """
        following = get_redis(self.app).zrangebyscore(
            self.app.redbeat_conf.schedule_key, f"({int(started)}", "+inf", start=0, num=1, withscores=True
        )
        if not following:
            return interval
        return min(interval, max(0.0, following[0][1] - self.app.now().timestamp()))

    def _hold_lock(self) -> bool:
        """Extend the lock this beat holds, or take it when free; False while another beat has it."""
        if self.holding_lock:
            try:
                self.lock.extend(int(self.lock_timeout))
                return True
            except LockError:
                self.holding_lock = False
                logger.warning(
                    "beat: Lost the scheduler lock: this process was paused for longer than its %ss timeout, "
                    "as when the machine sleeps. Taking it back unless another scheduler has.",
                    self.lock_timeout,
                )
        if self.lock is None:
            self.lock = self._new_lock()
        if self.lock.acquire(blocking=False):
            self.holding_lock = True
            logger.info("beat: Acquired lock")
        return self.holding_lock

    def _new_lock(self):
        """The Redis lock RedBeat would make, whose extend sets the expiry instead of adding to it."""
        client = get_redis(self.app)
        lock = client.lock(self.lock_key, timeout=self.lock_timeout)
        lock.lua_extend = client.register_script(LUA_EXTEND_TO_SCRIPT)
        return lock
