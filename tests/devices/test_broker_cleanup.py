"""Tests for ``DeviceBroker.cleanup_invocation`` queued-command removal."""

from __future__ import annotations


def _dispatch_offline(broker, invocation_id="inv_stale", device_id="dev_x"):
    # No session draining -> the envelope stays queued on the device's list.
    envelope = {"invocation_id": invocation_id, "action": "run_command"}
    return broker.dispatch_invocation(device_id, "user_x", envelope)


def test_cleanup_removes_queued_command_so_it_doesnt_replay(broker_env):
    # A timed-out invocation cleaned up while still queued must NOT later be
    # delivered to (and run by) a freshly connected session.
    broker, fake = broker_env
    inv = _dispatch_offline(broker)
    assert fake.llen("dev:cmd:dev_x") == 1

    broker.cleanup_invocation(inv.invocation_id)

    assert fake.llen("dev:cmd:dev_x") == 0
    assert broker.get_invocation(inv.invocation_id) is None

    # A session that connects now finds nothing queued.
    sess = broker.register_session("dev_x", "user_x")
    assert broker.next_command(sess, timeout=0.05) is None


def test_cleanup_deletes_invocation_and_output(broker_env):
    # The metadata hash and output stream are removed on cleanup.
    broker, fake = broker_env
    _dispatch_offline(broker, invocation_id="inv_live", device_id="dev_live")
    broker.submit_output_chunk(
        "inv_live", {"stream": "control", "exit_code": 0, "duration_ms": 1}
    )
    assert fake.exists("dev:inv:inv_live") == 1
    assert fake.exists("dev:out:inv_live") == 1

    broker.cleanup_invocation("inv_live")

    assert fake.exists("dev:inv:inv_live") == 0
    assert fake.exists("dev:out:inv_live") == 0
    assert broker.get_invocation("inv_live") is None


def test_cleanup_keeps_other_queued_commands(broker_env):
    # Cleaning one invocation must leave a sibling queued command intact.
    broker, fake = broker_env
    inv1 = _dispatch_offline(broker, invocation_id="inv_1", device_id="dev_y")
    _dispatch_offline(broker, invocation_id="inv_2", device_id="dev_y")
    assert fake.llen("dev:cmd:dev_y") == 2

    broker.cleanup_invocation(inv1.invocation_id)
    assert fake.llen("dev:cmd:dev_y") == 1

    sess = broker.register_session("dev_y", "user_y")
    envelope = broker.next_command(sess, timeout=0.05)
    assert envelope is not None
    assert envelope["invocation_id"] == "inv_2"
