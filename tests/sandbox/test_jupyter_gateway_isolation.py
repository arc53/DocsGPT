"""Per-session isolation hardening for the Jupyter gateway sandbox.

Covers the env-scrubbing kernel launcher (`deployment/sandbox/kernel-launch.sh`)
and the `0700` per-session workspace perms applied by `_prime`. Hermetic: the
launcher test runs the wrapper with a fake `python` on PATH, and the `_prime`
test executes the wrapper's setup code against a real temp directory by
stubbing `_run` -- no gateway / kernel process required.
"""

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from application.sandbox import jupyter_gateway
from application.sandbox.base import ExecResult
from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox, _Kernel

_SANDBOX_DIR = Path(__file__).resolve().parents[2] / "deployment" / "sandbox"
_WRAPPER = _SANDBOX_DIR / "kernel-launch.sh"
_KERNEL_NAME = "docsgpt-python"
_KERNELSPEC = _SANDBOX_DIR / "kernels" / _KERNEL_NAME / "kernel.json"


# -- Env-scrubbing kernel launcher ---------------------------------------------


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_kernel_launch_scrubs_secrets_keeps_runtime_env(tmp_path):
    """The wrapper drops *_API_KEY/*_TOKEN but keeps PATH/HOME/JUPYTER_* for ipykernel."""
    # Fake `python` on PATH: ignore `-m ipykernel_launcher` and dump the env it was given.
    fake_python = tmp_path / "python"
    fake_python.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            env
            """
        )
    )
    fake_python.chmod(0o755)

    env = {
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "JUPYTER_RUNTIME_DIR": str(tmp_path / "runtime"),
        "JUPYTER_DATA_DIR": str(tmp_path / "data"),
        # Secrets that must NOT reach the kernel.
        "OPENAI_API_KEY": "sk-super-secret",
        "SANDBOX_GATEWAY_AUTH_TOKEN": "gateway-token",
        "POSTGRES_URI": "postgresql://u:p@h/db",
    }
    proc = subprocess.run(
        ["sh", str(_WRAPPER), "-f", "/tmp/conn.json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    # Secrets stripped.
    assert "OPENAI_API_KEY" not in out
    assert "sk-super-secret" not in out
    assert "SANDBOX_GATEWAY_AUTH_TOKEN" not in out
    assert "POSTGRES_URI" not in out
    # Allowlisted runtime env kept.
    assert "PATH=" in out
    assert f"HOME={tmp_path}" in out
    assert f"JUPYTER_RUNTIME_DIR={tmp_path / 'runtime'}" in out
    assert f"JUPYTER_DATA_DIR={tmp_path / 'data'}" in out
    # The connection-file args were forwarded to ipykernel (reachability preserved).
    # The fake python prints env only, so just assert it was invoked with no crash above.


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_kernel_launch_is_valid_sh():
    """The wrapper parses under POSIX sh (`sh -n`)."""
    proc = subprocess.run(["sh", "-n", str(_WRAPPER)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# -- Scrubbing kernelspec is selectable ----------------------------------------


def test_kernelspec_argv_points_at_scrubbing_wrapper():
    """The shipped kernel.json launches the env-scrubbing wrapper, not bare ipykernel."""
    spec = json.loads(_KERNELSPEC.read_text())
    argv = spec["argv"]
    assert argv[0].endswith("kernel-launch.sh")
    assert "{connection_file}" in argv


def test_distinct_kernel_name_resolves_to_scrubbing_spec(tmp_path, monkeypatch):
    """A distinct kernel name resolves to the scrubbing wrapper (never the stock python3 spec)."""
    kernelspec = pytest.importorskip("jupyter_client.kernelspec")

    # Seed a Jupyter data dir with the custom spec under its distinct name.
    data_dir = tmp_path / "jupyter"
    spec_dir = data_dir / "kernels" / _KERNEL_NAME
    spec_dir.mkdir(parents=True)
    shutil.copy(_KERNELSPEC, spec_dir / "kernel.json")
    monkeypatch.setenv("JUPYTER_PATH", str(data_dir))

    manager = kernelspec.KernelSpecManager()
    resolved = manager.get_kernel_spec(_KERNEL_NAME)
    assert resolved.argv[0].endswith("kernel-launch.sh")
    assert "{connection_file}" in resolved.argv


# -- Per-session workspace perms (0700) ----------------------------------------


def _exec_setup_in_tmp(code: str) -> None:
    """Run the kernel-side setup snippet in-process (it is plain os.* calls)."""
    exec(compile(code, "<setup>", "exec"), {})


def test_prime_creates_workspace_mode_0700(tmp_path, monkeypatch):
    """`_prime` creates the workspace root and per-session dir at mode 0700."""
    root = tmp_path / "docsgpt-sandbox"
    monkeypatch.setattr(jupyter_gateway, "_WORKSPACE_ROOT", str(root))

    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    workspace = f"{root}/conv-perms"
    kernel = _Kernel("kid", workspace)

    captured = {}

    def fake_run(_kernel, code, _timeout):
        captured["code"] = code
        _exec_setup_in_tmp(code)
        return ExecResult(status="ok", exit_code=0)

    monkeypatch.setattr(sb, "_run", fake_run)
    monkeypatch.chdir(tmp_path)  # _prime's os.chdir must land somewhere harmless
    sb._prime(kernel)

    assert kernel.initialized
    assert stat.S_IMODE(os.stat(root).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(workspace).st_mode) == 0o700


# -- Output cap: rich outputs count against the byte budget --------------------


def test_rich_payload_bytes_sums_all_data():
    content = {"data": {"text/html": "x" * 100, "text/plain": "y" * 50, "application/json": {"a": 1}}}
    n = JupyterKernelGatewaySandbox._rich_payload_bytes(content)
    assert n >= 150  # html + plain + serialized json all counted


def _frame(msg_id, msg_type, content):
    return json.dumps({"parent_header": {"msg_id": msg_id}, "msg_type": msg_type, "content": content})


class _FakeWS:
    def __init__(self, frames):
        self._frames = list(frames)

    def settimeout(self, _t):
        pass

    def recv(self):
        if self._frames:
            return self._frames.pop(0)
        import websocket

        raise websocket.WebSocketConnectionClosedException()


class _TimeoutWS:
    """A channel that never yields another frame, even after an interrupt."""

    def settimeout(self, _t):
        pass

    def recv(self):
        import websocket

        raise websocket.WebSocketTimeoutException()


class _TimeoutThenIdleWS:
    """Reach the exec deadline, then report matching idle after the interrupt."""

    def __init__(self, msg_id):
        self._msg_id = msg_id
        self._calls = 0

    def settimeout(self, _t):
        pass

    def recv(self):
        import websocket

        self._calls += 1
        if self._calls == 1:
            raise websocket.WebSocketTimeoutException()
        return _frame(self._msg_id, "status", {"execution_state": "idle"})


def test_timeout_deletes_and_invalidates_kernel_when_interrupt_never_idles(monkeypatch):
    """A kernel that catches the interrupt cannot outlive the execution deadline."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    kernel = _Kernel("stuck-kernel", "/tmp/stuck")
    sb._kernels["session-stuck"] = kernel
    interrupted = []
    deleted = []
    monkeypatch.setattr(sb, "_interrupt", lambda kernel_id: interrupted.append(kernel_id))
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: deleted.append(kernel_id) or True)

    result = sb._collect(
        _TimeoutWS(),
        "timed-out-message",
        timeout=5,
        kernel_id=kernel.kernel_id,
    )

    assert result.error_name == "TimeoutError"
    assert result.runtime_invalidated is True
    assert interrupted == [kernel.kernel_id]
    assert deleted == [kernel.kernel_id]
    assert "session-stuck" not in sb._kernels


def test_timeout_keeps_kernel_when_interrupt_reaches_matching_idle(monkeypatch):
    """A confirmed-idle interrupted kernel remains reusable and is not deleted."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    kernel = _Kernel("reusable-kernel", "/tmp/reusable")
    sb._kernels["session-reusable"] = kernel
    interrupted = []
    deleted = []
    monkeypatch.setattr(sb, "_interrupt", lambda kernel_id: interrupted.append(kernel_id))
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: deleted.append(kernel_id) or True)
    msg_id = "timed-out-message"

    result = sb._collect(
        _TimeoutThenIdleWS(msg_id),
        msg_id,
        timeout=5,
        kernel_id=kernel.kernel_id,
    )

    assert result.error_name == "TimeoutError"
    assert result.runtime_invalidated is False
    assert interrupted == [kernel.kernel_id]
    assert deleted == []
    assert sb._kernels["session-reusable"] is kernel


def test_timeout_invalidation_does_not_remove_replacement_kernel(monkeypatch):
    """Late cleanup of an old timeout must leave a newly opened generation registered."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    old = _Kernel("old-kernel", "/tmp/old")
    replacement = _Kernel("new-kernel", "/tmp/new")
    sb._kernels["session-race"] = old
    deleted = []

    def replace_during_drain(*_args):
        sb._kernels["session-race"] = replacement
        return False

    monkeypatch.setattr(sb, "_interrupt_and_drain", replace_during_drain)
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: deleted.append(kernel_id) or True)

    result = sb._collect(
        _TimeoutWS(),
        "timed-out-message",
        timeout=5,
        kernel_id=old.kernel_id,
    )

    assert result.runtime_invalidated is True
    assert deleted == [old.kernel_id]
    assert sb._kernels["session-race"] is replacement


def test_failed_replacement_race_quarantine_does_not_block_unrelated_open(monkeypatch):
    """A failed old-id DELETE remains scoped to its original session."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    old = _Kernel("old-kernel", "/tmp/old", "session-race")
    replacement = _Kernel("new-kernel", "/tmp/new", "session-race")

    def replace_during_drain(*_args):
        sb._kernels["session-race"] = replacement
        return False

    class _Response:
        status_code = 201

        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "unrelated-kernel"}

    monkeypatch.setattr(sb, "_interrupt_and_drain", replace_during_drain)
    monkeypatch.setattr(sb, "_delete_kernel", lambda _kernel_id: False)
    monkeypatch.setattr(jupyter_gateway.requests, "post", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(sb, "_prime", lambda _kernel: None)

    result = sb._collect(
        _TimeoutWS(),
        "timed-out-message",
        timeout=5,
        kernel_id=old.kernel_id,
        session_id=old.session_id,
    )

    assert result.runtime_invalidated is True
    assert sb._quarantined_kernels == {old.kernel_id: "session-race"}
    assert sb.open("unrelated") == "unrelated-kernel"
    assert sb._kernels["session-race"] is replacement
    assert sb._quarantined_kernels == {old.kernel_id: "session-race"}


def test_delete_kernel_retries_transient_http_failure(monkeypatch):
    """A transient gateway failure gets one more termination attempt."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    statuses = iter((500, 204))
    calls = []

    class _Response:
        def __init__(self, status_code):
            self.status_code = status_code

    def fake_delete(url, **_kwargs):
        calls.append(url)
        return _Response(next(statuses))

    monkeypatch.setattr(jupyter_gateway.requests, "delete", fake_delete)

    assert sb._delete_kernel("stuck-kernel") is True
    assert calls == [
        "http://unused/api/kernels/stuck-kernel",
        "http://unused/api/kernels/stuck-kernel",
    ]


def test_delete_kernel_reports_failure_after_both_attempts(monkeypatch, caplog):
    """Two non-success responses leave termination explicitly unconfirmed."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    statuses = iter((500, 503))
    calls = []

    class _Response:
        def __init__(self, status_code):
            self.status_code = status_code

    def fake_delete(url, **_kwargs):
        calls.append(url)
        return _Response(next(statuses))

    monkeypatch.setattr(jupyter_gateway.requests, "delete", fake_delete)

    assert sb._delete_kernel("stuck-kernel") is False
    assert len(calls) == 2
    assert "Failed to delete kernel stuck-kernel after retry: HTTP 503" in caplog.text


def test_failed_timeout_delete_is_quarantined_and_cold_open_fails_closed(monkeypatch):
    """An undeletable runaway remains retryable and blocks a duplicate cold kernel."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    kernel = _Kernel("stuck-kernel", "/tmp/stuck")
    sb._kernels["session-stuck"] = kernel
    delete_calls = []
    post_calls = []
    monkeypatch.setattr(sb, "_interrupt", lambda _kernel_id: None)
    monkeypatch.setattr(
        sb,
        "_delete_kernel",
        lambda kernel_id: (delete_calls.append(kernel_id), False)[1],
    )
    monkeypatch.setattr(
        jupyter_gateway.requests,
        "post",
        lambda *args, **kwargs: post_calls.append((args, kwargs)),
    )

    result = sb._collect(
        _TimeoutWS(), "timed-out-message", timeout=5, kernel_id=kernel.kernel_id
    )

    assert result.runtime_invalidated is True
    assert "session-stuck" not in sb._kernels
    assert sb._quarantined_kernels == {kernel.kernel_id: "session-stuck"}
    with pytest.raises(RuntimeError, match="could not be terminated"):
        sb.open("session-stuck")
    assert delete_calls == [kernel.kernel_id, kernel.kernel_id]
    assert post_calls == []
    assert sb._quarantined_kernels == {kernel.kernel_id: "session-stuck"}


def test_cached_replacement_retries_old_quarantine_without_touching_replacement(monkeypatch):
    """Cached-session traffic retires only the old immutable kernel id."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    replacement = _Kernel("replacement-kernel", "/tmp/replacement")
    sb._kernels["session-race"] = replacement
    sb._quarantined_kernels["old-kernel"] = "session-race"
    deleted = []
    monkeypatch.setattr(
        sb,
        "_delete_kernel",
        lambda kernel_id: (deleted.append(kernel_id), True)[1],
    )

    assert sb._get_kernel("session-race") is replacement
    assert deleted == ["old-kernel"]
    assert sb._quarantined_kernels == {}
    assert sb._kernels["session-race"] is replacement


def test_collect_caps_oversize_rich_output(monkeypatch):
    # A huge execute_result must NOT be buffered: once it would exceed the byte
    # budget the bundle is dropped and the result is marked truncated.
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused", max_output_bytes=1000)
    monkeypatch.setattr(sb, "_interrupt_and_drain", lambda *a, **k: None)
    msg_id = "m1"
    frames = [_frame(msg_id, "execute_result", {"data": {"text/html": "H" * 5000}})]
    result = sb._collect(_FakeWS(frames), msg_id, timeout=5, kernel_id="k1")
    assert result.results == []  # over-budget bundle dropped, not materialized
    assert "[output truncated" in result.stderr
    assert result.truncated is True  # truncation is surfaced explicitly, not hidden behind "ok"


def test_collect_keeps_small_rich_output(monkeypatch):
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused", max_output_bytes=10000)
    monkeypatch.setattr(sb, "_interrupt_and_drain", lambda *a, **k: None)
    msg_id = "m2"
    frames = [
        _frame(msg_id, "execute_result", {"data": {"text/plain": "small"}}),
        _frame(msg_id, "execute_reply", {"status": "ok", "execution_count": 1}),
        _frame(msg_id, "status", {"execution_state": "idle"}),
    ]
    result = sb._collect(_FakeWS(frames), msg_id, timeout=5, kernel_id="k2")
    assert len(result.results) == 1
    assert "[output truncated" not in (result.stderr or "")
    assert result.truncated is False  # nothing was cut


# -- open() is idempotent under concurrency -----------------------------------


def test_concurrent_open_creates_one_kernel(monkeypatch):
    # Two threads opening the same session must POST exactly one kernel; a second
    # would orphan on the gateway. The CV guard serializes per-session creation.
    import threading

    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    posts = {"n": 0}
    post_lock = threading.Lock()
    start = threading.Event()

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": f"kernel-{posts['n']}"}

    def _fake_post(url, **kwargs):
        with post_lock:
            posts["n"] += 1
        start.wait(timeout=2)  # hold both threads at the POST to force the race
        return _Resp()

    monkeypatch.setattr(jupyter_gateway.requests, "post", _fake_post)
    monkeypatch.setattr(sb, "_prime", lambda kernel: None)

    results = {}

    def _open(i):
        results[i] = sb.open("session-x")

    threads = [threading.Thread(target=_open, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=5)

    assert posts["n"] == 1, "concurrent open() created more than one kernel"
    assert results[0] == results[1]  # both callers got the same kernel id


# -- Chunked put_file + large get_file round-trip ------------------------------


def _inprocess_run(calls):
    """A ``_run`` stand-in that execs the kernel program in-process and captures its stdout."""
    import io as _io
    from contextlib import redirect_stdout

    def fake_run(_kernel, code, _timeout, max_output_bytes=None):
        calls.append(code)
        buf = _io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(compile(code, "<kernel>", "exec"), {})
        except Exception as exc:  # surface as an error ExecResult, like the real gateway
            return ExecResult(status="error", error_name=type(exc).__name__, error_value=str(exc), exit_code=-1)
        return ExecResult(status="ok", stdout=buf.getvalue(), exit_code=0)

    return fake_run


def test_put_file_chunks_large_upload_and_get_file_round_trips(tmp_path, monkeypatch):
    """A >4 MB file is staged in multiple chunks and read back byte-for-byte.

    A 7 MB file's base64 (~9.3 MB) exceeds the default 8 MB output cap, so the
    file-transfer budget on get_file is what keeps it from truncating.
    """
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused", max_file_bytes=10 * 1024 * 1024)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sb._kernels["sid"] = _Kernel("kid", str(workspace))

    put_calls: list = []
    monkeypatch.setattr(sb, "_run", _inprocess_run(put_calls))

    data = os.urandom(7 * 1024 * 1024 + 123)  # 7 MB -> 3 chunks (3 + 3 + ~1)
    sb.put_file("sid", "big.bin", data)

    # Chunking actually happened (one execute_request could not carry this).
    assert len(put_calls) == 3
    assert (workspace / "big.bin").read_bytes() == data
    # get_file reassembles the same bytes and passes its length+sha256 integrity check.
    assert sb.get_file("sid", "big.bin") == data


def test_put_file_writes_empty_file(tmp_path, monkeypatch):
    """An empty upload still creates the file with a single wb write."""
    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    sb._kernels["sid"] = _Kernel("kid", str(workspace))
    calls: list = []
    monkeypatch.setattr(sb, "_run", _inprocess_run(calls))

    sb.put_file("sid", "empty.bin", b"")
    assert len(calls) == 1
    assert (workspace / "empty.bin").read_bytes() == b""
    assert sb.get_file("sid", "empty.bin") == b""


def test_collect_file_transfer_budget_prevents_truncation(monkeypatch):
    """A payload over the default output cap but under the file-transfer budget is not truncated."""
    sb = JupyterKernelGatewaySandbox(
        gateway_url="http://unused", max_output_bytes=1000, max_file_bytes=5000
    )
    monkeypatch.setattr(sb, "_interrupt_and_drain", lambda *a, **k: None)
    big = "Z" * 4000  # > max_output_bytes (1000), < _file_transfer_budget()
    assert 1000 < len(big) < sb._file_transfer_budget()

    # Default budget -> truncated (the get_file END marker would be dropped here).
    default = sb._collect(
        _FakeWS([_frame("m", "stream", {"name": "stdout", "text": big})]),
        "m", timeout=5, kernel_id="k",
    )
    assert "[output truncated" in default.stderr

    # Raised file-transfer budget -> the full payload is kept intact.
    ok = sb._collect(
        _FakeWS([
            _frame("m", "stream", {"name": "stdout", "text": big}),
            _frame("m", "execute_reply", {"status": "ok"}),
            _frame("m", "status", {"execution_state": "idle"}),
        ]),
        "m", timeout=5, kernel_id="k", max_output_bytes=sb._file_transfer_budget(),
    )
    assert "[output truncated" not in (ok.stderr or "")
    assert ok.stdout == big


def test_prime_sweeps_stale_workspace_before_recreate(tmp_path, monkeypatch):
    """A new kernel's _prime rmtrees any stale per-session dir so old files never carry over."""
    root = tmp_path / "docsgpt-sandbox"
    monkeypatch.setattr(jupyter_gateway, "_WORKSPACE_ROOT", str(root))
    workspace = root / "conv-stale"
    workspace.mkdir(parents=True)
    (workspace / "stale.txt").write_text("old")

    sb = JupyterKernelGatewaySandbox(gateway_url="http://unused")
    kernel = _Kernel("kid", str(workspace))
    monkeypatch.setattr(sb, "_run", lambda _k, code, _t: (_exec_setup_in_tmp(code), ExecResult(status="ok"))[1])
    monkeypatch.chdir(tmp_path)
    sb._prime(kernel)

    assert kernel.initialized
    assert not (workspace / "stale.txt").exists()  # stale file swept on re-open
