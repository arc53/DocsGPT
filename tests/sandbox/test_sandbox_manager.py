"""Unit tests for SandboxManager and SandboxCreator using an in-memory backend."""

import threading
import time
from typing import Dict, List

import pytest

from application.sandbox.base import CodeSandbox, ExecResult
from application.sandbox.manager import SandboxCapacityError, SandboxManager


class FakeBackend(CodeSandbox):
    """In-memory backend recording calls; no network, fully deterministic."""

    def __init__(self) -> None:
        self.open_calls: List[str] = []
        self.attach_calls: List[str] = []
        self.closed: List[str] = []
        self.closed_handles: List[tuple] = []
        self.removed: List[tuple] = []
        self.files: Dict[str, Dict[str, bytes]] = {}
        self._handles: Dict[str, str] = {}

    def open(self, session_id: str) -> str:
        self.open_calls.append(session_id)
        self.files.setdefault(session_id, {})
        # Distinct handle id per open call so an evict + concurrent re-open of the
        # same id produce different handles (the test asserts the old one is closed).
        handle = f"handle-{session_id}-{len(self.open_calls)}"
        self._handles[session_id] = handle
        return handle

    def attach(self, session_id: str) -> str:
        self.attach_calls.append(session_id)
        if session_id in self._handles:
            return self._handles[session_id]
        return self.open(session_id)

    def close(self, session_id: str) -> None:
        self.closed.append(session_id)
        self.files.pop(session_id, None)
        self._handles.pop(session_id, None)

    def close_handle(self, session_id: str, handle: str) -> None:
        # Close the SPECIFIC captured handle; only drop the registry entry when it
        # still points at that handle (a concurrent re-open may have replaced it).
        self.closed_handles.append((session_id, handle))
        if self._handles.get(session_id) == handle:
            self._handles.pop(session_id, None)
            self.files.pop(session_id, None)

    def exec(self, session_id, code, timeout=None) -> ExecResult:
        return ExecResult(status="ok", stdout=f"ran:{code}")

    def put_file(self, session_id, dest_path, data) -> None:
        self.files.setdefault(session_id, {})[dest_path] = data

    def get_file(self, session_id, path) -> bytes:
        return self.files[session_id][path]

    def list_files(self, session_id) -> List[str]:
        return list(self.files.get(session_id, {}).keys())

    def remove_path(self, session_id, path) -> None:
        self.removed.append((session_id, path))
        files = self.files.get(session_id, {})
        for key in [k for k in files if k == path or k.startswith(path + "/")]:
            files.pop(key, None)

    @property
    def torn_down(self) -> List[str]:
        """Session ids torn down via either close path, in teardown order."""
        return self.closed + [sid for sid, _ in self.closed_handles]


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


def test_open_registers_session_and_opens_backend(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    handle = mgr.open("conv-1")
    assert handle.startswith("handle-conv-1")
    assert backend.open_calls == ["conv-1"]
    assert mgr.has_session("conv-1")


def test_open_twice_reuses_cached_handle_without_backend_io(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    h1 = mgr.open("conv-1")
    h2 = mgr.open("conv-1")
    assert backend.open_calls == ["conv-1"]  # opened once
    # Reuse returns the cached handle WITHOUT any backend I/O (no second open/attach):
    # backend calls must never run while the manager lock is held.
    assert backend.attach_calls == []
    assert h1 == h2


def test_attach_reuse_requires_existing_session(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    with pytest.raises(KeyError):
        mgr.attach("missing")
    mgr.open("conv-1")
    # attach returns the cached handle without backend I/O.
    assert mgr.attach("conv-1").startswith("handle-conv-1")
    assert backend.attach_calls == []


def test_ttl_clamped_to_max(backend):
    mgr = SandboxManager(backend, max_ttl=300)
    mgr.open("conv-1", ttl=99999)
    assert mgr.ttl_for("conv-1") == 300


def test_ttl_honored_when_below_max(backend):
    mgr = SandboxManager(backend, max_ttl=300)
    mgr.open("conv-1", ttl=120)
    assert mgr.ttl_for("conv-1") == 120


def test_reuse_extends_ttl_but_never_shrinks(backend):
    # A tool (e.g. artifact_generator) may open the shared session at the short
    # exec timeout; a later run_code(persist, ttl=...) reuses it and must be able
    # to extend the keep-alive, or the kernel + background state are reaped early.
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1", ttl=60)
    assert mgr.ttl_for("conv-1") == 60
    mgr.open("conv-1", ttl=600)  # reuse: explicit longer ttl extends
    assert mgr.ttl_for("conv-1") == 600
    mgr.open("conv-1", ttl=120)  # reuse: shorter ttl must not shrink
    assert mgr.ttl_for("conv-1") == 600
    mgr.open("conv-1")  # reuse: default (ttl=None) leaves it untouched
    assert mgr.ttl_for("conv-1") == 600
    assert backend.open_calls == ["conv-1"]  # still opened only once


def test_ttl_default_used_for_nonpositive(backend):
    mgr = SandboxManager(backend, max_ttl=300, default_ttl=200)
    mgr.open("conv-1", ttl=0)
    assert mgr.ttl_for("conv-1") == 200
    mgr.open("conv-2", ttl=-5)
    assert mgr.ttl_for("conv-2") == 200


def test_close_drops_registry_and_backend(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    mgr.close("conv-1")
    assert not mgr.has_session("conv-1")
    assert backend.torn_down == ["conv-1"]


def test_reap_expired_closes_idle_sessions(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=100)
    mgr.open("conv-1", ttl=50)
    clock["t"] = 1051.0  # 51s idle > 50s ttl
    reaped = mgr.reap_expired()
    assert reaped == ["conv-1"]
    assert backend.torn_down == ["conv-1"]
    assert not mgr.has_session("conv-1")


def test_exec_and_file_roundtrip_through_manager(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    res = mgr.exec("conv-1", "1+1")
    assert res.ok and res.stdout == "ran:1+1"
    mgr.put_file("conv-1", "a.txt", b"hello")
    assert mgr.get_file("conv-1", "a.txt") == b"hello"
    assert mgr.list_files("conv-1") == ["a.txt"]


def test_runtime_invalidation_drops_cached_handle_and_next_open_is_cold():
    """A backend-killed runtime must not remain reusable in the manager cache."""

    class _InvalidatingBackend(FakeBackend):
        def exec(self, session_id, code, timeout=None):
            self._handles.pop(session_id, None)
            return ExecResult(
                status="error",
                error_name="TimeoutError",
                error_value="execution exceeded its deadline",
                exit_code=-1,
                runtime_invalidated=True,
            )

    backend = _InvalidatingBackend()
    mgr = SandboxManager(backend, max_ttl=600)
    old_handle = mgr.open("conv-1")

    result = mgr.exec("conv-1", "while True: pass", timeout=1)

    assert result.runtime_invalidated is True
    assert not mgr.has_session("conv-1")
    new_handle = mgr.open("conv-1")
    assert new_handle != old_handle
    assert backend.open_calls == ["conv-1", "conv-1"]
    assert backend.closed_handles == []  # the backend already destroyed the invalid runtime


def test_old_file_operation_cannot_release_reopened_session_after_invalidation():
    """A stale operation's leave must not decrement a replacement session generation."""

    class _BlockedReadInvalidatingBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.read_started = threading.Event()
            self.release_read = threading.Event()

        def get_file(self, session_id, path):
            self.read_started.set()
            assert self.release_read.wait(timeout=5)
            return b"old-generation"

        def exec(self, session_id, code, timeout=None):
            self._handles.pop(session_id, None)
            return ExecResult(status="error", error_name="TimeoutError", runtime_invalidated=True)

    backend = _BlockedReadInvalidatingBackend()
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    read_result: Dict[str, bytes] = {}
    reader = threading.Thread(
        target=lambda: read_result.__setitem__("data", mgr.get_file("conv-1", "old.txt"))
    )
    reader.start()
    assert backend.read_started.wait(timeout=5)

    mgr.exec("conv-1", "while True: pass", timeout=1)
    assert not mgr.has_session("conv-1")
    mgr.open("conv-1")
    replacement = mgr._enter("conv-1")

    backend.release_read.set()
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert read_result == {"data": b"old-generation"}
    assert replacement.in_use == 1

    # Closing is still deferred for the replacement's genuine hold. A stale
    # unguarded leave would have decremented it to zero and closed immediately.
    mgr.close("conv-1")
    assert mgr.has_session("conv-1")
    mgr._leave("conv-1", expected=replacement)
    assert not mgr.has_session("conv-1")


def test_file_ops_require_open_session(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    with pytest.raises(KeyError):
        mgr.get_file("missing", "a.txt")


def test_sandbox_creator_selects_jupyter_backend(monkeypatch):
    from application.sandbox import sandbox_creator as sc

    sc.SandboxCreator.reset()
    backend = sc.SandboxCreator.create_backend("jupyter")
    from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox

    assert isinstance(backend, JupyterKernelGatewaySandbox)


def test_sandbox_creator_unknown_backend_raises():
    from application.sandbox.sandbox_creator import SandboxCreator

    with pytest.raises(ValueError):
        SandboxCreator.create_backend("does-not-exist")


def test_sandbox_creator_manager_is_singleton():
    from application.sandbox.sandbox_creator import SandboxCreator

    SandboxCreator.reset()
    m1 = SandboxCreator.get_manager()
    m2 = SandboxCreator.get_manager()
    assert m1 is m2
    SandboxCreator.reset()


def test_sandbox_creator_peek_manager_never_builds():
    from application.sandbox.sandbox_creator import SandboxCreator

    SandboxCreator.reset()
    assert SandboxCreator.peek_manager() is None  # nothing built yet -> None, no construction
    built = SandboxCreator.get_manager()
    assert SandboxCreator.peek_manager() is built  # returns the existing singleton
    SandboxCreator.reset()
    assert SandboxCreator.peek_manager() is None


# ---------------------------------------------------------------------------
# Concurrent-session cap
# ---------------------------------------------------------------------------


def test_open_under_cap_does_not_evict(backend):
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=3)
    mgr.open("a")
    mgr.open("b")
    assert backend.torn_down == []
    assert mgr.session_count() == 2


def test_cap_evicts_lru_idle_session(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=2)
    mgr.open("a")  # last_access 1000
    clock["t"] = 1001.0
    mgr.open("b")  # last_access 1001
    clock["t"] = 1002.0
    mgr.open("c")  # at cap -> evict LRU-idle = "a"
    assert backend.torn_down == ["a"]
    assert not mgr.has_session("a")
    assert mgr.has_session("b") and mgr.has_session("c")
    assert mgr.session_count() == 2


def test_cap_eviction_picks_least_recently_used(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=2)
    mgr.open("a")
    clock["t"] = 1001.0
    mgr.open("b")
    clock["t"] = 1002.0
    mgr.exec("a", "noop")  # refresh "a" so "b" is now the LRU
    clock["t"] = 1003.0
    mgr.open("c")
    assert backend.torn_down == ["b"]
    assert mgr.has_session("a") and mgr.has_session("c")


def test_cap_rejects_when_all_sessions_busy(backend):
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=1)
    mgr.open("a")
    # Hold "a" in-use; a concurrent open of "b" then cannot free a slot.
    mgr._enter("a")
    try:
        with pytest.raises(SandboxCapacityError):
            mgr.open("b")
    finally:
        mgr._leave("a")
    # Once released, opening succeeds (evicting the now-idle "a").
    mgr.open("b")
    assert mgr.has_session("b")


def test_reuse_existing_session_never_evicts_at_cap(backend):
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=1)
    mgr.open("a")
    mgr.open("a")  # reuse, not a new session -> no eviction
    assert backend.torn_down == []
    assert mgr.session_count() == 1


def test_concurrent_open_same_id_does_not_evict_innocent():
    """A 2nd open() of an id mid cold-open reuses its placeholder, never evicts another session.

    The session_id is derived from conversation/run id, so two concurrent requests on
    one conversation both call open(same_id). The second must NOT see the first's
    not-yet-ready placeholder as a reason to make room (evict an innocent LRU-idle
    session or raise SandboxCapacityError) -- overwriting the same key adds no slot.
    """
    state = {"entries": 0}
    both_in_backend = threading.Event()
    release = threading.Event()
    guard = threading.Lock()

    class _BlockingSameId(FakeBackend):
        def open(self, session_id: str) -> str:
            if session_id == "slow":
                with guard:
                    state["entries"] += 1
                    if state["entries"] >= 2:
                        both_in_backend.set()
                assert release.wait(timeout=5)
            return super().open(session_id)

    backend = _BlockingSameId()
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=2)
    mgr.open("keep")  # a ready, idle session occupying one of the two slots

    t1 = threading.Thread(target=lambda: mgr.open("slow"))
    t1.start()
    # Wait until t1 has registered the "slow" placeholder and is blocked in backend.open
    # (registry is now {keep, slow} = at cap).
    deadline = time.monotonic() + 5
    while mgr.session_count() < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert mgr.session_count() == 2

    t2 = threading.Thread(target=lambda: mgr.open("slow"))
    t2.start()
    try:
        # Both opens have passed the lock section into backend.open. With the bug, t2
        # would have evicted "keep" in its lock section before reaching here.
        assert both_in_backend.wait(timeout=5)
        assert mgr.has_session("keep"), "concurrent same-id open evicted an innocent session"
        assert "keep" not in backend.torn_down
    finally:
        release.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
    assert mgr.has_session("slow") and mgr.has_session("keep")


# ---------------------------------------------------------------------------
# Idle reaper
# ---------------------------------------------------------------------------


def test_reap_closes_idle_past_ttl_and_keeps_fresh(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("stale", ttl=50)
    clock["t"] = 1040.0
    mgr.open("fresh", ttl=50)  # last_access 1040
    clock["t"] = 1051.0  # stale idle 51s > 50; fresh idle 11s < 50
    reaped = mgr.reap_expired()
    assert reaped == ["stale"]
    assert backend.torn_down == ["stale"]
    assert mgr.has_session("fresh")


def test_reap_leaves_busy_session_even_if_expired(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("busy", ttl=10)
    mgr._enter("busy")  # mark in-use (e.g. a long exec in flight)
    clock["t"] = 1100.0  # well past TTL
    try:
        assert mgr.reap_expired() == []
        assert mgr.has_session("busy")
        assert backend.torn_down == []
    finally:
        mgr._leave("busy")


# ---------------------------------------------------------------------------
# Workspace cleanup
# ---------------------------------------------------------------------------


def test_remove_path_delegates_to_backend(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("a")
    mgr.put_file("a", "artifacts/tok/out.pptx", b"x")
    mgr.remove_path("a", "artifacts/tok")
    assert backend.removed == [("a", "artifacts/tok")]
    assert mgr.list_files("a") == []


def test_remove_path_unknown_session_is_silent(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.remove_path("missing", "artifacts/tok")  # must not raise
    assert backend.removed == []


def test_remove_path_via_exec_when_backend_lacks_helper():
    class _NoRemoveBackend(FakeBackend):
        remove_path = None  # type: ignore[assignment]

        def __init__(self):
            super().__init__()
            self.exec_programs: List[str] = []

        def exec(self, session_id, code, timeout=None):
            self.exec_programs.append(code)
            return ExecResult(status="ok")

    backend = _NoRemoveBackend()
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("a")
    mgr.remove_path("a", "artifacts/tok")
    assert any("shutil.rmtree" in code for code in backend.exec_programs)


def test_remove_via_exec_program_guards_workspace_root():
    """The exec-fallback program must refuse to rmtree the workspace root ('', '.', './')."""

    class _NoRemoveBackend(FakeBackend):
        remove_path = None  # type: ignore[assignment]

        def __init__(self):
            super().__init__()
            self.exec_programs: List[str] = []

        def exec(self, session_id, code, timeout=None):
            self.exec_programs.append(code)
            return ExecResult(status="ok")

    backend = _NoRemoveBackend()
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("a")
    program = mgr._build_remove_program(".")
    # Run the generated guard program in-process against a sandbox dir; a '.' path
    # must be a no-op (root guard), never rmtree the cwd.
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        keep = os.path.join(tmp, "keep.txt")
        with open(keep, "w") as fh:
            fh.write("x")
        cwd = os.getcwd()
        os.chdir(tmp)
        try:
            exec(compile(program, "<guard>", "exec"), {})
        finally:
            os.chdir(cwd)
        assert os.path.exists(keep), "root-guard let '.' delete the workspace"
    # And empty/'./' are likewise refused.
    for bad in ("", "./", "."):
        assert "os.path.normpath(_p) != '.'" in mgr._build_remove_program(bad)


# ---------------------------------------------------------------------------
# Thread-safety smoke
# ---------------------------------------------------------------------------


def test_concurrent_open_close_stays_consistent(backend):
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=8)
    errors: List[Exception] = []

    def churn(i: int) -> None:
        try:
            for n in range(50):
                sid = f"s-{i}-{n % 4}"
                try:
                    mgr.open(sid)
                    mgr.exec(sid, "x")
                except SandboxCapacityError:
                    # capacity is expected under churn; skip this session
                    pass
                mgr.reap_expired()
                mgr.close(sid)
        except Exception as exc:  # noqa: BLE001 - surface any thread error to the assertion
            errors.append(exc)

    threads = [threading.Thread(target=churn, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert mgr.session_count() <= 8


# ---------------------------------------------------------------------------
# Concurrency: lock must never be held across a blocking backend call
# ---------------------------------------------------------------------------


def test_lock_not_held_across_blocking_open():
    """While a cold backend.open blocks, other lock-taking methods return promptly."""

    class _BlockingOpenBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.entered_open = threading.Event()
            self.release_open = threading.Event()

        def open(self, session_id: str) -> str:
            if session_id == "slow":
                self.entered_open.set()
                # Block here as if cold-starting a kernel/sandbox (network I/O ~60s).
                assert self.release_open.wait(timeout=5)
            return super().open(session_id)

    backend = _BlockingOpenBackend()
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=8)

    opener = threading.Thread(target=lambda: mgr.open("slow"))
    opener.start()
    try:
        # Wait until the backend open is in flight (lock already released by design).
        assert backend.entered_open.wait(timeout=5)

        # These take the manager lock; if the lock were held across backend.open they
        # would block for the full 5s. They must return effectively immediately.
        results: dict = {}

        def probe() -> None:
            results["count"] = mgr.session_count()
            results["has_other"] = mgr.has_session("other")
            # A second open for a DIFFERENT id must also make progress (reserve + open).
            results["other_handle"] = mgr.open("other")

        prober = threading.Thread(target=probe)
        prober.start()
        prober.join(timeout=3)
        assert not prober.is_alive(), "lock was held across backend.open (probe blocked)"
        assert results["count"] >= 1  # the reserved "slow" placeholder counts
        assert results["has_other"] is False
        assert results["other_handle"].startswith("handle-other")
    finally:
        backend.release_open.set()
        opener.join(timeout=5)
    assert mgr.has_session("slow")


# ---------------------------------------------------------------------------
# Concurrency: eviction closes the captured resource, never a re-opened one
# ---------------------------------------------------------------------------


def test_evict_then_concurrent_reopen_closes_old_handle_not_new():
    """Evicting V and concurrently re-opening V must tear down V's OLD handle, not the new one."""

    class _SlowCloseBackend(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.block_handle = None  # only this exact handle's close blocks
            self.close_started = threading.Event()
            self.release_close = threading.Event()

        def close_handle(self, session_id: str, handle: str) -> None:
            if handle == self.block_handle:
                self.close_started.set()
                # Hold the deferred close open so a concurrent open(V) lands first.
                assert self.release_close.wait(timeout=5)
            super().close_handle(session_id, handle)

    backend = _SlowCloseBackend()
    # cap=2: one slot pinned by a busy filler, one free slot the eviction/reopen contend over.
    mgr = SandboxManager(backend, max_ttl=600, max_sessions=2)

    mgr.open("U")
    mgr._enter("U")  # pin U busy so it is never the eviction victim
    old_handle = mgr.open("V")  # the victim's original handle (free slot)
    backend.block_handle = old_handle  # only V's OLD handle's close will block

    # open("W") is at cap -> evicts idle "V"; its deferred close_handle(V, old) blocks.
    evictor = threading.Thread(target=lambda: mgr.open("W"))
    evictor.start()
    assert backend.close_started.wait(timeout=5)  # eviction close of V's old handle is in flight

    # At this point W holds the free slot as a placeholder. Free it for the reopen by
    # letting the evicting open finish its own backend.open; W then occupies the slot.
    # To re-open V we must first release U so the cap has room.
    mgr._leave("U")

    # Re-open V WHILE its old handle's close is still blocked: a brand-new handle.
    new_handle = mgr.open("V")
    assert new_handle != old_handle

    # Now let the deferred close of the OLD handle complete.
    backend.release_close.set()
    evictor.join(timeout=5)

    # The OLD handle was the one closed; the NEW handle for V survives intact.
    assert (("V", old_handle) in backend.closed_handles)
    assert (("V", new_handle) not in backend.closed_handles)
    assert backend._handles.get("V") == new_handle  # registry still points at the new one
    assert mgr.has_session("V")
    # The new V is usable (its workspace was not torn down by the stale close).
    mgr.put_file("V", "f.txt", b"data")
    assert mgr.get_file("V", "f.txt") == b"data"


# ---------------------------------------------------------------------------
# Deferred close: a close while an op is in-use must not kill the in-flight op
# ---------------------------------------------------------------------------


def test_close_defers_while_in_use_then_tears_down_on_leave(backend):
    """close() during an in-flight op defers teardown; the last _leave performs it."""
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    mgr._enter("conv-1")  # simulate a concurrent exec holding the session

    mgr.close("conv-1")  # must DEFER, not tear the session out from under the op
    assert mgr.has_session("conv-1")
    assert backend.torn_down == []

    mgr._leave("conv-1")  # last release performs the deferred close
    assert not mgr.has_session("conv-1")
    assert backend.torn_down == ["conv-1"]


def test_close_defers_until_last_of_several_holds_releases(backend):
    """With multiple in-use holds, the deferred close fires only on the final _leave."""
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    mgr._enter("conv-1")
    mgr._enter("conv-1")
    mgr.close("conv-1")

    mgr._leave("conv-1")  # one hold remains -> still deferred
    assert mgr.has_session("conv-1")
    assert backend.torn_down == []

    mgr._leave("conv-1")  # last hold -> deferred close runs
    assert not mgr.has_session("conv-1")
    assert backend.torn_down == ["conv-1"]


def test_close_is_synchronous_when_not_in_use(backend):
    """The common path (in_use == 0 at close time) stays synchronous as before."""
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    mgr.close("conv-1")  # caller's own exec already _left -> immediate teardown
    assert not mgr.has_session("conv-1")
    assert backend.torn_down == ["conv-1"]


def test_exec_completes_despite_concurrent_close():
    """A close racing an in-flight exec never turns it into a KernelDiedError/lost files."""
    barrier = threading.Event()
    release = threading.Event()

    class _BlockingExecBackend(FakeBackend):
        def exec(self, session_id, code, timeout=None):
            barrier.set()
            assert release.wait(timeout=5)
            return ExecResult(status="ok", stdout=f"ran:{code}")

    backend = _BlockingExecBackend()
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")

    out: Dict[str, ExecResult] = {}
    worker = threading.Thread(target=lambda: out.__setitem__("r", mgr.exec("conv-1", "1+1")))
    worker.start()
    assert barrier.wait(timeout=5)  # exec is in flight, holding the session in-use

    mgr.close("conv-1")  # concurrent close must defer, not tear down the live exec
    assert backend.torn_down == []

    release.set()
    worker.join(timeout=5)
    assert out["r"].ok and out["r"].stdout == "ran:1+1"  # exec survived intact
    # The deferred close ran on the exec's own _leave.
    assert not mgr.has_session("conv-1")
    assert backend.torn_down == ["conv-1"]
