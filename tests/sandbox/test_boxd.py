"""Unit tests for BoxdSandbox with the boxd SDK fully mocked (no cloud calls)."""

import base64
import re
import sys
import types
from unittest import mock

import pytest

from docsgpt.sandbox.base import FileTooLargeError, SandboxGoneError

_WS = "/home/boxd/docsgpt-sandbox"


# --- Fakes mirroring the real boxd SDK shapes ----------------------------


class _NotFoundError(Exception):
    pass


class _ConflictError(Exception):
    pass


class _FakeExecResult:
    def __init__(self, stdout="", stderr="", exit_code=0):
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class _FakeMachine:
    def __init__(self, machine_id, name="m", labels=None, status="running"):
        self.id = machine_id
        self.name = name
        self.labels = dict(labels or {})
        self.status = status


class _FakeFiles:
    def __init__(self, machines):
        self._machines = machines
        self.store = {}
        self.upload = mock.Mock(side_effect=self._upload)
        self.download = mock.Mock(side_effect=self._download)
        self.delete = mock.Mock()

    def _upload(self, machine_id, path, data):
        self._machines._check(machine_id)
        self.store[path] = data
        return len(data)

    def _download(self, machine_id, path):
        self._machines._check(machine_id)
        return self.store[path]


class _FakeMachines:
    def __init__(self):
        self.machines = {}
        self.created = []
        self.deleted = []
        self.commands = []
        # ``handler(command) -> _FakeExecResult | None``; None falls back to the default reply.
        self.handler = None
        self.files = _FakeFiles(self)
        self.create = mock.Mock(side_effect=self._create)
        self.wait_until_ready = mock.Mock(side_effect=lambda machine_id, timeout=90.0: self.machines[machine_id])
        self.get = mock.Mock(side_effect=self._get)
        self.list = mock.Mock(side_effect=self._list)
        self.delete = mock.Mock(side_effect=self._delete)
        self.exec = mock.Mock(side_effect=self._exec)
        self.start = mock.Mock(side_effect=lambda machine_id: self._set(machine_id, "running"))
        self.wake = mock.Mock(side_effect=lambda machine_id: self._set(machine_id, "running"))
        self.resume = mock.Mock(side_effect=lambda machine_id: self._set(machine_id, "running"))
        self.set_delete_after = mock.Mock()

    def _set(self, machine_id, status):
        self.machines[machine_id].status = status

    def _check(self, machine_id):
        machine = self.machines.get(machine_id)
        if machine is None or machine.status == "destroyed":
            raise _NotFoundError(machine_id)
        if machine.status == "stopped":
            raise _ConflictError(f"{machine_id} is stopped")

    def _create(self, name=None, **kwargs):
        machine = _FakeMachine(f"m-{len(self.created) + 1}", name=name, labels=kwargs.get("labels"))
        self.machines[machine.id] = machine
        self.created.append((name, kwargs))
        return machine

    def _get(self, machine_id):
        machine = self.machines.get(machine_id)
        if machine is None:
            raise _NotFoundError(machine_id)
        return machine

    def _list(self, org=None, labels=None):
        wanted = labels or {}
        return [m for m in self.machines.values() if all(m.labels.get(k) == v for k, v in wanted.items())]

    def _delete(self, machine_id):
        self.deleted.append(machine_id)
        self.machines.pop(machine_id, None)

    def _exec(self, machine_id, command, env=None, timeout=None):
        self._check(machine_id)
        self.commands.append((machine_id, command, env, timeout))
        if self.handler is not None:
            reply = self.handler(command)
            if reply is not None:
                return reply
        return _FakeExecResult()


class _FakeBoxd:
    def __init__(self, api_key=None, region=None):
        self.api_key = api_key
        self.region = region
        self.machines = _FakeMachines()


@pytest.fixture()
def fake_sdk(monkeypatch):
    """Install a fake ``boxd`` package so BoxdSandbox imports it without the real SDK."""
    module = types.ModuleType("boxd")
    module.Boxd = _FakeBoxd
    errors = types.ModuleType("boxd.errors")
    errors.NotFoundError = _NotFoundError
    errors.ConflictError = _ConflictError
    module.errors = errors
    monkeypatch.setitem(sys.modules, "boxd", module)
    monkeypatch.setitem(sys.modules, "boxd.errors", errors)
    return module


@pytest.fixture()
def sandbox(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    return BoxdSandbox(api_key="test-key", org="acme", region="fra")


def _machines(sandbox):
    return sandbox._client.machines


def _script_of(command):
    """The Python source an inline run pipes to ``python3``."""
    match = re.search(r"echo ([A-Za-z0-9+/=]+) \| base64 -d", command)
    assert match, command
    return base64.b64decode(match.group(1)).decode("utf-8")


def _reply_to_runs(sandbox, stdout="", exit_code=0):
    def handler(command):
        if "python3 -u" in command:
            return _FakeExecResult(stdout=stdout, exit_code=exit_code)
        return None

    _machines(sandbox).handler = handler


# --- Construction --------------------------------------------------------


def test_requires_api_key(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    with pytest.raises(ValueError):
        BoxdSandbox(api_key="")


def test_client_gets_key_and_region(sandbox):
    assert sandbox._client.api_key == "test-key"
    assert sandbox._client.region == "fra"


def test_name_prefix_is_made_a_valid_machine_name(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", name_prefix="My_Deploy!")
    box.open("conv-1")
    name, _ = _machines(box).created[0]
    assert re.fullmatch(r"my-deploy-[0-9a-f]{8}", name), name


# --- Lifecycle -----------------------------------------------------------


def test_open_creates_isolated_labelled_machine_and_primes_workspace(sandbox):
    assert sandbox.open("conv-1") == "m-1"
    name, kwargs = _machines(sandbox).created[0]
    assert name.startswith("docsgpt-")
    assert kwargs["isolated"] is True
    assert kwargs["org"] == "acme"
    assert kwargs["labels"] == {"docsgpt_session_id": "conv-1"}
    assert kwargs["auto_suspend_timeout"] == 0
    _machines(sandbox).wait_until_ready.assert_called_once()
    assert any(cmd.startswith(f"mkdir -p {_WS} ") for _, cmd, _, _ in _machines(sandbox).commands)


def test_prime_creates_the_user_site_so_a_fresh_pip_install_imports_in_the_same_run(sandbox):
    """Python adds the user site to sys.path only if it exists when the interpreter starts."""
    sandbox.open("conv-1")
    prime = _machines(sandbox).commands[0][1]
    assert '"$(python3 -m site --user-site)"' in prime


def test_open_session_reports_a_fresh_machine_as_created(sandbox):
    assert sandbox.open_session("conv-1").created is True
    assert sandbox.open_session("conv-1").created is False


def test_open_twice_reuses_handle(sandbox):
    sandbox.open("conv-1")
    sandbox.open("conv-1")
    assert _machines(sandbox).create.call_count == 1


def test_attach_reuses_warm_handle(sandbox):
    sandbox.open("conv-1")
    assert sandbox.attach("conv-1") == "m-1"
    assert _machines(sandbox).create.call_count == 1


def test_attach_opens_when_no_handle(sandbox):
    assert sandbox.attach("conv-1") == "m-1"


def test_invalid_session_id_rejected(sandbox):
    with pytest.raises(ValueError):
        sandbox.open("../etc")


def test_close_deletes_machine_by_id(sandbox):
    sandbox.open("conv-1")
    sandbox.close("conv-1")
    assert _machines(sandbox).deleted == ["m-1"]
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def test_close_unknown_session_is_noop(sandbox):
    sandbox.close("nope")
    assert _machines(sandbox).deleted == []


def test_close_swallows_delete_errors(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).delete.side_effect = RuntimeError("boom")
    sandbox.close("conv-1")


def test_close_handle_leaves_reopened_machine_registered(sandbox):
    sandbox.open("conv-1")
    sandbox.release_handle("conv-1", "m-1")
    sandbox.open("conv-1")  # reattaches m-1 by its label
    _machines(sandbox).machines["m-1"].labels = {}
    sandbox.release_handle("conv-1", "m-1")
    assert sandbox.open("conv-1") == "m-2"
    sandbox.close_handle("conv-1", "m-1")
    assert _machines(sandbox).deleted == ["m-1"]
    assert sandbox._get_handle("conv-1").machine_id == "m-2"


def test_release_handle_keeps_the_machine(sandbox):
    sandbox.open("conv-1")
    sandbox.release_handle("conv-1", "m-1")
    assert _machines(sandbox).deleted == []
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def test_open_reattaches_to_labelled_machine(sandbox):
    _machines(sandbox).machines["old"] = _FakeMachine("old", labels={"docsgpt_session_id": "conv-1"})
    opened = sandbox.open_session("conv-1")
    assert opened.handle == "old" and opened.created is False
    assert _machines(sandbox).create.call_count == 0
    _machines(sandbox).list.assert_called_once_with(org="acme", labels={"docsgpt_session_id": "conv-1"})


def test_open_skips_a_destroyed_or_foreign_machine(sandbox):
    _machines(sandbox).machines["dead"] = _FakeMachine(
        "dead", labels={"docsgpt_session_id": "conv-1"}, status="destroyed"
    )
    _machines(sandbox).machines["other"] = _FakeMachine("other", labels={"docsgpt_session_id": "conv-2"})
    assert sandbox.open("conv-1") == "m-1"


def test_open_creates_fresh_when_listing_fails(sandbox):
    _machines(sandbox).list.side_effect = RuntimeError("unreachable")
    assert sandbox.open("conv-1") == "m-1"


def test_open_enforces_machine_cap(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", max_machines=1)
    box.open("conv-1")
    with pytest.raises(RuntimeError, match="cap"):
        box.open("conv-2")


def test_machine_that_never_gets_ready_is_deleted(sandbox):
    _machines(sandbox).wait_until_ready.side_effect = TimeoutError("not ready")
    with pytest.raises(TimeoutError):
        sandbox.open("conv-1")
    assert _machines(sandbox).deleted == ["m-1"]
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def test_prime_on_a_vanished_machine_raises_gone_and_caches_nothing(sandbox):
    def vanish(command):
        _machines(sandbox).machines.pop("m-1", None)
        raise _NotFoundError("m-1")

    _machines(sandbox).handler = vanish
    with pytest.raises(SandboxGoneError):
        sandbox.open("conv-1")
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def test_reattach_starts_a_stopped_machine_before_priming(sandbox):
    _machines(sandbox).machines["old"] = _FakeMachine(
        "old", labels={"docsgpt_session_id": "conv-1"}, status="stopped"
    )
    assert sandbox.open("conv-1") == "old"
    _machines(sandbox).start.assert_called_once_with("old")


# --- Execution -----------------------------------------------------------


def test_exec_maps_success_to_exec_result(sandbox):
    sandbox.open("conv-1")
    _reply_to_runs(sandbox, stdout="hi\n")
    result = sandbox.exec("conv-1", "print('hi')")
    assert result.ok and result.stdout == "hi\n" and result.exit_code == 0


def test_exec_runs_a_fresh_python_in_the_workspace(sandbox):
    sandbox.open("conv-1")
    sandbox.exec("conv-1", "from __future__ import annotations\nprint(1)", timeout=42)
    _, command, _, timeout = _machines(sandbox).commands[-1]
    assert f"; mkdir -p {_WS} && cd {_WS} || exit 1; " in command
    assert "timeout -k 5 42 python3 -u - 2>&1" in command
    script = _script_of(command)
    assert script.startswith("from __future__ import annotations\n")
    assert f"_os.chdir({_WS!r})" in script
    assert timeout > 42


def test_exec_lets_pip_install_into_the_user_site(sandbox):
    """Exported first, so every process in the pipeline (and pip run by the code) inherits it."""
    sandbox.open("conv-1")
    sandbox.exec("conv-1", "print(1)")
    _, command, _, _ = _machines(sandbox).commands[-1]
    assert command.startswith("export PIP_BREAK_SYSTEM_PACKAGES=1 ")


def test_exec_nonzero_exit_is_error(sandbox):
    sandbox.open("conv-1")
    _reply_to_runs(sandbox, stdout="Traceback ...\nValueError: boom\n", exit_code=1)
    result = sandbox.exec("conv-1", "raise ValueError('boom')")
    assert not result.ok
    assert result.exit_code == 1
    assert result.error_name == "ExecutionError"
    assert "ValueError: boom" in result.stdout


def test_exec_timeout_exit_is_a_timeout_error(sandbox):
    sandbox.open("conv-1")
    _reply_to_runs(sandbox, stdout="partial\n", exit_code=124)
    result = sandbox.exec("conv-1", "import time; time.sleep(99)", timeout=5)
    assert result.error_name == "TimeoutError"
    assert "5s" in result.error_value
    assert "partial" in result.stdout


def test_exec_sigkill_is_reported_as_out_of_memory(sandbox):
    sandbox.open("conv-1")
    _reply_to_runs(sandbox, exit_code=137)
    assert sandbox.exec("conv-1", "x = ' ' * 10**12").out_of_memory is True


def test_exec_captures_charts_as_plots(sandbox):
    sandbox.open("conv-1")
    png = base64.b64encode(b"\x89PNG fake").decode()
    _reply_to_runs(sandbox, stdout=f"before\n<<docsgpt-chart:{png}>>\nafter\n")
    result = sandbox.exec("conv-1", "plt.show()")
    assert [p.content_base64 for p in result.plots] == [png]
    assert "docsgpt-chart" not in result.stdout


def test_exec_truncates_output_over_the_cap(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", max_output_bytes=10)
    box.open("conv-1")
    _reply_to_runs(box, stdout="x" * 100)
    result = box.exec("conv-1", "print('x' * 100)")
    assert result.truncated is True
    assert result.stdout.startswith("x" * 10 + "\n[output truncated")


def test_exec_sdk_error_becomes_error_result(sandbox):
    sandbox.open("conv-1")

    def fail(command):
        raise RuntimeError("transport")

    _machines(sandbox).handler = fail
    result = sandbox.exec("conv-1", "print(1)")
    assert not result.ok and result.sandbox_error is True
    assert result.runtime_invalidated is False
    assert sandbox._get_handle("conv-1").machine_id == "m-1"


def test_exec_on_a_deleted_machine_invalidates_the_session(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).machines.pop("m-1")
    result = sandbox.exec("conv-1", "print(1)")
    assert result.runtime_invalidated is True and result.sandbox_error is True
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def test_exec_starts_a_stopped_machine_and_retries(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).machines["m-1"].status = "stopped"
    _reply_to_runs(sandbox, stdout="ok\n")
    result = sandbox.exec("conv-1", "print('ok')")
    assert result.ok and result.stdout == "ok\n"
    _machines(sandbox).start.assert_called_once_with("m-1")


def test_exec_uploads_a_script_too_long_for_one_command_line(sandbox):
    sandbox.open("conv-1")
    sandbox.exec("conv-1", "x = 1\n" * 20_000)
    uploads = _machines(sandbox).files.upload.call_args_list
    assert len(uploads) == 1
    remote = uploads[0].args[1]
    assert remote.startswith(f"{_WS}/scratch/jobs/") and remote.endswith("/main.py")
    _, command, _, _ = _machines(sandbox).commands[-1]
    assert f"python3 -u {remote}" in command
    assert "base64 -d" not in command
    assert "rm -rf" in command


def test_exec_bounds_the_output_read_back_and_keeps_the_exit_status(fake_sdk):
    from docsgpt.sandbox.boxd import _CHART_ROOM, BoxdSandbox

    box = BoxdSandbox(api_key="k", max_output_bytes=1000)
    box.open("conv-1")
    box.exec("conv-1", "print(1)")
    _, command, _, _ = _machines(box).commands[-1]
    assert f'head -c {1000 + _CHART_ROOM} "$out"' in command
    assert "rc=$?" in command and command.endswith("exit $rc")


def test_exec_after_its_timeout_on_a_deleted_machine_is_not_a_timeout(sandbox, monkeypatch):
    from docsgpt.sandbox import boxd as mod

    sandbox.open("conv-1")
    clock = iter([0.0, 100.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(clock, 100.0))

    def vanish(command):
        _machines(sandbox).machines.pop("m-1", None)
        raise RuntimeError("stream closed")

    _machines(sandbox).handler = vanish
    result = sandbox.exec("conv-1", "print(1)", timeout=5)
    assert result.error_name != "TimeoutError"
    assert result.runtime_invalidated is True


def test_exec_requires_open_session(sandbox):
    with pytest.raises(KeyError):
        sandbox.exec("nope", "print(1)")


# --- File transfer -------------------------------------------------------


def test_put_file_uploads_under_workspace(sandbox):
    sandbox.open("conv-1")
    sandbox.put_file("conv-1", "inputs/a.csv", b"1,2")
    assert _machines(sandbox).files.store[f"{_WS}/inputs/a.csv"] == b"1,2"


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", "a/../../x", "a\x00b"])
def test_file_paths_must_stay_in_the_workspace(sandbox, path):
    sandbox.open("conv-1")
    with pytest.raises(ValueError):
        sandbox.put_file("conv-1", path, b"x")
    with pytest.raises(ValueError):
        sandbox.get_file("conv-1", path)


def test_put_file_error_wrapped_as_ioerror(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).files.upload.side_effect = RuntimeError("secret backend detail")
    with pytest.raises(IOError) as info:
        sandbox.put_file("conv-1", "a.txt", b"x")
    assert "secret backend detail" not in str(info.value)


def test_put_file_on_a_deleted_machine_raises_gone(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).machines.pop("m-1")
    with pytest.raises(SandboxGoneError):
        sandbox.put_file("conv-1", "a.txt", b"x")
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")


def _stat_reply(size):
    def handler(command):
        if "; stat -L -c" in command:
            if size is None:
                return _FakeExecResult(exit_code=1)
            return _FakeExecResult(stdout=f"regular file/{size}\n")
        return None

    return handler


def test_get_file_returns_bytes(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).files.store[f"{_WS}/out/r.txt"] = b"payload"
    _machines(sandbox).handler = _stat_reply(7)
    assert sandbox.get_file("conv-1", "out/r.txt") == b"payload"


def test_get_file_too_large_is_refused_before_download(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", max_file_bytes=4)
    box.open("conv-1")
    _machines(box).handler = _stat_reply(5)
    with pytest.raises(FileTooLargeError) as info:
        box.get_file("conv-1", "big.bin")
    assert (info.value.size, info.value.limit) == (5, 4)
    _machines(box).files.download.assert_not_called()


def test_get_file_checks_the_size_of_what_a_symlink_points_to(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _stat_reply(7)
    _machines(sandbox).files.store[f"{_WS}/link"] = b"payload"
    sandbox.get_file("conv-1", "link")
    stat = next(cmd for _, cmd, _, _ in _machines(sandbox).commands if "stat " in cmd)
    assert "stat -L " in stat


def test_get_file_refuses_what_is_not_a_regular_file(sandbox):
    sandbox.open("conv-1")
    device = _FakeExecResult(stdout="character special file/0\n")
    _machines(sandbox).handler = lambda c: device if "stat " in c else None
    with pytest.raises(IOError, match="not a regular file"):
        sandbox.get_file("conv-1", "zero")
    _machines(sandbox).files.download.assert_not_called()


def test_get_file_missing_raises_file_not_found(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _stat_reply(None)
    with pytest.raises(FileNotFoundError):
        sandbox.get_file("conv-1", "nope.txt")


def test_list_files_returns_workspace_relative_paths(sandbox):
    sandbox.open("conv-1")

    def handler(command):
        if " -type f -printf " in command:
            return _FakeExecResult(stdout="a.txt\0sub/b.png\0scratch/c\0")
        return None

    _machines(sandbox).handler = handler
    assert sandbox.list_files("conv-1") == ["a.txt", "sub/b.png", "scratch/c"]


def test_list_files_drops_entries_that_escape_the_workspace(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = lambda c: _FakeExecResult(stdout="ok\0../x\0") if "-printf" in c else None
    assert sandbox.list_files("conv-1") == ["ok"]


def test_remove_path_deletes_and_refuses_the_root(sandbox):
    sandbox.open("conv-1")
    sandbox.remove_path("conv-1", "artifacts/tok")
    sandbox.remove_path("conv-1", ".")
    calls = _machines(sandbox).files.delete.call_args_list
    assert [c.args for c in calls] == [("m-1", f"{_WS}/artifacts/tok")]


def test_remove_path_never_raises(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).files.delete.side_effect = RuntimeError("boom")
    sandbox.remove_path("conv-1", "x")
    sandbox.remove_path("unknown", "x")


# --- Detached runs -------------------------------------------------------


def _detached_handler(state):
    def handler(command):
        if "setsid sh -c" in command:
            return _FakeExecResult(stdout="<<<DOCSGPT_JOB_BEGIN>>>4242<<<DOCSGPT_JOB_END>>>\n")
        if "base64 -d" in command and "killpg" in _script_of(command):
            import json

            return _FakeExecResult(stdout="<<<DOCSGPT_JOB_BEGIN>>>" + json.dumps(state) + "<<<DOCSGPT_JOB_END>>>\n")
        if "; stat -L -c" in command:
            return _FakeExecResult(stdout="regular file/5\n")
        return None

    return handler


def test_start_detached_uploads_the_script_and_starts_its_own_process_group(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _detached_handler({})
    run = sandbox.start_detached("conv-1", "print(1)", 30, "k1")
    assert run["backend"] == "boxd" and run["machine_id"] == "m-1" and run["pid"] == 4242
    assert run["job_dir"] == "scratch/jobs/k1" and run["wall"] == 30
    assert f"{_WS}/scratch/jobs/k1/main.py" in _machines(sandbox).files.store
    launch = next(cmd for _, cmd, _, _ in _machines(sandbox).commands if "setsid" in cmd)
    assert "timeout -k 5 30 python3" in launch and "</dev/null" in launch
    # Quoted, or the shell reads ``<<<`` as a here-string and prints no process id.
    assert "echo '<<<DOCSGPT_JOB_BEGIN>>>'$!'<<<DOCSGPT_JOB_END>>>'" in launch


def test_poll_detached_reports_a_running_job(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _detached_handler({"done": False, "exit": None, "tail": "step 1", "size": 6})
    run = sandbox.start_detached("conv-1", "print(1)", 30, "k1")
    state = sandbox.poll_detached("conv-1", run, with_output=True)
    assert state.done is False and state.output == "step 1" and state.output_size == 6


def test_poll_detached_finishes_a_job_and_removes_its_directory(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _detached_handler({"done": True, "exit": 0, "tail": "hello", "size": 5})
    run = sandbox.start_detached("conv-1", "print(1)", 30, "k1")
    _machines(sandbox).files.store[f"{_WS}/scratch/jobs/k1/out.log"] = b"hello"
    state = sandbox.poll_detached("conv-1", run)
    assert state.done is True and state.result.ok and state.result.stdout == "hello"
    _machines(sandbox).files.delete.assert_called_with("m-1", f"{_WS}/scratch/jobs/k1")


def test_poll_detached_on_a_deleted_machine_ends_the_run(sandbox):
    sandbox.open("conv-1")
    _machines(sandbox).handler = _detached_handler({})
    run = sandbox.start_detached("conv-1", "print(1)", 30, "k1")
    _machines(sandbox).machines.pop("m-1")
    state = sandbox.poll_detached("conv-1", run)
    assert state.done and state.gone and state.result.runtime_invalidated


def test_cancel_detached_signals_the_whole_session(sandbox):
    """``timeout`` runs the script in its own process group, so the session is what holds them all."""
    sandbox.open("conv-1")
    sandbox.cancel_detached("conv-1", {"pid": 4242, "job_dir": "scratch/jobs/k1"})
    assert "; pkill -TERM -s 4242;" in _machines(sandbox).commands[-1][1]
    _machines(sandbox).files.delete.assert_called_with("m-1", f"{_WS}/scratch/jobs/k1")


# --- Delete-after timer --------------------------------------------------


def test_no_delete_after_timer_by_default(sandbox):
    sandbox.open("conv-1")
    sandbox.exec("conv-1", "print(1)")
    assert "delete_after" not in _machines(sandbox).created[0][1]
    _machines(sandbox).set_delete_after.assert_not_called()


def test_a_new_machine_gets_the_delete_after_timer(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", delete_after=3600)
    box.open("conv-1")
    assert _machines(box).created[0][1]["delete_after"] == 3600
    box.exec("conv-1", "print(1)")  # just created: no refresh yet
    _machines(box).set_delete_after.assert_not_called()


def test_use_pushes_the_timer_forward_at_most_every_quarter(fake_sdk, monkeypatch):
    from docsgpt.sandbox import boxd as mod

    now = [1000.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    box = mod.BoxdSandbox(api_key="k", delete_after=3600)
    box.open("conv-1")
    now[0] += 899
    box.exec("conv-1", "print(1)")
    _machines(box).set_delete_after.assert_not_called()
    now[0] += 2
    box.exec("conv-1", "print(1)")
    box.put_file("conv-1", "a.txt", b"x")
    _machines(box).set_delete_after.assert_called_once_with("m-1", 3600)


def test_a_reattached_machine_gets_its_timer_pushed_forward(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", delete_after=3600)
    _machines(box).machines["old"] = _FakeMachine("old", labels={"docsgpt_session_id": "conv-1"})
    box.open("conv-1")
    _machines(box).set_delete_after.assert_called_once_with("old", 3600)


def test_a_failed_timer_refresh_does_not_fail_the_run(fake_sdk):
    from docsgpt.sandbox.boxd import BoxdSandbox

    box = BoxdSandbox(api_key="k", delete_after=3600)
    _machines(box).machines["old"] = _FakeMachine("old", labels={"docsgpt_session_id": "conv-1"})
    _machines(box).set_delete_after.side_effect = RuntimeError("busy")
    box.open("conv-1")
    _reply_to_runs(box, stdout="ok\n")
    assert box.exec("conv-1", "print('ok')").ok


def test_adopt_and_release(sandbox):
    run = {"machine_id": "m-9", "workspace": _WS}
    assert sandbox.adopt("conv-1", run) == {}
    assert sandbox._get_handle("conv-1").machine_id == "m-9"
    sandbox.release_adopted("conv-1", run)
    with pytest.raises(KeyError):
        sandbox._get_handle("conv-1")
    assert _machines(sandbox).deleted == []


def test_manager_sees_detached_support(sandbox):
    from docsgpt.sandbox.manager import SandboxManager

    assert SandboxManager(backend=sandbox, max_ttl=60, max_sessions=4).supports_detached() is True


# --- Registry wiring -----------------------------------------------------


def test_sandbox_creator_selects_boxd_backend(fake_sdk, monkeypatch):
    from docsgpt.core.settings import settings
    from docsgpt.sandbox import sandbox_creator as sc
    from docsgpt.sandbox.boxd import BoxdSandbox

    monkeypatch.setattr(settings, "BOXD_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "BOXD_ORG", "acme", raising=False)
    monkeypatch.setattr(settings, "BOXD_REGION", "nyc", raising=False)
    monkeypatch.setattr(settings, "BOXD_NAME_PREFIX", "dg", raising=False)
    monkeypatch.setattr(settings, "BOXD_MAX_MACHINES", 7, raising=False)
    monkeypatch.setattr(settings, "BOXD_DELETE_AFTER", 90, raising=False)
    sc.SandboxCreator.reset()
    backend = sc.SandboxCreator.create_backend("boxd")
    assert isinstance(backend, BoxdSandbox)
    assert backend._org == "acme" and backend._client.region == "nyc"
    assert backend._name_prefix == "dg" and backend._max_machines == 7
    assert backend._delete_after == 5400
    sc.SandboxCreator.reset()


@pytest.mark.parametrize(
    "minutes, max_ttl, max_timeout, expected",
    [(0, 1200, 1000, 0), (60, 1200, 1000, 3600), (5, 1200, 1000, 1660), (60, 7200, 1000, 9660)],
)
def test_factory_keeps_the_timer_longer_than_a_session_and_a_run(
    fake_sdk, monkeypatch, minutes, max_ttl, max_timeout, expected
):
    from docsgpt.core.settings import settings
    from docsgpt.sandbox import sandbox_creator as sc

    monkeypatch.setattr(settings, "BOXD_DELETE_AFTER", minutes, raising=False)
    monkeypatch.setattr(settings, "SANDBOX_MAX_TTL", max_ttl, raising=False)
    monkeypatch.setattr(settings, "SANDBOX_EXEC_MAX_TIMEOUT", max_timeout, raising=False)
    assert sc._boxd_delete_after() == expected


def test_sandbox_creator_without_a_key_fails_clearly(fake_sdk, monkeypatch):
    from docsgpt.core.settings import settings
    from docsgpt.sandbox import sandbox_creator as sc

    monkeypatch.setattr(settings, "BOXD_API_KEY", None, raising=False)
    with pytest.raises(ValueError, match="BOXD_API_KEY"):
        sc.SandboxCreator.create_backend("boxd")
