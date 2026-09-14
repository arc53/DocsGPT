"""Streaming response for native-async routes whose streams hold resources."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)


class ClosingStreamingResponse(StreamingResponse):
    """``StreamingResponse`` that always finalizes its stream.

    When a client disconnects, Starlette cancels the send loop and drops the
    body iterator: a generator paused between frames, or one that never
    started, would leave its cleanup to garbage collection. This closes the
    iterator and then runs ``on_close`` once the response is over, shielded
    from the cancellation that ended it.
    """

    def __init__(self, content, *, on_close: Optional[Callable[[], Awaitable[None]]] = None, **kwargs) -> None:
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                aclose = getattr(self.body_iterator, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:
                        logger.exception("closing the response stream failed")
                if self._on_close is not None:
                    try:
                        await self._on_close()
                    except Exception:
                        logger.exception("response on_close hook failed")
