"""Async Redis pub/sub Topic for the native-async SSE readers.

Event-loop twin of :class:`docsgpt.streaming.broadcast_channel.Topic`.
Same contract — ``subscribe`` yields ``None`` on poll timeout (so the
caller can emit keepalives / run the watchdog) and ``bytes`` per delivered
message, fires ``on_subscribe`` once after Redis acks SUBSCRIBE, and tears
the pubsub down cleanly on client disconnect — but awaitable so an idle
stream costs a coroutine instead of a WSGI thread.

Publishing stays on the sync side (the producer writes via
``broadcast_channel.Topic.publish``); this is read-only fan-out.
"""

from __future__ import annotations

import inspect
import logging
import time
from typing import AsyncIterator, Awaitable, Callable, Optional, Union

import anyio
from redis.exceptions import MaxConnectionsError

from docsgpt.streaming.async_redis import get_async_redis_instance

logger = logging.getLogger(__name__)

OnSubscribe = Callable[[], Union[None, Awaitable[None]]]

# Payload of the liveness PING. It differs from redis-py's own health-check
# payload, whose PONG the client swallows before ``get_message`` returns.
_LIVENESS_PING = "docsgpt-liveness"

# Upper bound on each teardown call (unsubscribe, close). Teardown is shielded
# from the cancellation that ended the stream, so without a bound a dead
# connection could hold the stream's task and a graceful shutdown.
_TEARDOWN_TIMEOUT_SECONDS = 5.0


class AsyncTopic:
    """An async pub/sub channel identified by a string name."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def subscribe(
        self,
        on_subscribe: Optional[OnSubscribe] = None,
        poll_timeout: float = 1.0,
        liveness_timeout: Optional[float] = None,
    ) -> AsyncIterator[Optional[bytes]]:
        """Subscribe to the topic; yield raw payloads or ``None`` on tick.

        ``on_subscribe`` runs (and is awaited if it returns a coroutine)
        after Redis acks SUBSCRIBE — use it to seed snapshot state that
        must be ordered after the subscriber is live but before the first
        live message is processed. If Redis is unavailable, returns
        immediately without yielding so the caller can fall back to a
        direct snapshot read. Cleanly unsubscribes on close / disconnect.

        ``liveness_timeout`` protects long-lived subscribers from a
        connection NAT/IPVS dropped without a FIN. Such a socket never
        errors; ``get_message`` just keeps timing out. After that many
        seconds with nothing received a PING goes out, and if nothing comes
        back within the same window the subscription ends, so the client
        reconnects and replays from its cursor.
        """
        redis = await get_async_redis_instance()
        if redis is None:
            logger.debug(
                "Async Redis unavailable; subscribe to %s yielded nothing",
                self.name,
            )
            return
        pubsub = redis.pubsub()
        on_subscribe_fired = False
        try:
            try:
                await pubsub.subscribe(self.name)
            except MaxConnectionsError:
                # Every pooled connection is held by another open stream.
                logger.warning(
                    "async Redis pool exhausted subscribing to %s; raise "
                    "ASYNC_REDIS_MAX_CONNECTIONS if this worker should hold more streams",
                    self.name,
                )
                return
            except Exception:
                # Transient subscribe failure is treated like "Redis
                # unavailable": yield nothing, let the caller fall back to
                # its own snapshot read. The finally block still tears the
                # pubsub down cleanly.
                logger.exception("async pubsub.subscribe failed for %s", self.name)
                return
            last_received = time.monotonic()
            ping_sent_at: Optional[float] = None
            while True:
                try:
                    msg = await pubsub.get_message(timeout=poll_timeout)
                except Exception:
                    logger.exception(
                        "async pubsub.get_message failed for %s", self.name
                    )
                    return
                now = time.monotonic()
                if msg is None:
                    if liveness_timeout is not None:
                        if ping_sent_at is not None:
                            if now - ping_sent_at >= liveness_timeout:
                                logger.info(
                                    "pubsub liveness probe unanswered for %s; closing subscriber",
                                    self.name,
                                )
                                return
                        elif now - last_received >= liveness_timeout:
                            try:
                                await pubsub.ping(_LIVENESS_PING)
                            except Exception:
                                logger.info(
                                    "pubsub liveness probe failed for %s; closing subscriber",
                                    self.name,
                                    exc_info=True,
                                )
                                return
                            ping_sent_at = now
                    yield None
                    continue
                last_received = now
                ping_sent_at = None
                msg_type = msg.get("type")
                if msg_type == "pong":
                    continue
                if msg_type == "subscribe":
                    if not on_subscribe_fired and on_subscribe is not None:
                        try:
                            result = on_subscribe()
                            if inspect.isawaitable(result):
                                await result
                        except Exception:
                            logger.exception(
                                "on_subscribe callback failed for %s", self.name
                            )
                    on_subscribe_fired = True
                    continue
                if msg_type != "message":
                    continue
                data = msg.get("data")
                if data is None:
                    continue
                yield data if isinstance(data, bytes) else str(data).encode("utf-8")
        finally:
            # Client disconnect cancels this generator at the ``await
            # get_message`` above. Each teardown call is shielded so the
            # cancellation can't skip it and strand the pooled connection, and
            # bounded separately so a stuck unsubscribe still lets the close run.
            if on_subscribe_fired:
                with anyio.move_on_after(_TEARDOWN_TIMEOUT_SECONDS, shield=True):
                    try:
                        await pubsub.unsubscribe(self.name)
                    except Exception:
                        logger.debug(
                            "async pubsub unsubscribe error for %s",
                            self.name,
                            exc_info=True,
                        )
            with anyio.move_on_after(_TEARDOWN_TIMEOUT_SECONDS, shield=True):
                try:
                    await pubsub.aclose()
                except Exception:
                    logger.debug(
                        "async pubsub close error for %s", self.name, exc_info=True
                    )
