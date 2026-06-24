"""End-to-end test against a locally launched Jupyter Kernel Gateway subprocess.

Launches a real `jupyter kernelgateway` on an ephemeral port (no Docker — the
Docker credential helper hangs on this machine), points the backend at it, and
exercises the full session lifecycle. Skips gracefully if the gateway binary or
the websocket-client library is unavailable.
"""

import shutil
import socket
import subprocess
import time

import pytest

requests = pytest.importorskip("requests")
pytest.importorskip("websocket")  # websocket-client

from application.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox  # noqa: E402

_GATEWAY_BIN = shutil.which("jupyter-kernelgateway") or shutil.which("jupyter")

pytestmark = pytest.mark.skipif(
    _GATEWAY_BIN is None,
    reason="jupyter kernel gateway not installed (pip install jupyter-kernel-gateway)",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _gateway_cmd(port: int) -> list:
    if _GATEWAY_BIN.endswith("jupyter-kernelgateway"):
        base = [_GATEWAY_BIN]
    else:
        base = [_GATEWAY_BIN, "kernelgateway"]
    return base + [
        "--KernelGatewayApp.ip=127.0.0.1",
        f"--KernelGatewayApp.port={port}",
        # Raise the iopub data-rate limit so large get_file payloads aren't truncated.
        "--ZMQChannelsWebsocketConnection.limit_rate=False",
    ]


@pytest.fixture(scope="module")
def gateway_url():
    port = _free_port()
    proc = subprocess.Popen(
        _gateway_cmd(port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    ready = False
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.skip("jupyter kernelgateway process exited during startup")
            try:
                resp = requests.get(f"{url}/api", timeout=1)
                if resp.status_code == 200:
                    ready = True
                    break
            except requests.RequestException:
                time.sleep(0.3)
        if not ready:
            pytest.skip("jupyter kernelgateway did not become ready in time")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture()
def sandbox(gateway_url):
    sb = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=30.0)
    yield sb


def test_open_and_close_lifecycle(sandbox):
    session = "conv-lifecycle"
    kernel_id = sandbox.open(session)
    assert kernel_id
    resp = requests.get(f"{sandbox._base_url}/api/kernels/{kernel_id}", timeout=5)
    assert resp.status_code == 200
    sandbox.close(session)
    resp = requests.get(f"{sandbox._base_url}/api/kernels/{kernel_id}", timeout=5)
    assert resp.status_code == 404  # kernel torn down


def test_stateful_exec_carries_variables(sandbox):
    session = "conv-state"
    sandbox.open(session)
    try:
        first = sandbox.exec(session, "x = 1")
        assert first.ok, first.error_value
        second = sandbox.exec(session, "print(x + 41)")
        assert second.ok, second.error_value
        assert second.stdout.strip() == "42"
        assert second.execution_count is not None
    finally:
        sandbox.close(session)


def test_stdout_capture(sandbox):
    session = "conv-stdout"
    sandbox.open(session)
    try:
        res = sandbox.exec(session, "print('hello sandbox')")
        assert res.ok
        assert "hello sandbox" in res.stdout
    finally:
        sandbox.close(session)


def test_error_capture_sets_failure_status(sandbox):
    session = "conv-error"
    sandbox.open(session)
    try:
        res = sandbox.exec(session, "raise ValueError('boom')")
        assert not res.ok
        assert res.status == "error"
        assert res.error_name == "ValueError"
        assert "boom" in (res.error_value or "")
        assert res.traceback
    finally:
        sandbox.close(session)


def test_put_and_get_file_roundtrip_exact_bytes(sandbox):
    session = "conv-files"
    sandbox.open(session)
    try:
        payload = bytes(range(256)) * 4  # 1 KiB of every byte value
        sandbox.put_file(session, "data/blob.bin", payload)
        assert "data/blob.bin" in sandbox.list_files(session)
        fetched = sandbox.get_file(session, "data/blob.bin")
        assert fetched == payload
    finally:
        sandbox.close(session)


def test_file_written_by_code_is_readable(sandbox):
    session = "conv-codefile"
    sandbox.open(session)
    try:
        res = sandbox.exec(session, "open('out.txt', 'w').write('generated')")
        assert res.ok, res.error_value
        assert sandbox.get_file(session, "out.txt") == b"generated"
    finally:
        sandbox.close(session)


def test_attach_reuses_running_kernel(sandbox):
    session = "conv-attach"
    first_id = sandbox.open(session)
    try:
        sandbox.exec(session, "y = 7")
        second_id = sandbox.attach(session)
        assert second_id == first_id
        res = sandbox.exec(session, "print(y)")
        assert res.stdout.strip() == "7"
    finally:
        sandbox.close(session)


def test_exec_timeout_reports_error(sandbox):
    session = "conv-timeout"
    sandbox.open(session)
    try:
        res = sandbox.exec(session, "import time; time.sleep(5)", timeout=1.0)
        assert not res.ok
        assert res.error_name == "TimeoutError"
    finally:
        sandbox.close(session)


def test_kernel_killed_mid_exec_returns_error(sandbox):
    session = "conv-killed"
    kernel_id = sandbox.open(session)
    try:
        import threading

        def _kill():
            time.sleep(0.5)
            requests.delete(f"{sandbox._base_url}/api/kernels/{kernel_id}", timeout=5)

        killer = threading.Thread(target=_kill)
        killer.start()
        res = sandbox.exec(session, "import time\nfor _ in range(50): time.sleep(0.2)", timeout=20.0)
        killer.join()
        assert not res.ok  # error result, no raise / no hang
        assert res.exit_code == -1
    finally:
        sandbox.close(session)


def test_runaway_loop_times_out_and_session_stays_reusable(sandbox):
    session = "conv-runaway"
    sandbox.open(session)
    try:
        start = time.monotonic()
        res = sandbox.exec(session, "while True:\n    print('x')", timeout=2.0)
        elapsed = time.monotonic() - start
        assert not res.ok
        assert res.error_name == "TimeoutError"
        assert elapsed < 2.0 + 8.0  # returns within timeout + interrupt slack
        # Interrupt should have freed the kernel: a fresh exec on the same session works.
        again = sandbox.exec(session, "print(2 + 2)", timeout=10.0)
        assert again.ok, again.error_value
        assert again.stdout.strip() == "4"
    finally:
        sandbox.close(session)


def test_output_cap_truncates_runaway_output(gateway_url):
    sb = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=60.0, max_output_bytes=50_000)
    session = "conv-bigout"
    sb.open(session)
    try:
        # Emit ~200 KiB (4x the 50 KB cap) as bounded, fast work under a generous timeout, so the
        # output cap -- not the wall-clock deadline -- deterministically trips even under load.
        res = sb.exec(session, "for _ in range(200): print('A' * 1000)", timeout=60.0)
        assert "truncated" in res.stderr
        assert len(res.stdout) <= 60_000  # capped well under the produced ~200 KiB
        again = sb.exec(session, "print('alive')", timeout=10.0)
        assert again.ok and "alive" in again.stdout
    finally:
        sb.close(session)


def test_put_file_rejects_path_traversal(sandbox):
    session = "conv-trav-put"
    sandbox.open(session)
    try:
        with pytest.raises(IOError):
            sandbox.put_file(session, "../escape.txt", b"nope")
        with pytest.raises(IOError):
            sandbox.put_file(session, "/etc/escape.txt", b"nope")
        # The escape target must not exist (no file written outside the workspace).
        probe = sandbox.exec(session, "import os; print(os.path.exists('/etc/escape.txt'))")
        assert probe.stdout.strip() == "False"
    finally:
        sandbox.close(session)


def test_get_file_rejects_path_traversal(sandbox):
    session = "conv-trav-get"
    sandbox.open(session)
    try:
        with pytest.raises(IOError):
            sandbox.get_file(session, "../../etc/passwd")
        with pytest.raises(IOError):
            sandbox.get_file(session, "/etc/passwd")
    finally:
        sandbox.close(session)


def test_get_file_rejects_oversized_file(gateway_url):
    sb = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=30.0, max_file_bytes=1024)
    session = "conv-toobig"
    sb.open(session)
    try:
        sb.put_file(session, "big.bin", b"x" * 4096)  # 4 KiB > 1 KiB cap
        with pytest.raises(IOError):
            sb.get_file(session, "big.bin")
    finally:
        sb.close(session)


def test_get_file_integrity_roundtrip_large(gateway_url):
    sb = JupyterKernelGatewaySandbox(gateway_url=gateway_url, default_timeout=60.0)
    session = "conv-large"
    sb.open(session)
    try:
        payload = bytes(range(256)) * 8192  # 2 MiB, exercises the iopub path + integrity check
        sb.put_file(session, "big.bin", payload)
        fetched = sb.get_file(session, "big.bin")
        assert fetched == payload
    finally:
        sb.close(session)


def test_open_rejects_illegal_session_id(sandbox):
    for bad in ["../evil", "a/b", "a b", "a;b", ""]:
        with pytest.raises(ValueError):
            sandbox.open(bad)
