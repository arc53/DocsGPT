"""Async Redis pub/sub Topic for the native-async SSE reader.

Event-loop twin of :class:`application.streaming.broadcast_channel.Topic`.
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
from typing import AsyncIterator, Awaitable, Callable, Optional, Union

import anyio

from application.streaming.async_redis import get_async_redis_instance

logger = logging.getLogger(__name__)

OnSubscribe = Callable[[], Union[None, Awaitable[None]]]


class AsyncTopic:
    """An async pub/sub channel identified by a string name."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def subscribe(
        self,
        on_subscribe: Optional[OnSubscribe] = None,
        poll_timeout: float = 1.0,
    ) -> AsyncIterator[Optional[bytes]]:
        """Subscribe to the topic; yield raw payloads or ``None`` on tick.

        ``on_subscribe`` runs (and is awaited if it returns a coroutine)
        after Redis acks SUBSCRIBE — use it to seed snapshot state that
        must be ordered after the subscriber is live but before the first
        live message is processed. If Redis is unavailable, returns
        immediately without yielding so the caller can fall back to a
        direct snapshot read. Cleanly unsubscribes on close / disconnect.
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
            except Exception:
                # Transient subscribe failure is treated like "Redis
                # unavailable": yield nothing, let the caller fall back to
                # its own snapshot read. The finally block still tears the
                # pubsub down cleanly.
                logger.exception("async pubsub.subscribe failed for %s", self.name)
                return
            while True:
                try:
                    msg = await pubsub.get_message(timeout=poll_timeout)
                except Exception:
                    logger.exception(
                        "async pubsub.get_message failed for %s", self.name
                    )
                    return
                if msg is None:
                    yield None
                    continue
                msg_type = msg.get("type")
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
            # get_message`` above; without shielding, the cancellation could
            # re-fire mid-teardown and skip ``aclose()``, leaking the pooled
            # connection back to nothing. Shield so unsubscribe + aclose
            # always complete and the connection returns to the pool.
            with anyio.CancelScope(shield=True):
                if on_subscribe_fired:
                    try:
                        await pubsub.unsubscribe(self.name)
                    except Exception:
                        logger.debug(
                            "async pubsub unsubscribe error for %s",
                            self.name,
                            exc_info=True,
                        )
                try:
                    await pubsub.aclose()
                except Exception:
                    logger.debug(
                        "async pubsub close error for %s", self.name, exc_info=True
                    )
