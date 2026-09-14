"""Tests for the async Redis client behind the event-loop routes.

Each open event-loop stream (a notification tab, a chat reconnect, a device
session) holds one pooled connection for its whole life. redis-py's pool
defaults to 100 connections, which one worker outgrows long before its event
loop does, so the pool size must come from settings.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import docsgpt.streaming.async_redis as async_redis
from docsgpt.core.settings import Settings

_FROM_URL = "docsgpt.streaming.async_redis.aioredis.Redis.from_url"


@pytest.fixture(autouse=True)
def _reset_singleton():
    async_redis._async_redis = None
    async_redis._creation_failed = False
    yield
    async_redis._async_redis = None
    async_redis._creation_failed = False


@pytest.mark.unit
@pytest.mark.asyncio
class TestGetAsyncRedisInstance:
    async def test_pool_sized_from_settings(self, monkeypatch):
        monkeypatch.setattr(async_redis.settings, "ASYNC_REDIS_MAX_CONNECTIONS", 4321)
        with patch(_FROM_URL) as from_url:
            client = await async_redis.get_async_redis_instance()
        assert client is from_url.return_value
        kwargs = from_url.call_args.kwargs
        assert kwargs["max_connections"] == 4321
        assert kwargs["socket_connect_timeout"] == 2
        assert kwargs["health_check_interval"] == 10

    async def test_real_client_pool_honours_setting(self, monkeypatch):
        # from_url connects lazily, so this never opens a socket.
        monkeypatch.setattr(async_redis.settings, "ASYNC_REDIS_MAX_CONNECTIONS", 777)
        monkeypatch.setattr(async_redis.settings, "CACHE_REDIS_URL", "redis://127.0.0.1:1/0")
        client = await async_redis.get_async_redis_instance()
        try:
            assert client.connection_pool.max_connections == 777
        finally:
            await client.aclose()

    async def test_default_pool_outgrows_redis_py_default(self):
        assert Settings.model_fields["ASYNC_REDIS_MAX_CONNECTIONS"].default > 100

    async def test_singleton(self):
        with patch(_FROM_URL) as from_url:
            first = await async_redis.get_async_redis_instance()
            second = await async_redis.get_async_redis_instance()
        assert first is second
        assert from_url.call_count == 1

    async def test_invalid_url_marks_failed_and_stops_retrying(self):
        with patch(_FROM_URL, side_effect=ValueError("bad url")) as from_url:
            assert await async_redis.get_async_redis_instance() is None
            assert await async_redis.get_async_redis_instance() is None
        assert from_url.call_count == 1
