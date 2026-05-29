"""Tests for ``DeviceBroker.drain_output`` deadline + control handling."""

from __future__ import annotations

import time


def _dispatch(broker):
    envelope = {"invocation_id": "inv_test", "action": "run_command"}
    return broker.dispatch_invocation("dev_x", "user_x", envelope)


def test_drain_output_returns_after_deadline_with_no_output(broker_env):
    # Device never connects / posts output: the generator must stop once the
    # deadline passes instead of looping forever.
    broker, _fake = broker_env
    inv = _dispatch(broker)
    deadline = time.time() + 0.2
    start = time.time()
    chunks = list(
        broker.drain_output(inv.invocation_id, timeout=0.05, deadline=deadline)
    )
    elapsed = time.time() - start
    assert chunks == []
    assert elapsed < 2.0


def test_drain_output_yields_then_stops_on_control(broker_env):
    # A normal stream drains stdout then stops on the closing control chunk.
    broker, _fake = broker_env
    inv = _dispatch(broker)
    broker.submit_output_chunk(inv.invocation_id, {"stream": "stdout", "chunk": "hello"})
    broker.submit_output_chunk(
        inv.invocation_id, {"stream": "control", "exit_code": 0, "duration_ms": 1}
    )
    deadline = time.time() + 5.0
    chunks = list(
        broker.drain_output(inv.invocation_id, timeout=0.05, deadline=deadline)
    )
    assert chunks[0] == {"stream": "stdout", "chunk": "hello"}
    assert chunks[-1]["stream"] == "control"
    assert chunks[-1]["exit_code"] == 0


def test_drain_output_stops_when_completed_without_control(broker_env):
    # If the invocation is marked completed but no control chunk is on the
    # stream, the completed flag still terminates the drain loop.
    broker, fake = broker_env
    inv = _dispatch(broker)
    fake.hset(f"dev:inv:{inv.invocation_id}", mapping={"completed": "1"})
    chunks = list(broker.drain_output(inv.invocation_id, timeout=0.05))
    assert chunks == []


def test_drain_output_reports_error_when_redis_unavailable(monkeypatch):
    # No Redis: the tool must get a clear control/error chunk, not hang.
    from application.devices.broker import DeviceBroker

    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: None
    )
    broker = DeviceBroker()
    chunks = list(broker.drain_output("inv_missing", timeout=0.05))
    assert len(chunks) == 1
    assert chunks[0]["stream"] == "control"
    assert "unavailable" in chunks[0]["error"]
