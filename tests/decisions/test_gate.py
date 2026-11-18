"""The pass gate: one pass at a time, hot first, background throttled, hopeless waiters turned away."""

import threading
import time

import pytest

from docsgpt.decisions.gate import Gate, GateTimeout


def far() -> float:
    return time.monotonic() + 10.0


def start_waiter(gate, lane, order, deadline=None, predicted=0.0):
    """Acquire in a thread, record the lane when admitted, and release at once."""
    def run():
        gate.acquire(lane, deadline or far(), predicted)
        order.append(lane)
        gate.release(lane, 0.0)

    thread = threading.Thread(target=run)
    thread.start()
    return thread


def wait_for_waiters(gate, hot=0, background=0):
    end = time.monotonic() + 2
    while time.monotonic() < end:
        if len(gate._waiting["hot"]) == hot and len(gate._waiting["background"]) == background:
            return
        time.sleep(0.005)
    raise AssertionError("waiters did not queue")


@pytest.mark.unit
class TestOrder:
    def test_hot_goes_before_background_that_queued_first(self):
        gate = Gate(share=1.0)
        gate.acquire("hot", far(), 0.0)  # a pass in progress
        order = []
        background = start_waiter(gate, "background", order)
        wait_for_waiters(gate, background=1)
        hot = start_waiter(gate, "hot", order)
        wait_for_waiters(gate, hot=1, background=1)
        gate.release("hot", 0.0)
        hot.join(2)
        background.join(2)
        assert order == ["hot", "background"]

    def test_one_pass_at_a_time(self):
        gate = Gate(share=1.0)
        gate.acquire("hot", far(), 0.0)
        with pytest.raises(GateTimeout):
            gate.acquire("hot", time.monotonic() + 0.05, 0.0)


@pytest.mark.unit
class TestAdmission:
    def test_a_pass_that_cannot_finish_in_time_is_refused_at_once(self):
        gate = Gate(share=1.0)
        started = time.monotonic()
        with pytest.raises(GateTimeout):
            gate.acquire("hot", started + 0.5, predicted=1.0)
        assert time.monotonic() - started < 0.1

    def test_a_waiter_leaves_when_its_pass_no_longer_fits(self):
        gate = Gate(share=1.0)
        gate.acquire("background", far(), 0.0)
        started = time.monotonic()
        with pytest.raises(GateTimeout):
            gate.acquire("hot", started + 0.3, predicted=0.2)
        assert 0.05 < time.monotonic() - started < 0.25
        assert not gate._waiting["hot"]


@pytest.mark.unit
class TestThrottle:
    def test_background_waits_its_share_after_a_background_pass(self):
        gate = Gate(share=0.25)
        gate.acquire("background", far(), 0.0)
        gate.release("background", 0.05)  # at 0.25, the next background pass waits 3 x 0.05 s
        assert gate.acquire("background", far(), 0.0) >= 0.12
        gate.release("background", 0.0)

    def test_hot_is_never_throttled(self):
        gate = Gate(share=0.25)
        gate.acquire("background", far(), 0.0)
        gate.release("background", 1.0)
        assert gate.acquire("hot", far(), 0.0) < 0.05
