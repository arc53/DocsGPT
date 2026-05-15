"""Redis pub/sub Topic abstraction for SSE fan-out.

A Topic is a named channel for one-shot live event delivery. Canonical uses:

- ``user:{user_id}`` for per-user notifications
- ``channel:{message_id}`` for per-chat-message streams

Subscription is race-free via ``on_subscribe``: the callback fires only
after Redis acknowledges ``SUBSCRIBE``, so a publisher dispatched inside
the callback cannot lose its first event to a not-yet-registered
subscriber.

The subscribe iterator yields ``None`` on poll timeout so the caller can
emit SSE keepalive comments without spawning a separate timer thread.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterator, Optional

from application.cache import get_redis_instance

logger = logging.getLogger(__name__)


class Topic:
    """A pub/sub channel identified by a string name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def publish(self, payload: str | bytes) -> int:
        """Fan out a payload to currently subscribed clients.

        Returns the number Redis reports as receiving the message (limited
        to subscribers connected to *this* Redis instance), or 0 if Redis
        is unavailable. Never raises.
        """
        redis = get_redis_instance()
        if redis is None:
            logger.debug("Redis unavailable; dropping publish to %s", self.name)
            return 0
        try:
            return int(redis.publish(self.name, payload))
        except Exception:
            logger.exception("Topic.publish failed for %s", self.name)
            return 0

    def subscribe(
        self,
        on_subscribe: Optional[Callable[[], None]] = None,
        poll_timeout: float = 1.0,
    ) -> Iterator[Optional[bytes]]:
        """Subscribe to the topic; yield raw payloads or ``None`` on tick.

        Yields ``None`` every ``poll_timeout`` seconds while idle so the
        caller can emit keepalive frames or check cancellation. Yields
        ``bytes`` for each delivered message.

        ``on_subscribe`` runs synchronously after Redis acknowledges the
        SUBSCRIBE — use it to seed any state (e.g. read backlog) that
        must be ordered after the subscriber is live but before the
        first pub/sub message is processed.

        If Redis is unavailable, returns immediately without yielding.
        Cleanly unsubscribes on ``GeneratorExit`` (client disconnect).
        """
        redis = get_redis_instance()
        if redis is None:
            logger.debug("Redis unavailable; subscribe to %s yielded nothing", self.name)
            return
        pubsub = None
        on_subscribe_fired = False
        try:
            pubsub = redis.pubsub()
            try:
                pubsub.subscribe(self.name)
            except Exception:
                # Subscribe failure (transient Redis hiccup, conn reset, etc.)
                # is treated like "Redis unavailable": yield nothing, let the
                # caller fall back to its own resilience strategy. The finally
                # block will still tear down the pubsub object cleanly.
                logger.exception("pubsub.subscribe failed for %s", self.name)
                return
            while True:
                try:
                    msg = pubsub.get_message(timeout=poll_timeout)
                except Exception:
                    logger.exception("pubsub.get_message failed for %s", self.name)
                    return
                if msg is None:
                    yield None
                    continue
                msg_type = msg.get("type")
                if msg_type == "subscribe":
                    if not on_subscribe_fired and on_subscribe is not None:
                        try:
                            on_subscribe()
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
            if pubsub is not None:
                if on_subscribe_fired:
                    try:
                        pubsub.unsubscribe(self.name)
                    except Exception:
                        logger.debug(
                            "pubsub unsubscribe error for %s",
                            self.name,
                            exc_info=True,
                        )
                try:
                    pubsub.close()
                except Exception:
                    logger.debug("pubsub close error for %s", self.name, exc_info=True)
