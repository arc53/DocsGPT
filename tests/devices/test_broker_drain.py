"""Tests for ``DeviceBroker.drain_output`` deadline handling."""

from __future__ import annotations

import time

from application.devices.broker import DeviceBroker, INVOCATION_DONE


def _dispatch(broker: DeviceBroker):
    envelope = {"invocation_id": "inv_test", "action": "run_command"}
    return broker.dispatch_invocation("dev_x", "user_x", envelope)


def test_drain_output_returns_after_deadline_with_no_output():
    # Device never connects / posts output and ``completed`` is never set:
    # the generator must stop once the deadline passes instead of looping.
    broker = DeviceBroker()
    inv = _dispatch(broker)
    deadline = time.time() + 0.2
    start = time.time()
    chunks = list(
        broker.drain_output(inv.invocation_id, timeout=0.05, deadline=deadline)
    )
    elapsed = time.time() - start
    assert chunks == []
    assert not inv.completed.is_set()
    assert elapsed < 2.0


def test_drain_output_yields_then_stops_on_done():
    # Sanity: a normal stream still drains and stops on INVOCATION_DONE,
    # with a generous deadline that should not fire.
    broker = DeviceBroker()
    inv = _dispatch(broker)
    inv.output_queue.put({"stream": "stdout", "chunk": "hello"})
    inv.output_queue.put(INVOCATION_DONE)
    deadline = time.time() + 5.0
    chunks = list(
        broker.drain_output(inv.invocation_id, timeout=0.05, deadline=deadline)
    )
    assert chunks == [{"stream": "stdout", "chunk": "hello"}]


def test_drain_output_no_deadline_stops_when_completed():
    # Without a deadline, the completed event still terminates the loop.
    broker = DeviceBroker()
    inv = _dispatch(broker)
    inv.completed.set()
    chunks = list(broker.drain_output(inv.invocation_id, timeout=0.05))
    assert chunks == []
