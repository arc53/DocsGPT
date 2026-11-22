"""The OCR request limiter: slots shared through Redis, AIMD adaptation, the per-process fallback."""

import threading
import time

import pytest

from docsgpt.parser.file import ocr_limiter as ol


class FakeRedis:
    """The handful of Redis commands the limiter sends, in memory and thread-safe."""

    def __init__(self):
        self.lock = threading.RLock()
        self.zsets = {}
        self.values = {}

    def zremrangebyscore(self, key, low, high):
        with self.lock:
            zset = self.zsets.setdefault(key, {})
            gone = [m for m, score in zset.items() if score <= float(high)]
            for member in gone:
                del zset[member]
            return len(gone)

    def zadd(self, key, mapping, xx=False):
        with self.lock:
            zset = self.zsets.setdefault(key, {})
            if xx:
                mapping = {member: score for member, score in mapping.items() if member in zset}
            zset.update(mapping)
            return len(mapping)

    def zcard(self, key):
        with self.lock:
            return len(self.zsets.get(key, {}))

    def zrem(self, key, member):
        with self.lock:
            return 1 if self.zsets.get(key, {}).pop(member, None) is not None else 0

    def expire(self, key, seconds):
        return True

    def get(self, key):
        with self.lock:
            value = self.values.get(key)
            return None if value is None else str(value).encode()

    def set(self, key, value, ex=None):
        with self.lock:
            self.values[key] = value
            return True

    def incr(self, key):
        with self.lock:
            self.values[key] = int(self.values.get(key) or 0) + 1
            return self.values[key]

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def transaction(self, func, *watches):
        # WATCH ... MULTI/EXEC: the reads and the queued writes run with nothing in between.
        with self.lock:
            pipe = FakeWatchPipeline(self)
            func(pipe)
            return pipe.execute()


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.calls = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return queue

    def execute(self):
        with self.redis.lock:  # MULTI/EXEC: nothing interleaves
            return [getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.calls]


class FakeWatchPipeline(FakePipeline):
    """Commands run at once until ``multi()``, then queue, as a WATCHed redis-py pipeline does."""

    def __init__(self, redis):
        super().__init__(redis)
        self.queued = False

    def multi(self):
        self.queued = True

    def __getattr__(self, name):
        if not self.queued:
            return getattr(self.redis, name)
        return super().__getattr__(name)


class BrokenRedis:
    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise ConnectionError("redis is down")

        return fail


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(ol, "_redis_client", lambda: redis)
    return redis


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(ol, "_sleep", lambda seconds: time.sleep(0.001))


def _hammer(limiters, per_limiter_threads=6, rounds=5):
    """Send requests through ``limiters`` from many threads; returns the peak in flight seen.

    Fails the test when a thread raised or never finished, or fewer requests completed than were sent.
    """
    state = {"in_flight": 0, "peak": 0, "done": 0}
    errors = []
    lock = threading.Lock()

    def request(limiter):
        try:
            for _ in range(rounds):
                with limiter.slot():
                    with lock:
                        state["in_flight"] += 1
                        state["peak"] = max(state["peak"], state["in_flight"])
                    time.sleep(0.002)
                    with lock:
                        state["in_flight"] -= 1
                        state["done"] += 1
        except BaseException as err:  # noqa: BLE001 - reported by the test
            errors.append(err)

    threads = [
        threading.Thread(target=request, args=(limiter,)) for limiter in limiters for _ in range(per_limiter_threads)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert not any(thread.is_alive() for thread in threads), "a request never finished"
    assert state["done"] == len(threads) * rounds
    return state["peak"]


@pytest.mark.unit
class TestSharedSlots:
    def test_two_limiters_sharing_redis_never_exceed_the_cap(self, fake_redis, no_wait):
        # Two processes' limiters for one endpoint: same key, separate objects.
        first = ol.InFlightLimiter("k", cap=3, lease_seconds=60)
        second = ol.InFlightLimiter("k", cap=3, lease_seconds=60)

        peak = _hammer([first, second])

        assert 1 <= peak <= 3
        assert fake_redis.zcard("k:leases") == 0  # every slot was given back

    def test_a_dead_holders_lease_lapses(self, fake_redis, no_wait, monkeypatch):
        clock = [1000.0]
        monkeypatch.setattr(ol, "_now", lambda: clock[0])
        limiter = ol.InFlightLimiter("k", cap=1, lease_seconds=30)
        assert limiter._try_redis_slot(fake_redis) is not None  # taken, never released
        assert limiter._try_redis_slot(fake_redis) is None
        clock[0] += 31
        assert limiter._try_redis_slot(fake_redis) is not None

    def test_limiter_for_shares_one_limiter_per_endpoint(self):
        a = ol.limiter_for("deepseek", "http://x", 60, cap=4)
        assert ol.limiter_for("deepseek", "http://x", 60, cap=4) is a
        assert ol.limiter_for("deepseek", "http://y", 60, cap=4) is not a


@pytest.mark.unit
class TestAdaptation:
    def test_429_halves_and_clean_responses_raise_it_again(self, fake_redis):
        limiter = ol.InFlightLimiter("k", cap=8, lease_seconds=60)
        assert limiter.allowed() == 8
        assert limiter.record_rate_limited() == 4
        assert limiter.record_rate_limited() == 2
        assert limiter.record_rate_limited() == 1
        assert limiter.record_rate_limited() == 1  # never below one
        for _ in range(ol.CLEAN_RUN_TO_GROW):
            limiter.record_success()
        assert limiter.allowed() == 2

    def test_never_grows_above_the_cap(self, fake_redis):
        limiter = ol.InFlightLimiter("k", cap=2, lease_seconds=60)
        for _ in range(ol.CLEAN_RUN_TO_GROW * 5):
            limiter.record_success()
        assert limiter.allowed() == 2

    def test_halving_is_seen_by_the_other_process(self, fake_redis):
        first = ol.InFlightLimiter("k", cap=8, lease_seconds=60)
        second = ol.InFlightLimiter("k", cap=8, lease_seconds=60)
        first.record_rate_limited()
        assert second.allowed() == 4

    def test_halved_limit_holds_slots_down(self, fake_redis):
        limiter = ol.InFlightLimiter("k", cap=4, lease_seconds=60)
        limiter.record_rate_limited()  # 2
        assert limiter._try_redis_slot(fake_redis)
        assert limiter._try_redis_slot(fake_redis)
        assert limiter._try_redis_slot(fake_redis) is None


@pytest.mark.unit
class TestWithoutRedis:
    def test_per_process_limit_still_applies(self, monkeypatch, no_wait):
        monkeypatch.setattr(ol, "_redis_client", lambda: None)
        limiter = ol.InFlightLimiter("k", cap=2, lease_seconds=60)
        assert _hammer([limiter]) <= 2

    def test_per_process_adaptation(self, monkeypatch):
        monkeypatch.setattr(ol, "_redis_client", lambda: None)
        limiter = ol.InFlightLimiter("k", cap=6, lease_seconds=60)
        assert limiter.record_rate_limited() == 3
        for _ in range(ol.CLEAN_RUN_TO_GROW):
            limiter.record_success()
        assert limiter.allowed() == 4

    def test_a_failing_redis_falls_back_to_the_process(self, monkeypatch, no_wait):
        monkeypatch.setattr(ol, "_redis_client", lambda: BrokenRedis())
        limiter = ol.InFlightLimiter("k", cap=2, lease_seconds=60)
        assert _hammer([limiter]) <= 2
        assert limiter.record_rate_limited() == 1


class TestReviewFixes:
    def test_two_429s_at_once_halve_twice(self, fake_redis):
        limiter = ol.InFlightLimiter("k", cap=8, lease_seconds=60)
        threads = [threading.Thread(target=limiter.record_rate_limited) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert limiter.allowed() == 2

    def test_a_lease_whose_count_cannot_be_read_is_taken_back(self, fake_redis, monkeypatch):
        limiter = ol.InFlightLimiter("k", cap=1, lease_seconds=60)
        monkeypatch.setattr(limiter, "_redis_allowed", lambda client: (_ for _ in ()).throw(ConnectionError("x")))
        with pytest.raises(ConnectionError):
            limiter._try_redis_slot(fake_redis)
        assert fake_redis.zcard(limiter._leases) == 0

    def test_a_slow_request_keeps_its_lease(self, fake_redis, monkeypatch):
        clock = {"now": 1000.0}
        monkeypatch.setattr(ol, "_now", lambda: clock["now"])
        limiter = ol.InFlightLimiter("k", cap=1, lease_seconds=3)
        with limiter.slot():
            [lease] = fake_redis.zsets[limiter._leases]
            clock["now"] += 2.5
            deadline = time.time() + 3
            while fake_redis.zsets[limiter._leases][lease] < clock["now"] + 2 and time.time() < deadline:
                time.sleep(0.05)
            assert fake_redis.zsets[limiter._leases][lease] >= clock["now"] + 2
        assert fake_redis.zcard(limiter._leases) == 0
