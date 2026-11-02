"""Unit tests for the Celery queue gauge.

``measure_celery_queues`` reads the broker's Redis lists the way kombu writes
them (``LPUSH`` on publish, ``BRPOP`` on consume, one list per priority step),
and the per-queue sets of running tasks that workers keep fresh. The beat task
adds the result to its ``sse_gauge`` event, so the ingest-lane backlog and how
long its head-of-line task has waited show up next to the SSE numbers.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from docsgpt.core.settings import settings
from docsgpt.events import queue_gauge
from docsgpt.events.queue_gauge import head_key, measure_celery_queues

SEP = "\x06\x16"


class FakeRedis:
    """The handful of list, hash, string and sorted-set commands the gauge uses.

    fakeredis is not a test dependency, so a tiny stand-in keeps these tests
    running in CI. Values are stored as bytes, like redis-py returns them.
    """

    def __init__(self):
        self.lists: dict = {}
        self.hashes: dict = {}
        self.strings: dict = {}
        self.zsets: dict = {}

    @staticmethod
    def _b(value):
        return value if isinstance(value, bytes) else str(value).encode()

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, self._b(value))

    def rpop(self, key):
        items = self.lists.get(key) or []
        return items.pop() if items else None

    def llen(self, key):
        return len(self.lists.get(key, []))

    def lindex(self, key, index):
        items = self.lists.get(key, [])
        try:
            return items[index]
        except IndexError:
            return None

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = self._b(value)

    def hlen(self, key):
        return len(self.hashes.get(key, {}))

    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())

    def get(self, key):
        return self.strings.get(key)

    def set(self, key, value, ex=None):
        self.strings[key] = self._b(value)

    def delete(self, key):
        self.strings.pop(key, None)

    def scan_iter(self, match=None, count=None):
        return iter(())

    def zadd(self, key, mapping):
        zset = self.zsets.setdefault(key, {})
        for member, score in mapping.items():
            zset[self._b(member)] = float(score)

    def zrem(self, key, member):
        self.zsets.get(key, {}).pop(self._b(member), None)

    def zremrangebyscore(self, key, low, high):
        zset = self.zsets.get(key, {})
        low = float("-inf") if low == "-inf" else float(low)
        high = float("inf") if high == "+inf" else float(high)
        for member in [m for m, score in zset.items() if low <= score <= high]:
            del zset[member]

    def zcard(self, key):
        return len(self.zsets.get(key, {}))

    def expire(self, key, seconds):
        return True

    def pipeline(self, transaction=True):
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, client):
        self.client = client
        self.calls: list = []

    def __getattr__(self, name):
        def queue_call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self

        return queue_call

    def execute(self):
        results = [getattr(self.client, name)(*args, **kwargs) for name, args, kwargs in self.calls]
        self.calls = []
        return results


def _message(task_id: str, queue: str = "ingest") -> str:
    """A kombu Redis-transport payload carrying a Celery protocol-2 task."""
    return json.dumps(
        {
            "body": "W10=",
            "headers": {"id": task_id, "task": "docsgpt.api.user.tasks.ingest"},
            "properties": {"delivery_info": {"exchange": queue, "routing_key": queue}},
        }
    )


def _publish(client, queue: str, task_id: str, priority: int = 0) -> None:
    key = queue if not priority else f"{queue}{SEP}{priority}"
    client.lpush(key, _message(task_id, queue))


@pytest.fixture
def client():
    return FakeRedis()


@pytest.mark.unit
class TestMeasureCeleryQueues:
    def test_depth_sums_every_priority_list(self, client):
        _publish(client, "ingest", "a")
        _publish(client, "ingest", "b")
        _publish(client, "ingest", "c", priority=6)
        snapshot = measure_celery_queues(client, ["ingest", "docsgpt"], now=1000.0)
        assert snapshot["ingest"]["depth"] == 3
        assert snapshot["docsgpt"] == {"depth": 0, "wait_s": 0, "in_flight": 0}

    def test_wait_grows_while_the_same_task_heads_the_queue(self, client):
        _publish(client, "ingest", "oldest")
        _publish(client, "ingest", "newer")
        assert measure_celery_queues(client, ["ingest"], now=1000.0)["ingest"]["wait_s"] == 0
        assert measure_celery_queues(client, ["ingest"], now=1120.0)["ingest"]["wait_s"] == 120

    def test_wait_resets_when_the_head_moves(self, client):
        _publish(client, "ingest", "oldest")
        _publish(client, "ingest", "newer")
        measure_celery_queues(client, ["ingest"], now=1000.0)
        client.rpop("ingest")  # a worker took "oldest"
        assert measure_celery_queues(client, ["ingest"], now=1060.0)["ingest"]["wait_s"] == 0
        assert measure_celery_queues(client, ["ingest"], now=1180.0)["ingest"]["wait_s"] == 120

    def test_the_default_priority_list_heads_the_queue(self, client):
        # kombu consumes the plain list before the priority-suffixed ones.
        _publish(client, "ingest", "low", priority=9)
        _publish(client, "ingest", "default")
        measure_celery_queues(client, ["ingest"], now=1000.0)
        assert json.loads(client.get(head_key("ingest")))["id"] == "default"

    def test_an_emptied_queue_forgets_its_head(self, client):
        _publish(client, "ingest", "only")
        measure_celery_queues(client, ["ingest"], now=1000.0)
        client.rpop("ingest")
        assert measure_celery_queues(client, ["ingest"], now=1300.0)["ingest"]["wait_s"] == 0
        assert client.get(head_key("ingest")) is None

    def test_unparseable_payloads_still_count(self, client):
        client.lpush("ingest", b"\xff not json")
        snapshot = measure_celery_queues(client, ["ingest"], now=1000.0)
        assert snapshot["ingest"]["depth"] == 1
        # The same raw payload heading the queue is still "the same head".
        assert measure_celery_queues(client, ["ingest"], now=1090.0)["ingest"]["wait_s"] == 90


@pytest.fixture
def tracked(client):
    """Point the worker-side in-flight tracking at ``client``, without its renewal thread."""
    with patch.object(queue_gauge, "broker_redis", return_value=client), patch.object(
        queue_gauge, "_ensure_renewer"
    ), patch.dict(queue_gauge._running, clear=True):
        yield client


@pytest.mark.unit
class TestInFlight:
    def test_running_tasks_count_by_queue(self, tracked):
        for task_id, queue in (("t1", "ingest"), ("t2", "ingest"), ("t3", "docsgpt")):
            queue_gauge.task_started(task_id, queue, now=1000.0)
        snapshot = measure_celery_queues(tracked, ["ingest", "docsgpt", "parsing"], now=1010.0)
        assert snapshot["ingest"]["in_flight"] == 2
        assert snapshot["docsgpt"]["in_flight"] == 1
        assert snapshot["parsing"] == {"depth": 0, "wait_s": 0, "in_flight": 0}

    def test_a_task_running_past_the_visibility_timeout_still_counts(self, tracked):
        timeout = settings.CELERY_VISIBILITY_TIMEOUT
        queue_gauge.task_started("long-ingest", "ingest", now=0.0)
        renew_every = queue_gauge.IN_FLIGHT_RENEW_SECONDS
        for tick in range(renew_every, timeout + 600, renew_every):
            queue_gauge.renew_in_flight(now=float(tick))
        # kombu has restored the message by now, so the unacked hash no longer holds it.
        assert tracked.hlen("unacked") == 0
        snapshot = measure_celery_queues(tracked, ["ingest"], now=float(timeout + 600))
        assert snapshot["ingest"]["in_flight"] == 1

    def test_a_finished_task_stops_counting(self, tracked):
        queue_gauge.task_started("t1", "ingest", now=1000.0)
        queue_gauge.task_finished("t1")
        assert measure_celery_queues(tracked, ["ingest"], now=1001.0)["ingest"]["in_flight"] == 0
        assert queue_gauge._running == {}

    def test_a_task_whose_worker_died_drops_out_after_the_ttl(self, tracked):
        queue_gauge.task_started("t1", "ingest", now=1000.0)
        # No renewal: the worker was killed before its next heartbeat.
        expired = 1000.0 + queue_gauge.IN_FLIGHT_TTL_SECONDS + 1
        assert measure_celery_queues(tracked, ["ingest"], now=expired)["ingest"]["in_flight"] == 0

    def test_renewal_covers_only_tasks_still_running(self, tracked):
        queue_gauge.task_started("done", "ingest", now=1000.0)
        queue_gauge.task_started("running", "ingest", now=1000.0)
        queue_gauge.task_finished("done")
        queue_gauge.renew_in_flight(now=1060.0)
        assert set(tracked.zsets[queue_gauge.in_flight_key("ingest")]) == {b"running"}

    def test_no_redis_broker_tracks_nothing(self, client):
        with patch.object(queue_gauge, "broker_redis", return_value=None), patch.dict(
            queue_gauge._running, clear=True
        ):
            queue_gauge.task_started("t1", "ingest")
            queue_gauge.renew_in_flight()
            queue_gauge.task_finished("t1")
            assert queue_gauge._running == {}


@pytest.mark.unit
class TestInFlightSignals:
    @staticmethod
    def _task(routing_key=None, is_eager=False):
        task = MagicMock()
        task.request.delivery_info = {"routing_key": routing_key} if routing_key else None
        task.request.is_eager = is_eager
        return task

    def test_a_worker_task_is_tracked_under_its_queue(self, tracked):
        from docsgpt import celery_init

        celery_init._track_in_flight(task_id="t1", task=self._task("ingest"))
        assert queue_gauge._running == {"t1": "ingest"}
        celery_init._untrack_in_flight(task_id="t1")
        assert queue_gauge._running == {}

    def test_an_eager_or_unrouted_task_is_not_tracked(self, tracked):
        from docsgpt import celery_init

        celery_init._track_in_flight(task_id="t1", task=self._task("ingest", is_eager=True))
        celery_init._track_in_flight(task_id="t2", task=self._task(None))
        assert queue_gauge._running == {}

    def test_a_redis_error_never_fails_the_task(self, client):
        from docsgpt import celery_init

        broken = MagicMock()
        broken.zadd.side_effect = ConnectionError("broker down")
        broken.zrem.side_effect = ConnectionError("broker down")
        with patch.object(queue_gauge, "broker_redis", return_value=broken), patch.object(
            queue_gauge, "_ensure_renewer"
        ), patch.dict(queue_gauge._running, clear=True):
            celery_init._track_in_flight(task_id="t1", task=self._task("ingest"))
            celery_init._untrack_in_flight(task_id="t1")


@pytest.mark.unit
class TestBrokerRedis:
    @pytest.fixture(autouse=True)
    def _fresh_client(self):
        queue_gauge._broker_client = None
        yield
        queue_gauge._broker_client = None

    def test_non_redis_broker_has_no_queue_gauge(self):
        with patch.object(queue_gauge.settings, "CELERY_BROKER_URL", "amqp://guest@localhost//"):
            assert queue_gauge.broker_redis() is None

    def test_redis_broker_gets_a_client_with_socket_timeouts(self):
        with patch.object(queue_gauge.settings, "CELERY_BROKER_URL", "redis://localhost:6379/3"):
            client = queue_gauge.broker_redis()
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["db"] == 3
        assert kwargs["socket_timeout"] and kwargs["socket_connect_timeout"]


@pytest.mark.unit
class TestGaugeTaskQueueAttributes:
    @patch("docsgpt.events.queue_gauge.broker_redis")
    @patch("docsgpt.cache.get_redis_instance")
    def test_queue_numbers_ride_on_the_sse_gauge_event(self, mock_cache, mock_broker, caplog):
        broker = FakeRedis()
        _publish(broker, "ingest", "a")
        _publish(broker, "ingest", "b")
        mock_cache.return_value = FakeRedis()
        mock_broker.return_value = broker
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        record = next(r for r in caplog.records if r.msg == "sse_gauge")
        assert record.connections == 0
        assert record.queue_ingest_depth == 2
        assert record.queue_ingest_wait_s == 0
        assert record.queue_docsgpt_depth == 0
        assert result["queues"]["ingest"]["depth"] == 2

    @patch("docsgpt.events.queue_gauge.broker_redis")
    @patch("docsgpt.cache.get_redis_instance")
    def test_broker_errors_never_drop_the_sse_numbers(self, mock_cache, mock_broker, caplog):
        mock_cache.return_value = FakeRedis()
        mock_broker.return_value.pipeline.side_effect = ConnectionError("broker down")
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        record = next(r for r in caplog.records if r.msg == "sse_gauge")
        assert record.connections == 0
        assert not hasattr(record, "queue_ingest_depth")
        assert "queues" not in result

    @patch("docsgpt.events.queue_gauge.broker_redis")
    @patch("docsgpt.cache.get_redis_instance")
    def test_every_declared_queue_is_reported_even_when_empty(self, mock_cache, mock_broker):
        from docsgpt.api.user.tasks import sse_connections_gauge_task
        from docsgpt.celeryconfig import task_queues

        mock_cache.return_value = FakeRedis()
        mock_broker.return_value = FakeRedis()

        result = sse_connections_gauge_task()

        assert set(result["queues"]) == {queue.name for queue in task_queues}
        for metrics in result["queues"].values():
            assert metrics == {"depth": 0, "wait_s": 0, "in_flight": 0}

    @patch("docsgpt.events.queue_gauge.broker_redis", return_value=None)
    @patch("docsgpt.cache.get_redis_instance")
    def test_no_broker_client_keeps_the_old_event(self, mock_cache, _mock_broker, caplog):
        mock_cache.return_value = FakeRedis()
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        assert result == {"connected_users": 0, "connections": 0}
