"""Unit tests for the SSE connection gauge.

``measure_sse_connections`` counts the live members of the per-user
``user:*:sse_leases`` sorted sets that SSE streams hold; the Celery beat
task logs the snapshot as a structured ``sse_gauge`` event, so a log
backend can chart concurrent connected users over time.
"""

from __future__ import annotations

import logging

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.events.gauge import measure_sse_connections

NOW = 1_000_000.0
TTL = 60.0


def _client(keys, counts_per_batch):
    """Mock Redis whose pipeline returns one ZCOUNT result list per execute."""
    client = MagicMock()
    client.scan_iter.return_value = iter(keys)
    pipe = MagicMock()
    pipe.execute.side_effect = list(counts_per_batch)
    client.pipeline.return_value = pipe
    return client, pipe


@pytest.fixture(autouse=True)
def _no_broker_gauge():
    # The task also measures the Celery queues on the broker; these tests
    # cover the SSE half only and must not touch a local Redis.
    with patch("docsgpt.events.queue_gauge.broker_redis", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _frozen_clock():
    with patch("docsgpt.events.gauge.time.time", return_value=NOW), patch(
        "docsgpt.events.gauge.lease_ttl_seconds", return_value=TTL
    ):
        yield


@pytest.mark.unit
class TestMeasureSseConnections:
    def test_counts_users_and_sums_live_leases(self):
        client, pipe = _client(
            [b"user:alice:sse_leases", b"user:bob:sse_leases"], [[2, 1]]
        )
        snapshot = measure_sse_connections(client)
        assert snapshot == {"connected_users": 2, "connections": 3}
        client.scan_iter.assert_called_once_with(
            match="user:*:sse_leases", count=500
        )
        client.pipeline.assert_called_once_with(transaction=False)

    def test_counts_only_leases_refreshed_within_ttl(self):
        # A lease scored at or before now - ttl belongs to a stream that
        # died without cleanup; acquire prunes it, so the gauge must not
        # count it either. Exclusive lower bound, open upper bound.
        client, pipe = _client([b"user:alice:sse_leases"], [[1]])
        measure_sse_connections(client)
        pipe.zcount.assert_called_once_with(
            b"user:alice:sse_leases", f"({NOW - TTL}", "+inf"
        )

    def test_skips_keys_with_no_live_leases(self):
        # Every lease stale, or the key expired between SCAN and ZCOUNT:
        # ZCOUNT returns 0 and the user is not connected.
        client, _ = _client(
            [
                b"user:alice:sse_leases",
                b"user:bob:sse_leases",
                b"user:carol:sse_leases",
            ],
            [[0, 0, 3]],
        )
        snapshot = measure_sse_connections(client)
        assert snapshot == {"connected_users": 1, "connections": 3}

    def test_empty_scan_reports_zero_without_pipeline(self):
        client, _ = _client([], [])
        snapshot = measure_sse_connections(client)
        assert snapshot == {"connected_users": 0, "connections": 0}
        client.pipeline.assert_not_called()

    def test_batches_zcount_pipelines(self):
        keys = [f"user:u{i}:sse_leases".encode() for i in range(1200)]
        client, pipe = _client(keys, [[1] * 500, [1] * 500, [1] * 200])
        snapshot = measure_sse_connections(client)
        assert snapshot == {"connected_users": 1200, "connections": 1200}
        assert pipe.execute.call_count == 3  # 500 + 500 + 200

    def test_against_redis_lease_sets(self):
        # Real sorted-set semantics: the ZCOUNT bound syntax and the
        # key pattern must match what acquire_stream_lease writes.
        fakeredis = pytest.importorskip("fakeredis")
        from docsgpt.events.keys import connection_leases_key

        client = fakeredis.FakeRedis()
        client.zadd(
            connection_leases_key("alice"), {"a1": NOW - 5, "a2": NOW - 30}
        )
        # Scored exactly at the TTL edge: acquire prunes it, so it is dead.
        client.zadd(connection_leases_key("bob"), {"b1": NOW - TTL})
        client.zadd(connection_leases_key("carol"), {"c1": NOW - 1})
        client.set("user:dave:stream", "unrelated")

        snapshot = measure_sse_connections(client)
        assert snapshot == {"connected_users": 2, "connections": 3}


@pytest.mark.unit
class TestSseGaugeTask:
    @patch("docsgpt.cache.get_redis_instance")
    def test_logs_structured_gauge_event(self, mock_get_redis, caplog):
        client, _ = _client([b"user:alice:sse_leases"], [[2]])
        mock_get_redis.return_value = client
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        assert result == {"connected_users": 1, "connections": 2}
        gauge_records = [r for r in caplog.records if r.msg == "sse_gauge"]
        assert len(gauge_records) == 1
        assert gauge_records[0].connected_users == 1
        assert gauge_records[0].connections == 2

    @patch("docsgpt.cache.get_redis_instance")
    def test_zero_connections_still_logs(self, mock_get_redis, caplog):
        # The chart needs continuous data; an idle fleet is a data point,
        # not a skip.
        client, _ = _client([], [])
        mock_get_redis.return_value = client
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        assert result == {"connected_users": 0, "connections": 0}
        assert any(r.msg == "sse_gauge" for r in caplog.records)

    @patch("docsgpt.cache.get_redis_instance")
    def test_redis_unavailable_skips_quietly(self, mock_get_redis, caplog):
        mock_get_redis.return_value = None
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        assert result == {"skipped": "redis unavailable"}
        assert not any(r.msg == "sse_gauge" for r in caplog.records)

    @patch("docsgpt.cache.get_redis_instance")
    def test_redis_error_does_not_raise(self, mock_get_redis, caplog):
        client = MagicMock()
        client.scan_iter.side_effect = RuntimeError("connection reset")
        mock_get_redis.return_value = client
        from docsgpt.api.user.tasks import sse_connections_gauge_task

        with caplog.at_level(logging.INFO):
            result = sse_connections_gauge_task()

        assert result == {"skipped": "redis error"}
        assert not any(r.msg == "sse_gauge" for r in caplog.records)
