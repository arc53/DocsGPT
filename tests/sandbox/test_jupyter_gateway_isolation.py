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
