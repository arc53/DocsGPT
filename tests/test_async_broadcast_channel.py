"""Tests for ``AsyncTopic.subscribe``'s liveness probe.

A pub/sub socket that NAT/IPVS dropped silently never errors: ``get_message``
keeps timing out exactly as if the channel were idle. The sync subscriber
bounds this with ``socket_timeout`` (see tests/test_pubsub_timeouts.py). The
async subscriber sends a PING after a quiet spell and ends the subscription
when nothing comes back, so the SSE client reconnects and replays from its
cursor instead of silently missing events.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from docsgpt.streaming.async_broadcast_channel import AsyncTopic

_AREDIS = "docsgpt.streaming.async_broadcast_channel.get_async_redis_instance"

IDLE = object()


class _FakePubSub:
    """Scripted ``redis.asyncio`` pubsub.

    ``script`` entries are message dicts (returned at once) or ``IDLE`` (a
    ``get_message`` poll that times out). After the script, every poll is idle.
    A PING queues a pong reply unless ``answer_pings`` is off.
    """

    def __init__(self, script=(), *, answer_pings=True, ping_error=None):
        self._script = [{"type": "subscribe", "channel": b"t", "data": 1}, *script]
        self.answer_pings = answer_pings
        self.ping_error = ping_error
        self.pings = 0
        self._pong_pending = False
        self.unsubscribed = False
        self.closed = False

    async def subscribe(self, name):
        return None

    async def get_message(self, timeout=0.0):
        if self._pong_pending:
            self._pong_pending = False
            return {"type": "pong", "pattern": None, "channel": None, "data": b"liveness"}
        if self._script:
            item = self._script.pop(0)
            if item is not IDLE:
                return item
        await anyio.sleep(timeout)
        return None

    async def ping(self, message=None):
        self.pings += 1
        if self.ping_error is not None:
            raise self.ping_error
        if self.answer_pings:
            self._pong_pending = True
        return True

    async def unsubscribe(self, name):
        self.unsubscribed = True

    async def aclose(self):
        self.closed = True


def _redis_with(pubsub: _FakePubSub) -> AsyncMock:
    client = MagicMock()
    client.pubsub.return_value = pubsub
    return AsyncMock(return_value=client)


@pytest.mark.unit
@pytest.mark.asyncio
class TestLivenessProbe:
    async def test_unanswered_ping_ends_subscription(self):
        pubsub = _FakePubSub(answer_pings=False)
        ticks = 0
        with patch(_AREDIS, _redis_with(pubsub)):
            with anyio.fail_after(2):
                async for payload in AsyncTopic("t").subscribe(
                    poll_timeout=0.01, liveness_timeout=0.05
                ):
                    assert payload is None
                    ticks += 1
        assert ticks > 0
        assert pubsub.pings == 1
        assert pubsub.unsubscribed
        assert pubsub.closed

    async def test_answered_pings_keep_subscription_open(self):
        pubsub = _FakePubSub(answer_pings=True)
        with patch(_AREDIS, _redis_with(pubsub)):
            agen = AsyncTopic("t").subscribe(poll_timeout=0.01, liveness_timeout=0.03)
            try:
                with anyio.fail_after(2):
                    # Roughly 0.4s of idle polls: many probe windows, and the
                    # pong replies are consumed rather than yielded.
                    for _ in range(40):
                        assert await agen.__anext__() is None
            finally:
                await agen.aclose()
        assert pubsub.pings >= 2
        assert pubsub.closed

    async def test_published_traffic_counts_as_liveness(self):
        message = {"type": "message", "channel": b"t", "data": b"event"}
        # Traffic every 3 polls (0.03s) never leaves a 0.05s quiet window.
        script = [message, IDLE, IDLE] * 10
        pubsub = _FakePubSub(script, answer_pings=False)
        received = []
        with patch(_AREDIS, _redis_with(pubsub)):
            with anyio.fail_after(3):
                async for payload in AsyncTopic("t").subscribe(
                    poll_timeout=0.01, liveness_timeout=0.05
                ):
                    if payload is not None:
                        received.append(payload)
                        assert pubsub.pings == 0
        assert received == [b"event"] * 10
        # The only probe went out after the traffic stopped, and it ended the stream.
        assert pubsub.pings == 1

    async def test_ping_failure_ends_subscription(self):
        pubsub = _FakePubSub(ping_error=ConnectionError("broken pipe"))
        with patch(_AREDIS, _redis_with(pubsub)):
            with anyio.fail_after(2):
                async for _payload in AsyncTopic("t").subscribe(
                    poll_timeout=0.01, liveness_timeout=0.03
                ):
                    pass
        assert pubsub.pings == 1
        assert pubsub.closed

    async def test_pool_exhaustion_warns_with_setting_name(self):
        from redis.exceptions import MaxConnectionsError

        pubsub = _FakePubSub()

        async def _exhausted(name):
            raise MaxConnectionsError("Too many connections")

        pubsub.subscribe = _exhausted
        with patch(_AREDIS, _redis_with(pubsub)), patch(
            "docsgpt.streaming.async_broadcast_channel.logger"
        ) as log:
            items = [payload async for payload in AsyncTopic("t").subscribe(poll_timeout=0.01)]
        assert items == []
        assert pubsub.closed
        assert log.warning.called
        assert "ASYNC_REDIS_MAX_CONNECTIONS" in str(log.warning.call_args)
        log.exception.assert_not_called()

    async def test_no_probe_when_liveness_disabled(self):
        pubsub = _FakePubSub(answer_pings=False)
        with patch(_AREDIS, _redis_with(pubsub)):
            agen = AsyncTopic("t").subscribe(poll_timeout=0.005)
            try:
                with anyio.fail_after(2):
                    for _ in range(30):
                        assert await agen.__anext__() is None
            finally:
                await agen.aclose()
        assert pubsub.pings == 0
