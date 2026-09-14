"""Streaming response for native-async routes whose streams hold resources."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterable, Awaitable, Callable, Optional

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

# Upper bound on each cleanup step. Cleanup is shielded from the cancellation
# that ended the response, so a step stuck on a dead connection would otherwise
# hold the request task, and a graceful shutdown, indefinitely.
_CLEANUP_TIMEOUT_SECONDS = 5.0


class ClosingStreamingResponse(StreamingResponse):
    """``StreamingResponse`` that always finalizes its stream.

    When a client disconnects, Starlette cancels the send loop and drops the
    body iterator: a generator paused between frames, or one that never
    started, would leave its cleanup to garbage collection. This closes the
    iterator and then runs ``on_close`` once the response is over. Each step is
    shielded from the cancellation that ended the response and bounded by
    ``_CLEANUP_TIMEOUT_SECONDS``, so ``on_close`` still runs if closing the
    iterator hangs.
    """

    def __init__(
        self,
        content: AsyncIterable[Any],
        *,
        on_close: Optional[Callable[[], Awaitable[None]]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                await _bounded(aclose, "closing the response stream")
            if self._on_close is not None:
                await _bounded(self._on_close, "response on_close hook")


async def _bounded(step: Callable[[], Awaitable[None]], what: str) -> None:
    """Run one cleanup step shielded from cancellation, giving up after the cleanup timeout."""
    with anyio.move_on_after(_CLEANUP_TIMEOUT_SECONDS, shield=True) as scope:
        try:
            await step()
        except Exception:
            logger.exception("%s failed", what)
    if scope.cancelled_caught:
        logger.warning("%s timed out after %ss", what, _CLEANUP_TIMEOUT_SECONDS)
