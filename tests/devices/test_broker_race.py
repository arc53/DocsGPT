"""Race-condition regressions for the Redis-backed broker.

These cover the concurrency paths the happy-path suite cannot reach: the
completion-flag-vs-control-chunk ordering, drain's final flush, the tool's
near-deadline capture + authoritative fallback, and the cleanup/dispatch
edge paths. Each fails against the pre-fix code and passes after.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from application.agents.tools.remote_device import RemoteDeviceTool, _MAX_TIMEOUT_MS
from application.core.settings import settings
from application.devices.broker import DeviceBroker, Invocation

from .conftest import FakeRedis


class RacyFakeRedis(FakeRedis):
    """FakeRedis that fires a one-shot hook on the FIRST ``xread`` and returns
    empty for that call — modelling a drain observing completion before the
    chunks are visible to its read cursor.
    """

    def __init__(self) -> None:
        super().__init__()
        self.on_first_empty = None
        self._fired = False

    def xread(self, streams, count=None, block=None):
        if not self._fired and self.on_first_empty is not None:
            self._fired = True
            self.on_first_empty()  # web side posts output + control here
            return None  # this read still sees nothing
        return super().xread(streams, count=count, block=block)


class _StubBroker:
    """Minimal broker for exercising RemoteDeviceTool._collect_result."""

    def __init__(self, chunks, snapshot=None):
        self._chunks = chunks
        self._snapshot = snapshot
        self.cleaned = False

    def drain_output(self, invocation_id, timeout=1.0, deadline=None):
        for chunk in self._chunks:
            yield chunk

    def get_invocation(self, invocation_id):
        return self._snapshot

    def cleanup_invocation(self, invocation_id):
        self.cleaned = True


def _tool():
    # Bypass __init__ (which loads the device from the DB); _collect_result
    # uses only its arguments, no instance state.
    return RemoteDeviceTool.__new__(RemoteDeviceTool)


# ---------------------------------------------------------------------------
# drain_output final-flush (HIGH): completion observed before control read
# ---------------------------------------------------------------------------
def test_drain_flushes_chunks_posted_after_first_empty_read(monkeypatch):
    fake = RacyFakeRedis()
    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: fake
    )
    worker = DeviceBroker()  # Celery side: dispatch + drain
    web = DeviceBroker()  # web side: posts output
    worker.dispatch_invocation(
        "d_race", "u_race",
        {"invocation_id": "inv_race", "action": "run_command"},
    )

    def hook():
        web.submit_output_chunk("inv_race", {"stream": "stdout", "chunk": "out"})
        web.submit_output_chunk(
            "inv_race", {"stream": "control", "exit_code": 0, "duration_ms": 1}
        )

    fake.on_first_empty = hook
    chunks = list(
        worker.drain_output("inv_race", timeout=0.05, deadline=time.time() + 5)
    )
    stdout = "".join(c.get("chunk", "") for c in chunks if c.get("stream") == "stdout")
    control = [c for c in chunks if c.get("stream") == "control"]
    # Pre-fix: drain returned [] on the _is_completed early-return, dropping both.
    assert stdout == "out"
    assert control and control[0]["exit_code"] == 0


# ---------------------------------------------------------------------------
# _collect_result authoritative fallback + near-deadline capture (MEDIUM)
# ---------------------------------------------------------------------------
def test_collect_result_uses_completion_snapshot_when_no_control():
    inv = SimpleNamespace(invocation_id="i", device_id="d", completed=False, error=None)
    snap = Invocation("i", "d", completed=True, exit_code=0, duration_ms=9)
    broker = _StubBroker([], snapshot=snap)  # drain yields nothing
    res = _tool()._collect_result(broker, inv, {"name": "dev"}, 1000)
    assert res["exit_code"] == 0
    assert not res["error"]
    assert broker.cleaned


def test_collect_result_times_out_when_snapshot_incomplete():
    inv = SimpleNamespace(invocation_id="i", device_id="d", completed=False, error=None)
    broker = _StubBroker([], snapshot=None)
    res = _tool()._collect_result(broker, inv, {"name": "dev"}, 1000)
    assert "did not respond" in (res["error"] or "")


def test_collect_result_captures_control_chunk_past_deadline(monkeypatch):
    from application.agents.tools import remote_device as rd

    # First time.time() seeds the deadline; later calls are far past it, so the
    # post-capture break fires — the control chunk must still be captured.
    seq = iter([100.0])

    def fake_time():
        try:
            return next(seq)
        except StopIteration:
            return 1e9

    monkeypatch.setattr(rd.time, "time", fake_time)
    inv = SimpleNamespace(invocation_id="i", device_id="d", completed=False, error=None)
    broker = _StubBroker([{"stream": "control", "exit_code": 7, "duration_ms": 3}])
    res = _tool()._collect_result(broker, inv, {"name": "dev"}, 30000)
    assert res["exit_code"] == 7
    assert not res["error"]


# ---------------------------------------------------------------------------
# cleanup / dispatch / next_command edge paths
# ---------------------------------------------------------------------------
def test_dispatch_failure_cleans_inv_hash(monkeypatch):
    class RpushFailRedis(FakeRedis):
        def rpush(self, key, *values):
            raise RuntimeError("queue write failed")

    fake = RpushFailRedis()
    monkeypatch.setattr(
        "application.devices.broker.get_redis_instance", lambda: fake
    )
    broker = DeviceBroker()
    inv = broker.dispatch_invocation(
        "d_fail", "u_fail",
        {
            "invocation_id": "inv_fail",
            "action": "run_command",
            "params": {"command": "echo secret"},
        },
    )
    assert inv.completed is True
    assert inv.error
    # The plaintext command must not be stranded in the orphaned hash.
    assert broker.get_invocation("inv_fail") is None
    assert fake.exists("dev:inv:inv_fail") == 0


def test_next_command_drops_reaped_invocation(broker_env):
    broker, fake = broker_env
    broker.dispatch_invocation(
        "d_reap", "u_reap",
        {"invocation_id": "inv_reap", "action": "run_command"},
    )
    # Invocation reaped (timed out / cleaned up) after it was queued.
    fake.delete("dev:inv:inv_reap")
    sess = broker.register_session("d_reap", "u_reap")
    assert broker.next_command(sess, timeout=0.05) is None


def test_byte_counts_are_utf8(broker_env):
    broker, _fake = broker_env
    broker.dispatch_invocation(
        "d_utf", "u_utf",
        {"invocation_id": "inv_utf", "action": "run_command"},
    )
    text = "héllo 世界 🚀"
    broker.submit_output_chunk("inv_utf", {"stream": "stdout", "chunk": text})
    snap = broker.get_invocation("inv_utf")
    assert snap.stdout_bytes == len(text.encode("utf-8"))
    assert snap.stdout_bytes != len(text)  # bytes != characters for this string


def test_cmd_queue_ttl_covers_max_command_timeout():
    # A queued command must outlive its own drain deadline so a briefly-offline
    # device that reconnects late still receives it.
    assert settings.REMOTE_DEVICE_CMD_QUEUE_TTL_SECONDS >= _MAX_TIMEOUT_MS / 1000 + 5
