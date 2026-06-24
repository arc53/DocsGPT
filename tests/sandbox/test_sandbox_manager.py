"""Unit tests for SandboxManager and SandboxCreator using an in-memory backend."""

from typing import Dict, List

import pytest

from application.sandbox.base import CodeSandbox, ExecResult
from application.sandbox.manager import SandboxManager


class FakeBackend(CodeSandbox):
    """In-memory backend recording calls; no network, fully deterministic."""

    def __init__(self) -> None:
        self.open_calls: List[str] = []
        self.attach_calls: List[str] = []
        self.closed: List[str] = []
        self.files: Dict[str, Dict[str, bytes]] = {}
        self._handles: Dict[str, str] = {}

    def open(self, session_id: str) -> str:
        self.open_calls.append(session_id)
        self.files.setdefault(session_id, {})
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

    def exec(self, session_id, code, timeout=None) -> ExecResult:
        return ExecResult(status="ok", stdout=f"ran:{code}")

    def put_file(self, session_id, dest_path, data) -> None:
        self.files.setdefault(session_id, {})[dest_path] = data

    def get_file(self, session_id, path) -> bytes:
        return self.files[session_id][path]

    def list_files(self, session_id) -> List[str]:
        return list(self.files.get(session_id, {}).keys())


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


def test_open_registers_session_and_opens_backend(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    handle = mgr.open("conv-1")
    assert handle.startswith("handle-conv-1")
    assert backend.open_calls == ["conv-1"]
    assert mgr.has_session("conv-1")


def test_open_twice_reuses_via_attach(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    mgr.open("conv-1")
    assert backend.open_calls == ["conv-1"]  # opened once
    assert backend.attach_calls == ["conv-1"]  # second open reused via attach


def test_attach_reuse_requires_existing_session(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    with pytest.raises(KeyError):
        mgr.attach("missing")
    mgr.open("conv-1")
    assert mgr.attach("conv-1").startswith("handle-conv-1")


def test_ttl_clamped_to_max(backend):
    mgr = SandboxManager(backend, max_ttl=300)
    mgr.open("conv-1", ttl=99999)
    assert mgr.ttl_for("conv-1") == 300


def test_ttl_honored_when_below_max(backend):
    mgr = SandboxManager(backend, max_ttl=300)
    mgr.open("conv-1", ttl=120)
    assert mgr.ttl_for("conv-1") == 120


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
    assert backend.closed == ["conv-1"]


def test_reap_expired_closes_idle_sessions(backend, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr("application.sandbox.manager.time.monotonic", lambda: clock["t"])
    mgr = SandboxManager(backend, max_ttl=100)
    mgr.open("conv-1", ttl=50)
    clock["t"] = 1051.0  # 51s idle > 50s ttl
    reaped = mgr.reap_expired()
    assert reaped == ["conv-1"]
    assert backend.closed == ["conv-1"]
    assert not mgr.has_session("conv-1")


def test_exec_and_file_roundtrip_through_manager(backend):
    mgr = SandboxManager(backend, max_ttl=600)
    mgr.open("conv-1")
    res = mgr.exec("conv-1", "1+1")
    assert res.ok and res.stdout == "ran:1+1"
    mgr.put_file("conv-1", "a.txt", b"hello")
    assert mgr.get_file("conv-1", "a.txt") == b"hello"
    assert mgr.list_files("conv-1") == ["a.txt"]


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
