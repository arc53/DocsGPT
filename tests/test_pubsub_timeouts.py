"""Tests for the pub/sub-dedicated Redis client and subscriber timeout handling.

Regression tests for the 2026-07-05→07 prod incident: idle pub/sub
connections silently dropped by NAT/IPVS never raised inside
``pubsub.get_message`` (the shared cache client has no ``socket_timeout``),
leaving each ``/api/events`` SSE generator blocked in ``_read_from_socket``
forever. One WSGI thread-pool slot leaked per dead subscriber until the
pool was exhausted and the worker stopped serving Flask requests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import redis as redis_lib

import application.cache as cache
from application.streaming.broadcast_channel import Topic


@pytest.fixture(autouse=True)
def _reset_pubsub_singleton():
    cache._pubsub_redis_instance = None
    cache._pubsub_redis_creation_failed = False
    yield
    cache._pubsub_redis_instance = None
    cache._pubsub_redis_creation_failed = False


class TestGetPubsubRedisInstance:

    @pytest.mark.unit
    def test_bounds_blocking_reads_and_enables_keepalive(self):
        with patch("application.cache.redis.Redis.from_url") as from_url:
            client = cache.get_pubsub_redis_instance()
        assert client is from_url.return_value
        kwargs = from_url.call_args.kwargs
        assert kwargs["socket_timeout"] == cache.PUBSUB_SOCKET_TIMEOUT_SECONDS
        assert kwargs["socket_timeout"] > 0
        assert kwargs["socket_keepalive"] is True
        assert kwargs["health_check_interval"] == 10

    @pytest.mark.unit
    def test_socket_timeout_exceeds_subscribe_poll_interval(self):
        """get_message(timeout=poll) waits ``poll`` seconds while healthy-idle;
        socket_timeout must be comfortably larger or idle polling would be
        misread as a dead connection."""
        assert cache.PUBSUB_SOCKET_TIMEOUT_SECONDS >= 5

    @pytest.mark.unit
    def test_singleton(self):
        with patch("application.cache.redis.Redis.from_url") as from_url:
            first = cache.get_pubsub_redis_instance()
            second = cache.get_pubsub_redis_instance()
        assert first is second
        assert from_url.call_count == 1

    @pytest.mark.unit
    def test_invalid_url_marks_failed_and_stops_retrying(self):
        with patch(
            "application.cache.redis.Redis.from_url", side_effect=ValueError("bad url")
        ):
            assert cache.get_pubsub_redis_instance() is None
        with patch("application.cache.redis.Redis.from_url") as from_url:
            assert cache.get_pubsub_redis_instance() is None
        from_url.assert_not_called()

    @pytest.mark.unit
    def test_connection_error_allows_retry(self):
        with patch(
            "application.cache.redis.Redis.from_url",
            side_effect=redis_lib.ConnectionError("down"),
        ):
            assert cache.get_pubsub_redis_instance() is None
        with patch("application.cache.redis.Redis.from_url") as from_url:
            assert cache.get_pubsub_redis_instance() is from_url.return_value


class TestSubscribeTimeout:

    @pytest.mark.unit
    def test_socket_timeout_ends_subscription(self):
        """A read timeout means the connection is half-open/dead: the generator
        must exit — freeing its WSGI thread — rather than loop or raise."""
        pubsub = MagicMock()
        pubsub.get_message.side_effect = redis_lib.exceptions.TimeoutError(
            "Timeout reading from socket"
        )
        client = MagicMock()
        client.pubsub.return_value = pubsub
        with patch(
            "application.streaming.broadcast_channel.get_pubsub_redis_instance",
            return_value=client,
        ):
            events = list(Topic("user:u1").subscribe())
        assert events == []
        pubsub.close.assert_called_once()

    @pytest.mark.unit
    def test_subscribe_uses_dedicated_pubsub_client(self):
        """The shared cache client has no socket_timeout; subscribers must not
        fall back to it."""
        pubsub = MagicMock()
        pubsub.get_message.side_effect = redis_lib.exceptions.TimeoutError()
        client = MagicMock()
        client.pubsub.return_value = pubsub
        with patch(
            "application.streaming.broadcast_channel.get_pubsub_redis_instance",
            return_value=client,
        ) as get_pubsub, patch(
            "application.streaming.broadcast_channel.get_redis_instance"
        ) as get_cache:
            list(Topic("user:u1").subscribe())
        get_pubsub.assert_called_once()
        get_cache.assert_not_called()
