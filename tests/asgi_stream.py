"""Drive a streaming ASGI response and disconnect the client mid-stream.

Starlette's ``TestClient`` buffers a response until the app returns, so it
can't exercise what happens when a browser tab closes on an endless SSE
stream. This harness speaks raw ASGI: it hands the app one GET, collects the
response, and delivers ``http.disconnect`` once enough body has arrived.
"""

from __future__ import annotations

from typing import Mapping, Optional

import anyio


async def stream_then_disconnect(
    app,
    path: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    query_string: bytes = b"",
    chunks_before_disconnect: int = 1,
    timeout: float = 5.0,
) -> tuple[Optional[int], dict[str, str], list[bytes]]:
    """Run ``app`` for one GET, disconnecting after ``chunks_before_disconnect`` body chunks.

    A response that finishes on its own (a 401, a stream that ends) returns
    without any disconnect. ``chunks_before_disconnect=0`` disconnects as soon
    as the request is read, before any body. ``timeout`` fails the test
    instead of hanging it when a stream never ends.

    Returns:
        tuple: ``(status, headers, body_chunks)`` with lower-cased header names.
    """
    disconnected = anyio.Event()
    if chunks_before_disconnect <= 0:
        disconnected.set()
    request_delivered = False
    status: Optional[int] = None
    response_headers: dict[str, str] = {}
    chunks: list[bytes] = []

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "root_path": "",
        "query_string": query_string,
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }

    async def receive():
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            for name, value in message.get("headers", []):
                response_headers[name.decode("latin-1")] = value.decode("latin-1")
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                chunks.append(body)
                if len(chunks) >= chunks_before_disconnect:
                    disconnected.set()
            if not message.get("more_body", False):
                disconnected.set()

    with anyio.fail_after(timeout):
        await app(scope, receive, send)
    return status, response_headers, chunks
