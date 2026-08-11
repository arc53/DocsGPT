"""Wire-level keepalive for synchronous SSE streaming routes.

``with_sse_keepalive`` pumps the stream from a daemon thread and emits
``: keepalive`` SSE comment frames whenever the inner generator stays
quiet — long tool-argument generations, summary-less reasoning stretches,
and server-side tool runs otherwise leave the connection byte-silent until
a fronting proxy (Cloudflare, ~100s idle) cuts it while the origin is
still working. Used by both ``/stream`` and ``/v1/chat/completions``.
"""

import contextvars
import threading

import pytest

from application.streaming.sse_keepalive import with_sse_keepalive


@pytest.mark.unit
def test_keepalive_comments_emitted_while_inner_is_quiet():
    release = threading.Event()

    def slow_inner():
        release.wait(5)
        yield "data: one\n\n"

    gen = with_sse_keepalive(slow_inner(), 0.02)
    # The inner generator is gated on ``release``, so the first frame must
    # be a keepalive — no timing race on loaded runners.
    assert next(gen) == ": keepalive\n\n"
    release.set()
    rest = list(gen)
    assert rest[-1] == "data: one\n\n"


@pytest.mark.unit
def test_items_pass_through_in_order_without_spurious_keepalives():
    out = list(with_sse_keepalive(iter(["a", "b", "c"]), 5.0))
    assert out == ["a", "b", "c"]


@pytest.mark.unit
def test_inner_exception_propagates_to_consumer():
    def failing_inner():
        yield "a"
        raise RuntimeError("boom")

    frames = with_sse_keepalive(failing_inner(), 5.0)
    assert next(frames) == "a"
    with pytest.raises(RuntimeError, match="boom"):
        next(frames)


@pytest.mark.unit
def test_empty_inner_ends_cleanly():
    assert list(with_sse_keepalive(iter([]), 5.0)) == []


@pytest.mark.unit
def test_close_returns_promptly_while_pump_drains_inner():
    """Consumer close() (client disconnect) ends the wrapper without raising
    or blocking; the pump drains the inner generator to completion."""
    release = threading.Event()
    drained = threading.Event()

    def inner():
        yield "a"
        release.wait(5)
        yield "b"
        drained.set()

    gen = with_sse_keepalive(inner(), 5.0)
    assert next(gen) == "a"
    gen.close()
    release.set()
    assert drained.wait(2), "pump should drain the inner generator"


@pytest.mark.unit
def test_pump_runs_in_callers_contextvars_context():
    """Request-scoped log bindings (ContextVars) must survive the pump's
    thread hop so generation logs keep their correlation ids."""
    var = contextvars.ContextVar("sse_keepalive_test_var", default="unset")
    var.set("bound")
    seen = {}

    def inner():
        seen["value"] = var.get()
        yield "data: x\n\n"

    assert list(with_sse_keepalive(inner(), 5.0)) == ["data: x\n\n"]
    assert seen["value"] == "bound"
