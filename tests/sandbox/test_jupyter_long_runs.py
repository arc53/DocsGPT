"""The Jupyter runner under long and memory-hungry runs.

A run may now ask for up to SANDBOX_EXEC_MAX_TIMEOUT seconds. The exec deadline
and the websocket reads must follow the requested timeout, the websocket
handshake must not, and a kernel that dies mid-run (the gateway restarts it and
announces ``restarting`` with no parent message) must end the call at once
instead of waiting out the whole timeout. When the container's OOM-kill counter
rose since the kernel started, the death is reported as out of memory.
"""

from __future__ import annotations

import json
from typing import List, Optional

import pytest

from docsgpt.sandbox import jupyter_gateway
from docsgpt.sandbox.base import ExecResult
from docsgpt.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox, _Kernel


def _frame(msg_id: Optional[str], msg_type: str, content: dict) -> str:
    parent = {"msg_id": msg_id} if msg_id else {}
    return json.dumps({"parent_header": parent, "msg_type": msg_type, "content": content})


class _ScriptedWS:
    """Serves frames in order and records the read timeouts it was given."""

    def __init__(self, frames: List[str]) -> None:
        self._frames = list(frames)
        self.timeouts: List[float] = []
        self.closed = False

    def settimeout(self, t: float) -> None:
        self.timeouts.append(t)

    def recv(self) -> str:
        if self._frames:
            return self._frames.pop(0)
        import websocket

        raise websocket.WebSocketTimeoutException()

    def send(self, _data: str) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def _sandbox(**kwargs) -> JupyterKernelGatewaySandbox:
    return JupyterKernelGatewaySandbox(gateway_url="http://unused", default_timeout=60, http_timeout=10, **kwargs)


def test_exec_reads_with_the_requested_timeout_and_connects_with_a_bounded_one(monkeypatch):
    sb = _sandbox()
    sb._kernels["s"] = _Kernel("k-1", "/tmp/s", "s")
    connects = []
    ws_holder = {}

    def _connect(url, timeout=None, header=None):
        connects.append(timeout)
        ws = _ScriptedWS([])
        ws_holder["ws"] = ws
        return ws

    def _collect(ws, msg_id, timeout, kernel_id, max_output_bytes=None, session_id=None):
        ws_holder["collect_timeout"] = timeout
        return ExecResult(status="ok")

    monkeypatch.setattr(jupyter_gateway.websocket, "create_connection", _connect)
    monkeypatch.setattr(sb, "_collect", _collect)

    assert sb.exec("s", "render()", timeout=900).ok
    # The deadline follows the call; the handshake is bounded by the default exec cap.
    assert ws_holder["collect_timeout"] == 900
    assert connects == [60]

    sb.exec("s", "quick()", timeout=5)
    assert connects[-1] == 5


def test_collect_waits_across_quiet_stretches_until_the_long_deadline(monkeypatch):
    """A long run that prints nothing for a while is not a timeout while the deadline is ahead."""
    sb = _sandbox()
    msg_id = "m-1"
    ws = _ScriptedWS(
        [
            _frame(msg_id, "status", {"execution_state": "busy"}),
            _frame(msg_id, "stream", {"name": "stdout", "text": "frame 1000/1000\n"}),
            _frame(msg_id, "execute_reply", {"status": "ok", "execution_count": 1}),
            _frame(msg_id, "status", {"execution_state": "idle"}),
        ]
    )
    result = sb._collect(ws, msg_id, timeout=900, kernel_id="k-1", session_id="s")
    assert result.ok and result.stdout == "frame 1000/1000\n"
    # Each read may block for what is left of the 900 s deadline.
    assert ws.timeouts and all(850 < t <= 900 for t in ws.timeouts)


@pytest.mark.parametrize("state", ["restarting", "dead"])
def test_a_kernel_that_dies_mid_run_ends_the_call_at_once(monkeypatch, state):
    sb = _sandbox()
    kernel = _Kernel("k-1", "/tmp/s", "s")
    sb._kernels["s"] = kernel
    deleted = []
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: deleted.append(kernel_id) or True)
    monkeypatch.setattr(sb, "_oom_kills_now", lambda kernel_id, session_id: None)
    msg_id = "m-1"
    ws = _ScriptedWS(
        [
            _frame(msg_id, "status", {"execution_state": "busy"}),
            _frame(msg_id, "stream", {"name": "stdout", "text": "loading\n"}),
            # The gateway's restart notice carries no parent message.
            _frame(None, "status", {"execution_state": state}),
        ]
    )

    result = sb._collect(ws, msg_id, timeout=900, kernel_id="k-1", session_id="s")

    assert result.ok is False
    assert result.error_name == "KernelDiedError"
    assert result.stdout == "loading\n"
    # The restarted kernel lost the workspace cwd and every variable: start a new session.
    assert result.runtime_invalidated is True
    assert deleted == ["k-1"]
    assert "s" not in sb._kernels
    assert result.out_of_memory is False
    assert "memory" in result.error_value


def test_a_kernel_killed_for_memory_is_reported_as_out_of_memory(monkeypatch):
    sb = _sandbox()
    sb._kernels["s"] = _Kernel("k-1", "/tmp/s", "s")
    sb._oom_baseline["k-1"] = 2
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: True)
    monkeypatch.setattr(sb, "_oom_kills_now", lambda kernel_id, session_id: 3)
    ws = _ScriptedWS([_frame(None, "status", {"execution_state": "restarting"})])

    result = sb._collect(ws, "m-1", timeout=900, kernel_id="k-1", session_id="s")

    assert result.out_of_memory is True
    assert result.error_name == "KernelDiedError"
    assert "k-1" not in sb._oom_baseline


def test_an_unchanged_oom_counter_is_not_out_of_memory(monkeypatch):
    sb = _sandbox()
    sb._kernels["s"] = _Kernel("k-1", "/tmp/s", "s")
    sb._oom_baseline["k-1"] = 2
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: True)
    monkeypatch.setattr(sb, "_oom_kills_now", lambda kernel_id, session_id: 2)
    ws = _ScriptedWS([_frame(None, "status", {"execution_state": "restarting"})])

    result = sb._collect(ws, "m-1", timeout=900, kernel_id="k-1", session_id="s")
    assert result.out_of_memory is False


def test_a_dead_kernel_is_not_probed(monkeypatch):
    """``dead`` means the gateway could not restart it: there is no kernel to read the counter from."""
    sb = _sandbox()
    sb._kernels["s"] = _Kernel("k-1", "/tmp/s", "s")
    sb._oom_baseline["k-1"] = 0
    monkeypatch.setattr(sb, "_delete_kernel", lambda kernel_id: True)

    def _probe(kernel_id, session_id):
        raise AssertionError("probed a dead kernel")

    monkeypatch.setattr(sb, "_oom_kills_now", _probe)
    ws = _ScriptedWS([_frame(None, "status", {"execution_state": "dead"})])
    result = sb._collect(ws, "m-1", timeout=900, kernel_id="k-1", session_id="s")
    assert result.error_name == "KernelDiedError" and result.out_of_memory is False


def test_another_messages_status_does_not_end_the_run():
    """Only the restart/dead notice ends a run early; a busy/idle of some other request does not."""
    sb = _sandbox()
    msg_id = "m-1"
    ws = _ScriptedWS(
        [
            _frame("other", "status", {"execution_state": "idle"}),
            _frame(None, "status", {"execution_state": "busy"}),
            _frame(msg_id, "execute_reply", {"status": "ok"}),
            _frame(msg_id, "status", {"execution_state": "idle"}),
        ]
    )
    assert sb._collect(ws, msg_id, timeout=30, kernel_id="k-1").ok


def test_prime_records_the_oom_kill_baseline(monkeypatch):
    sb = _sandbox()
    kernel = _Kernel("k-1", "/tmp/s", "s")
    codes = []

    def _run(_kernel, code, _timeout, max_output_bytes=None):
        codes.append(code)
        return ExecResult(status="ok", stdout="<<<DOCSGPT_OOM_KILLS:4>>>\n")

    monkeypatch.setattr(sb, "_run", _run)
    sb._prime(kernel)
    assert sb._oom_baseline["k-1"] == 4
    assert "memory.events" in codes[0]


def test_prime_without_a_readable_counter_records_none(monkeypatch):
    sb = _sandbox()
    monkeypatch.setattr(sb, "_run", lambda *a, **k: ExecResult(status="ok", stdout="<<<DOCSGPT_OOM_KILLS:-1>>>\n"))
    sb._prime(_Kernel("k-1", "/tmp/s", "s"))
    assert sb._oom_baseline["k-1"] is None


def test_the_oom_counter_snippet_reads_cgroup_v2_and_v1(tmp_path, monkeypatch, capsys):
    """The kernel-side snippet understands both cgroup layouts and prints -1 without either."""
    v2 = tmp_path / "memory.events"
    v2.write_text("low 0\nhigh 0\nmax 12\noom 3\noom_kill 3\noom_group_kill 0\n")
    v1 = tmp_path / "memory.oom_control"
    v1.write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 7\n")
    snippet = jupyter_gateway._OOM_KILLS_SNIPPET

    def _run(paths):
        code = snippet.replace(repr(jupyter_gateway._OOM_COUNTER_PATHS), repr(tuple(str(p) for p in paths)))
        exec(compile(code, "<oom>", "exec"), {})
        return jupyter_gateway._parse_oom_kills(capsys.readouterr().out)

    assert _run([v2, v1]) == 3
    assert _run([tmp_path / "missing", v1]) == 7
    assert _run([tmp_path / "missing"]) is None


def test_oom_kills_now_runs_the_snippet_on_the_restarted_kernel(monkeypatch):
    sb = _sandbox()
    seen = {}

    def _run(kernel, code, timeout, max_output_bytes=None):
        seen.update(kernel_id=kernel.kernel_id, timeout=timeout, code=code)
        return ExecResult(status="ok", stdout="<<<DOCSGPT_OOM_KILLS:5>>>\n")

    monkeypatch.setattr(sb, "_run", _run)
    assert sb._oom_kills_now("k-1", "s") == 5
    assert seen["kernel_id"] == "k-1" and seen["timeout"] == 10
    monkeypatch.setattr(sb, "_run", lambda *a, **k: ExecResult(status="error", error_name="X"))
    assert sb._oom_kills_now("k-1", "s") is None


def test_deleting_a_kernel_forgets_its_oom_baseline(monkeypatch):
    sb = _sandbox()
    sb._oom_baseline["k-1"] = 0

    class _Resp:
        status_code = 204

    monkeypatch.setattr(jupyter_gateway.requests, "delete", lambda *a, **k: _Resp())
    assert sb._delete_kernel("k-1") is True
    assert "k-1" not in sb._oom_baseline


def test_a_probe_that_raises_reads_as_no_counter(monkeypatch):
    sb = _sandbox()

    def _boom(*args, **kwargs):
        raise ConnectionError("gateway restarting")

    monkeypatch.setattr(sb, "_run", _boom)
    assert sb._oom_kills_now("k-1", "s") is None
