"""Tests for ``DeviceBroker.cleanup_invocation`` pending removal."""

from __future__ import annotations

from queue import Empty

from application.devices.broker import DeviceBroker


def _dispatch_offline(broker: DeviceBroker):
    # No session registered -> the invocation lands in _pending.
    envelope = {"invocation_id": "inv_stale", "action": "run_command"}
    return broker.dispatch_invocation("dev_x", "user_x", envelope)


def test_cleanup_removes_pending_so_register_session_doesnt_replay():
    # A timed-out invocation cleaned up while still pending must NOT be
    # drained/executed by a later session registration.
    broker = DeviceBroker()
    inv = _dispatch_offline(broker)
    assert broker._pending.get("dev_x") == [inv]

    broker.cleanup_invocation(inv.invocation_id)
    # Pending key gone entirely once the list empties.
    assert "dev_x" not in broker._pending
    assert broker.get_invocation(inv.invocation_id) is None

    sess = broker.register_session("dev_x", "user_x")
    # The stale invocation must not have been re-queued.
    assert inv.invocation_id not in sess.invocations
    try:
        sess.invocation_queue.get_nowait()
        raise AssertionError("stale invocation was dispatched after cleanup")
    except Empty:
        pass


def test_cleanup_keeps_other_pending_invocations():
    # Cleaning one invocation must leave a sibling pending invocation intact.
    broker = DeviceBroker()
    inv1 = broker.dispatch_invocation(
        "dev_y", "user_y", {"invocation_id": "inv_1", "action": "run_command"}
    )
    inv2 = broker.dispatch_invocation(
        "dev_y", "user_y", {"invocation_id": "inv_2", "action": "run_command"}
    )
    assert broker._pending.get("dev_y") == [inv1, inv2]

    broker.cleanup_invocation(inv1.invocation_id)
    assert broker._pending.get("dev_y") == [inv2]

    sess = broker.register_session("dev_y", "user_y")
    assert "inv_2" in sess.invocations
    assert "inv_1" not in sess.invocations
