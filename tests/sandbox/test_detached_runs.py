"""Detached runs on the Daytona and Jupyter backends, and the shared result helpers (no cloud calls)."""

from __future__ import annotations

import json
import sys
import time
import types
from unittest import mock

import pytest

from docsgpt.sandbox import detached
from docsgpt.sandbox.base import ExecResult


# --- shared helpers -------------------------------------------------------


class TestResultHelpers:
    def test_ok_output(self):
        result = detached.result_from_output("hi\n", 0)
        assert result.ok
        assert result.stdout == "hi\n"

    def test_error_and_charts(self):
        out = "x\n<<docsgpt-chart:QUJD>>\nTraceback\n"
        result = detached.result_from_output(out, 1)
        assert result.status == "error"
        assert result.error_name == "ExecutionError"
        assert [p.content_base64 for p in result.plots] == ["QUJD"]
        assert "docsgpt-chart" not in result.stdout

    def test_sigkill_is_out_of_memory(self):
        result = detached.result_from_output("", 137)
        assert result.out_of_memory is True

    def test_timeout_exit_and_late_sigkill_are_timeouts_that_keep_output(self):
        for code, elapsed in ((124, 10), (137, 61)):
            result = detached.finished_result("partial\n", code, elapsed=elapsed, wall=60)
            assert result.error_name == "TimeoutError"
            assert result.error_value == "execution exceeded 60s"
            assert result.stdout == "partial\n"
        early_kill = detached.finished_result("", 137, elapsed=5, wall=60)
        assert early_kill.out_of_memory is True

    def test_output_cap(self):
        result = detached.result_from_output("a" * 100, 0, max_output_bytes=10)
        assert result.truncated
        assert result.stdout.startswith("a" * 10)

    def test_script_keeps_future_imports_first(self):
        script = detached.script_for("/ws", "from __future__ import annotations\nprint(1)\n")
        assert script.startswith("from __future__ import annotations\n")
        assert "_os.chdir('/ws')" in script
        compile(script, "main.py", "exec")

    def test_tail_bytes(self):
        assert detached.tail_bytes("abc<<docsgpt-chart:QQ==>>", 2) == "bc"


# --- Daytona --------------------------------------------------------------


class _Cmd:
    def __init__(self, exit_code):
        self.exit_code = exit_code


class _Logs:
    def __init__(self, stdout, stderr=""):
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def daytona(monkeypatch):
    process = types.SimpleNamespace(
        create_session=mock.Mock(),
        execute_session_command=mock.Mock(return_value=types.SimpleNamespace(cmd_id="cmd-1")),
        get_session_command=mock.Mock(return_value=_Cmd(None)),
        get_session_command_logs=mock.Mock(return_value=_Logs("so far\n")),
        delete_session=mock.Mock(),
    )
    sandbox_obj = types.SimpleNamespace(
        id="sbx-1",
        process=process,
        fs=types.SimpleNamespace(
            create_folder=mock.Mock(), upload_file=mock.Mock(), delete_file=mock.Mock()
        ),
        refresh_activity=mock.Mock(),
    )
    client = types.SimpleNamespace(get=mock.Mock(return_value=sandbox_obj))
    module = types.ModuleType("daytona")
    module.Daytona = lambda config: client
    module.DaytonaConfig = lambda **kwargs: types.SimpleNamespace(**kwargs)
    module.SessionExecuteRequest = lambda **kwargs: types.SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "daytona", module)
    from docsgpt.sandbox.daytona import DaytonaSandbox, _Handle

    backend = DaytonaSandbox(api_key="k")
    backend._handles["conv"] = _Handle(sandbox_obj, "sbx-1", "/home/daytona/docsgpt-sandbox")
    return backend, sandbox_obj


class TestDaytonaDetached:
    def test_start_feeds_the_script_on_stdin_and_launches_async(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "print(1)", 90, "abc")
        assert run["cmd_id"] == "cmd-1"
        assert run["process_session"] == "docsgpt-job-abc"
        assert run["job_dir"] is None
        assert run["wall"] == 90
        sbx.fs.upload_file.assert_not_called()
        sbx.process.create_session.assert_called_once()
        request = sbx.process.execute_session_command.call_args[0][1]
        assert request.run_async is True
        assert request.command.startswith("cd /home/daytona/docsgpt-sandbox && echo ")
        assert request.command.endswith("| base64 -d | timeout -k 5 90 python3 -u - 2>&1")
        encoded = request.command.split("echo ", 1)[1].split(" |", 1)[0]
        script = __import__("base64").b64decode(encoded).decode()
        assert script.endswith("print(1)")

    def test_a_long_script_is_uploaded(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x = 1\n" * 20_000, 90, "abc")
        assert run["job_dir"] == "scratch/jobs/abc"
        assert sbx.fs.upload_file.call_args[0][1].endswith("/scratch/jobs/abc/main.py")
        request = sbx.process.execute_session_command.call_args[0][1]
        assert request.command.endswith("python3 -u - < scratch/jobs/abc/main.py 2>&1")

    def test_poll_running_then_finished(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "print(1)", 90, "abc")
        state = backend.poll_detached("conv", run, with_output=True)
        assert state.done is False
        assert state.output == "so far\n"
        assert state.output_size == 7

        sbx.process.get_session_command.return_value = _Cmd(0)
        sbx.process.get_session_command_logs.return_value = _Logs("done\n")
        state = backend.poll_detached("conv", run)
        assert state.done is True
        assert state.result.ok and state.result.stdout == "done\n"
        deadline = time.monotonic() + 5
        while not sbx.process.delete_session.called and time.monotonic() < deadline:
            time.sleep(0.01)
        sbx.process.delete_session.assert_called_with("docsgpt-job-abc", request_timeout=mock.ANY)

    def test_poll_result_matches_code_run_mapping(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x", 90, "abc")
        sbx.process.get_session_command.return_value = _Cmd(1)
        sbx.process.get_session_command_logs.return_value = _Logs("Traceback\nValueError: bad\n")
        detached_result = backend.poll_detached("conv", run).result
        code_run_result = backend._to_result(
            types.SimpleNamespace(exit_code=1, result="Traceback\nValueError: bad\n", artifacts=None)
        )
        assert detached_result == code_run_result

    def test_timeout_exit(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x", 5, "abc")
        sbx.process.get_session_command.return_value = _Cmd(124)
        sbx.process.get_session_command_logs.return_value = _Logs("tick\n")
        result = backend.poll_detached("conv", run).result
        assert result.error_name == "TimeoutError"

    def test_gone_sandbox_ends_the_run(self, daytona, monkeypatch):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x", 5, "abc")
        sbx.process.get_session_command.side_effect = RuntimeError("404")
        monkeypatch.setattr(backend, "_sandbox_gone", lambda handle: True)
        state = backend.poll_detached("conv", run)
        assert state.done and state.gone
        assert state.result.runtime_invalidated

    def test_transient_poll_error_raises(self, daytona, monkeypatch):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x", 5, "abc")
        sbx.process.get_session_command.side_effect = RuntimeError("502")
        monkeypatch.setattr(backend, "_sandbox_gone", lambda handle: False)
        with pytest.raises(RuntimeError):
            backend.poll_detached("conv", run)

    def test_cancel_deletes_the_process_session(self, daytona):
        backend, sbx = daytona
        run = backend.start_detached("conv", "x", 5, "abc")
        backend.cancel_detached("conv", run)
        sbx.process.delete_session.assert_called_with("docsgpt-job-abc", request_timeout=mock.ANY)

    def test_adopt_and_release(self, daytona):
        backend, sbx = daytona
        backend._handles.clear()
        assert backend.adopt("conv", {"sandbox_id": "sbx-1", "workspace": "/ws"}) == {}
        assert backend._handles["conv"].workspace == "/ws"
        backend.refresh_activity("conv")
        sbx.refresh_activity.assert_called_once()
        backend.release_adopted("conv", {"sandbox_id": "sbx-1"})
        assert "conv" not in backend._handles


# --- Jupyter --------------------------------------------------------------


@pytest.fixture()
def jupyter():
    from docsgpt.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox, _Kernel

    backend = JupyterKernelGatewaySandbox("http://gateway")
    backend._kernels["conv"] = _Kernel("k1", "/tmp/docsgpt-sandbox/conv", "conv")
    return backend


def _marker(payload):
    return ExecResult(stdout="<<<DOCSGPT_JOB_BEGIN>>>" + json.dumps(payload) + "<<<DOCSGPT_JOB_END>>>")


class TestJupyterDetached:
    def test_start_launches_a_separate_process(self, jupyter):
        codes = []
        with mock.patch.object(jupyter, "put_file") as put, mock.patch.object(
            jupyter, "_run", side_effect=lambda k, code, t, max_output_bytes=None: codes.append(code) or _marker(
                {"pid": 77}
            )
        ):
            run = jupyter.start_detached("conv", "print(1)", 30, "abc")
        assert run["pid"] == 77
        assert run["kernel_id"] == "k1"
        assert put.call_args[0][1] == "scratch/jobs/abc/main.py"
        launcher = codes[0]
        compile(launcher, "launcher", "exec")
        assert "start_new_session=True" in launcher
        assert "timeout -k 5 ' + str(30)" in launcher

    def test_failed_launch_raises(self, jupyter):
        with mock.patch.object(jupyter, "put_file"), mock.patch.object(
            jupyter, "_run", return_value=ExecResult(status="error", error_value="boom")
        ):
            with pytest.raises(IOError):
                jupyter.start_detached("conv", "x", 30, "abc")

    def test_poll_running_and_finished(self, jupyter):
        run = {"job_dir": "scratch/jobs/abc", "pid": 77, "wall": 30, "started_at": time.time()}
        running = _marker({"done": False, "exit": None, "tail": "1\n", "size": 120})
        with mock.patch.object(jupyter, "_run", return_value=running):
            state = jupyter.poll_detached("conv", run, with_output=True)
        assert state.done is False and state.output == "1\n"
        assert state.output_size == 120

        outputs = iter([_marker({"done": True, "exit": 0, "tail": "1\n2\n"}), ExecResult()])
        with mock.patch.object(jupyter, "_run", side_effect=lambda *a, **k: next(outputs)), mock.patch.object(
            jupyter, "get_file", return_value=b"1\n2\n"
        ):
            state = jupyter.poll_detached("conv", run)
        assert state.done and state.result.ok
        assert state.result.stdout == "1\n2\n"

    def test_poll_probe_compiles(self, jupyter):
        codes = []
        run = {"job_dir": "scratch/jobs/abc", "pid": 77}
        with mock.patch.object(
            jupyter, "_run", side_effect=lambda k, code, t, max_output_bytes=None: codes.append(code) or _marker(
                {"done": False}
            )
        ):
            jupyter.poll_detached("conv", run, with_output=True)
        compile(codes[0], "probe", "exec")

    def test_cancel_signals_the_process_group(self, jupyter):
        with mock.patch.object(jupyter, "_run") as run_mock:
            jupyter.cancel_detached("conv", {"pid": 77})
        assert "_os.killpg(77, _sig.SIGTERM)" in run_mock.call_args[0][1]

    def test_adopt_uses_an_observer_kernel(self, jupyter):
        jupyter._kernels.clear()
        response = mock.Mock(json=mock.Mock(return_value={"id": "observer-1"}))
        with mock.patch("docsgpt.sandbox.jupyter_gateway.requests.post", return_value=response) as post:
            created = jupyter.adopt("conv", {"kernel_id": "k1", "workspace": "/tmp/docsgpt-sandbox/conv"})
        post.assert_called_once()
        assert created == {"observer_kernel_id": "observer-1"}
        kernel = jupyter._kernels["conv"]
        assert kernel.kernel_id == "observer-1"
        assert kernel.workspace == "/tmp/docsgpt-sandbox/conv"
        assert kernel.initialized is False

        with mock.patch.object(jupyter, "_kernel_alive", return_value=True), mock.patch(
            "docsgpt.sandbox.jupyter_gateway.requests.post"
        ) as post:
            assert jupyter.adopt("conv", {"observer_kernel_id": "observer-1", "workspace": "/w"}) == {}
        post.assert_not_called()

        with mock.patch.object(jupyter, "_delete_kernel") as delete:
            jupyter.release_adopted("conv", {"observer_kernel_id": "observer-1", "kernel_id": "k1"})
        delete.assert_called_once_with("observer-1")
        assert "conv" not in jupyter._kernels


def test_jupyter_probe_rereads_exit_when_the_group_is_gone(tmp_path):
    """A run that wrote ``exit`` and was reaped between the two checks keeps its real exit code."""
    import os
    import subprocess

    from docsgpt.sandbox.jupyter_gateway import JupyterKernelGatewaySandbox, _Kernel

    backend = JupyterKernelGatewaySandbox("http://gateway")
    backend._kernels["conv"] = _Kernel("k1", str(tmp_path), "conv")
    job = tmp_path / "scratch" / "jobs" / "abc"
    job.mkdir(parents=True)
    finished = subprocess.Popen(["true"], start_new_session=True)
    finished.wait()
    probes = []
    with mock.patch.object(
        backend, "_run", side_effect=lambda k, code, t, max_output_bytes=None: probes.append(code) or ExecResult()
    ):
        with pytest.raises(IOError):
            backend.poll_detached("conv", {"job_dir": "scratch/jobs/abc", "pid": finished.pid})
    probe = probes[0]
    # Simulate the race: no exit file at the first check, written before the re-read.
    namespace = {}
    original_exists = os.path.exists

    def exists_once(path, _seen=[]):
        if path.endswith("/exit") and not _seen:
            _seen.append(1)
            (job / "exit").write_text("0")
            return False
        return original_exists(path)

    with mock.patch("os.path.exists", exists_once), mock.patch("builtins.print") as printed:
        exec(compile(probe, "probe", "exec"), namespace)
    state = json.loads(printed.call_args[0][0].split("<<<DOCSGPT_JOB_BEGIN>>>")[1].split("<<<DOCSGPT_JOB_END>>>")[0])
    assert state["done"] is True
    assert state["exit"] == 0
