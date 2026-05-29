"""Regression: a command dispatched in one process reaches a session in another.

This reproduces the scheduled-run failure. The agent runs inside a Celery
worker (``worker_broker``) while the device's SSE session lives in the web
process (``web_broker``). With the old in-process broker these two never
shared state, so every scheduled invocation timed out. Backed by one Redis
(here a shared ``FakeRedis``), dispatch and drain cross the process line.
"""

from __future__ import annotations

import time

from application.devices.broker import DeviceBroker


def test_dispatch_in_worker_reaches_session_in_web(monkeypatch, fake_redis):
    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: fake_redis
    )
    worker_broker = DeviceBroker()  # e.g. Celery scheduled run
    web_broker = DeviceBroker()  # e.g. gunicorn web tier holding the SSE socket

    # 1) Agent (worker process) dispatches a command.
    envelope = {
        "invocation_id": "inv_xproc",
        "action": "run_command",
        "params": {"command": "echo hi"},
    }
    worker_broker.dispatch_invocation("dev_1", "user_1", envelope)

    # 2) Device polls/upgrades on the web process and receives the command.
    assert web_broker.claim_ticket("dev_1", 30) is not None
    sess = web_broker.register_session("dev_1", "user_1")
    delivered = web_broker.next_command(sess, timeout=0.1)
    assert delivered is not None
    assert delivered["invocation_id"] == "inv_xproc"
    assert delivered["params"]["command"] == "echo hi"

    # 3) Device streams output back through the web process.
    web_broker.submit_output_chunk("inv_xproc", {"stream": "stdout", "chunk": "hi\n"})
    web_broker.submit_output_chunk(
        "inv_xproc",
        {"stream": "control", "exit_code": 0, "duration_ms": 7},
    )

    # 4) The worker's drain (what the tool does) sees the full result.
    deadline = time.time() + 2.0
    chunks = list(
        worker_broker.drain_output("inv_xproc", timeout=0.05, deadline=deadline)
    )
    stdout = "".join(c.get("chunk", "") for c in chunks if c.get("stream") == "stdout")
    control = [c for c in chunks if c.get("stream") == "control"]
    assert stdout == "hi\n"
    assert control and control[0]["exit_code"] == 0

    # And the metadata snapshot reflects completion across instances.
    final = worker_broker.get_invocation("inv_xproc")
    assert final is not None
    assert final.completed is True
    assert final.exit_code == 0
    assert final.stdout_bytes == len("hi\n")


def test_denied_ack_unblocks_drain(monkeypatch, fake_redis):
    # A denial on the web side must promptly stop a worker-side drain.
    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: fake_redis
    )
    worker_broker = DeviceBroker()
    web_broker = DeviceBroker()

    worker_broker.dispatch_invocation(
        "dev_2", "user_2", {"invocation_id": "inv_deny", "action": "run_command"}
    )
    web_broker.submit_ack("inv_deny", "denied", reason="user rejected")

    deadline = time.time() + 2.0
    chunks = list(
        worker_broker.drain_output("inv_deny", timeout=0.05, deadline=deadline)
    )
    assert chunks and chunks[-1]["stream"] == "control"
    assert chunks[-1]["error"] == "denied"
