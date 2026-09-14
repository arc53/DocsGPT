"""Tests for ``docsgpt/api/asgi_stream.py`` — cleanup that can't stall a worker.

The cleanup runs shielded from the cancellation that ended the response, so
each step needs its own deadline: a close or release waiting on a dead Redis
connection must not hold the request task, or a graceful shutdown, forever.
"""

from __future__ import annotations

import anyio
import pytest

from docsgpt.api import asgi_stream
from docsgpt.api.asgi_stream import ClosingStreamingResponse
from tests.asgi_stream import stream_then_disconnect


class _StuckCloseIterator:
    """Yields one chunk, then ends; its ``aclose`` never returns."""

    def __init__(self) -> None:
        self._sent = False
        self.aclose_started = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return b"chunk"

    async def aclose(self):
        self.aclose_started = True
        await anyio.sleep_forever()


async def _one_chunk():
    yield b"chunk"


@pytest.mark.unit
@pytest.mark.asyncio
class TestBoundedCleanup:
    async def test_stuck_stream_close_is_abandoned_and_on_close_still_runs(self, monkeypatch):
        monkeypatch.setattr(asgi_stream, "_CLEANUP_TIMEOUT_SECONDS", 0.05)
        body = _StuckCloseIterator()
        released = {"ran": False}

        async def on_close():
            released["ran"] = True

        response = ClosingStreamingResponse(body, media_type="text/plain", on_close=on_close)
        with anyio.fail_after(2):
            status, _, chunks = await stream_then_disconnect(
                response, "/", chunks_before_disconnect=10**6
            )
        assert status == 200
        assert chunks == [b"chunk"]
        assert body.aclose_started
        assert released["ran"] is True

    async def test_stuck_on_close_is_abandoned(self, monkeypatch):
        monkeypatch.setattr(asgi_stream, "_CLEANUP_TIMEOUT_SECONDS", 0.05)

        async def on_close():
            await anyio.sleep_forever()

        response = ClosingStreamingResponse(_one_chunk(), media_type="text/plain", on_close=on_close)
        with anyio.fail_after(2):
            status, _, chunks = await stream_then_disconnect(
                response, "/", chunks_before_disconnect=10**6
            )
        assert status == 200
        assert chunks == [b"chunk"]

    async def test_on_close_runs_when_client_leaves_before_first_frame(self):
        released = {"count": 0}

        async def on_close():
            released["count"] += 1

        async def endless():
            while True:
                await anyio.sleep(0.01)
                yield b"tick"

        response = ClosingStreamingResponse(endless(), media_type="text/plain", on_close=on_close)
        with anyio.fail_after(2):
            await stream_then_disconnect(response, "/", chunks_before_disconnect=0)
        assert released["count"] == 1
