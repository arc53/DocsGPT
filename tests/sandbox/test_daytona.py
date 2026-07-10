"""Unit tests for DaytonaSandbox with the Daytona SDK fully mocked (no cloud calls)."""

import sys
import types
from unittest import mock

import pytest

from application.sandbox.base import ExecResult


# --- Fakes mirroring the real Daytona SDK shapes -------------------------


class _FakeArtifacts:
    def __init__(self, stdout="", charts=None):
        self.stdout = stdout
        self.charts = charts or []


class _FakeChart:
    def __init__(self, png):
        self.png = png


class _FakeExecuteResponse:
    def __init__(self, exit_code=0, result="", artifacts=None):
        self.exit_code = exit_code
        self.result = result
        self.artifacts = artifacts


class _FakeFileInfo:
    def __init__(self, name, is_dir=False, size=0):
        self.name = name
        self.is_dir = is_dir
        self.size = size


class _FakeProcess:
    def __init__(self):
        self.code_run = mock.Mock(return_value=_FakeExecuteResponse(exit_code=0, result="hi"))


class _FakeFS:
    def __init__(self):
        self.create_folder = mock.Mock()
        self.upload_file = mock.Mock()
        self.download_file = mock.Mock(return_value=b"payload")
        self.delete_file = mock.Mock()
        self.get_file_info = mock.Mock(return_value=_FakeFileInfo("a.txt", size=7))
        # Path-aware tree: maps an absolute dir to the entries it contains. The
        # real Daytona fs.list_files is single-level and returns basenames, so the
        # backend must recurse into subdirs itself. Default tree is a single file.
        self.tree = {}
        self.list_files = mock.Mock(side_effect=self._list_files)

    def _list_files(self, path):
        if self.tree:
            return self.tree.get(path, [])
        return [_FakeFileInfo("a.txt")]


class _FakeSandbox:
    def __init__(self, sandbox_id="sbx-1", labels=None, state="started"):
        self.id = sandbox_id
        self.labels = labels or {}
        self.state = state
        self.process = _FakeProcess()
        self.fs = _FakeFS()


class _FakeDaytonaClient:
    def __init__(self, config=None):
        self.config = config
        self.created = []
        self.deleted = []
        self.started = []
        # Sandboxes pretend to already exist in the cloud (cross-restart reattach).
        self.existing = []
        self.create = mock.Mock(side_effect=self._create)
        self.delete = mock.Mock(side_effect=self._delete)
        self.list = mock.Mock(side_effect=self._list)
        self.start = mock.Mock(side_effect=self._start)
        self.get = mock.Mock(side_effect=self._get)

    def _get(self, sandbox_id_or_name):
        for _, sandbox in self.created:
            if sandbox.id == sandbox_id_or_name:
                return sandbox
        for sandbox in self.existing:
            if sandbox.id == sandbox_id_or_name:
                return sandbox
        raise KeyError(sandbox_id_or_name)

    def _create(self, params=None, timeout=60):
        labels = getattr(params, "labels", None) or {}
        sandbox = _FakeSandbox(sandbox_id=f"sbx-{len(self.created) + 1}", labels=labels)
        self.created.append((params, sandbox))
        return sandbox

    def _delete(self, sandbox, timeout=60):
        self.deleted.append(sandbox)

    def _list(self, query=None):
        wanted = getattr(query, "labels", None) or {}
        for sandbox in self.existing:
            labels = getattr(sandbox, "labels", {})
            if all(labels.get(k) == v for k, v in wanted.items()):
                yield sandbox

    def _start(self, sandbox, timeout=60):
        self.started.append(sandbox)
        sandbox.state = "started"


@pytest.fixture()
def fake_sdk(monkeypatch):
    """Install a fake ``daytona`` module so DaytonaSandbox imports it without the real SDK."""
    captured = {}

    def _config(**kwargs):
        captured["config"] = kwargs
        return types.SimpleNamespace(**kwargs)

    def _params(**kwargs):
        return types.SimpleNamespace(**kwargs)

    def _list_query(**kwargs):
        return types.SimpleNamespace(**kwargs)

    class _SandboxState:
        STARTED = "started"
        STOPPED = "stopped"

    fake_module = types.ModuleType("daytona")
    fake_module.Daytona = _FakeDaytonaClient
    fake_module.DaytonaConfig = _config
    fake_module.CreateSandboxFromSnapshotParams = _params
    fake_module.ListSandboxesQuery = _list_query
    fake_module.SandboxState = _SandboxState
    monkeypatch.setitem(sys.modules, "daytona", fake_module)
    captured["client_cls"] = _FakeDaytonaClient
    return captured


@pytest.fixture()
def sandbox(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    return DaytonaSandbox(api_key="dtn_test", language="python")


# --- Construction --------------------------------------------------------


def test_requires_api_key(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    with pytest.raises(ValueError):
        DaytonaSandbox(api_key="")


def test_config_forwards_optional_knobs(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    DaytonaSandbox(api_key="k", api_url="https://api.example", target="us")
    cfg = fake_sdk["config"]
    assert cfg["api_key"] == "k"
    assert cfg["api_url"] == "https://api.example"
    assert cfg["target"] == "us"


def test_config_omits_unset_knobs(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    DaytonaSandbox(api_key="k")
    assert set(fake_sdk["config"].keys()) == {"api_key"}


# --- Lifecycle -----------------------------------------------------------


def test_open_creates_sandbox_and_primes_workspace(sandbox):
    handle_id = sandbox.open("conv-1")
    assert handle_id == "sbx-1"
    assert sandbox._client.create.call_count == 1
    _, created = sandbox._client.created[0]
    created.fs.create_folder.assert_called_once()
    # label binds the cloud sandbox to the docsgpt session id
    params = sandbox._client.create.call_args.args[0]
    assert params.labels["docsgpt_session_id"] == "conv-1"


def test_open_twice_reuses_handle(sandbox):
    sandbox.open("conv-1")
    sandbox.open("conv-1")
    assert sandbox._client.create.call_count == 1  # created once


def test_attach_reuses_warm_handle(sandbox):
    sandbox.open("conv-1")
    assert sandbox.attach("conv-1") == "sbx-1"
    assert sandbox._client.create.call_count == 1


def test_attach_opens_when_no_handle(sandbox):
    assert sandbox.attach("conv-1") == "sbx-1"
    assert sandbox._client.create.call_count == 1


def test_close_deletes_cloud_sandbox(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.close("conv-1")
    sandbox._client.delete.assert_called_once_with(created)
    assert not sandbox._handles


def test_close_unknown_session_is_noop(sandbox):
    sandbox.close("never-opened")
    sandbox._client.delete.assert_not_called()


def test_close_swallows_delete_errors(sandbox):
    sandbox.open("conv-1")
    sandbox._client.delete.side_effect = RuntimeError("cloud down")
    sandbox.close("conv-1")  # must not raise
    assert not sandbox._handles


def test_remove_path_deletes_directory_recursively(sandbox):
    """A token DIRECTORY is removed with a recursive delete (daytona delete_file recursive=True)."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.remove_path("conv-1", "artifacts/tok")
    remote, kwargs = created.fs.delete_file.call_args.args, created.fs.delete_file.call_args.kwargs
    assert remote[0].endswith("/artifacts/tok")
    assert kwargs.get("recursive") is True


def test_remove_path_refuses_workspace_root(sandbox):
    """remove_path must never delete the workspace root itself."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.remove_path("conv-1", ".")
    created.fs.delete_file.assert_not_called()


def test_remove_path_falls_back_to_rm_when_no_recursive_kwarg(sandbox):
    """When delete_file lacks the recursive kwarg, fall back to a contained rm -rf."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]

    def _no_recursive(path, recursive=None):
        if recursive:
            raise TypeError("delete_file() got an unexpected keyword argument 'recursive'")
        raise RuntimeError("cannot delete a directory")

    created.fs.delete_file.side_effect = _no_recursive
    created.process.exec = mock.Mock()
    sandbox.remove_path("conv-1", "artifacts/tok")
    cmd = created.process.exec.call_args.args[0]
    assert cmd.startswith("rm -rf ") and cmd.endswith("/artifacts/tok'")


def test_remove_path_never_raises(sandbox):
    """Any backend error during cleanup is swallowed (cleanup must not fail an op)."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.delete_file.side_effect = RuntimeError("cloud down")
    created.process.exec = mock.Mock(side_effect=RuntimeError("also down"))
    sandbox.remove_path("conv-1", "artifacts/tok")  # must not raise


def test_close_handle_deletes_captured_sandbox(sandbox):
    """close_handle tears down the captured sandbox and drops the registry entry."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.close_handle("conv-1", created.id)
    sandbox._client.delete.assert_called_once_with(created)
    assert not sandbox._handles


def test_close_handle_leaves_reopened_sandbox_intact(sandbox):
    """A concurrent re-open replaced the handle: close_handle deletes the OLD one by id only."""
    sandbox.open("conv-1")
    _, old = sandbox._client.created[0]
    # Simulate a concurrent re-open: a new sandbox is registered for the same session.
    new = _FakeSandbox(sandbox_id="sbx-new", labels={"docsgpt_session_id": "conv-1"})
    from application.sandbox.daytona import _Handle, _WORKSPACE_ROOT

    sandbox._handles["conv-1"] = _Handle(new, new.id, _WORKSPACE_ROOT)
    sandbox._client.created.append((None, new))  # so client.get(new.id) could resolve

    sandbox.close_handle("conv-1", old.id)  # close the OLD captured id

    # The OLD sandbox was deleted (fetched by id); the NEW handle stays registered.
    assert old in sandbox._client.deleted
    assert new not in sandbox._client.deleted
    assert sandbox._handles["conv-1"].sandbox_id == "sbx-new"


def test_invalid_session_id_rejected(sandbox):
    with pytest.raises(ValueError):
        sandbox.open("../etc/passwd")


def test_open_reattaches_to_existing_cloud_sandbox(sandbox):
    """A still-live labelled sandbox (e.g. after a process restart) is reused, not re-created."""
    prior = _FakeSandbox(sandbox_id="sbx-prior", labels={"docsgpt_session_id": "conv-1"})
    sandbox._client.existing = [prior]
    handle_id = sandbox.open("conv-1")
    assert handle_id == "sbx-prior"
    assert sandbox._client.create.call_count == 0  # no new paid sandbox
    assert sandbox._handles["conv-1"].sandbox is prior


def test_open_reattach_starts_stopped_sandbox(sandbox):
    prior = _FakeSandbox(sandbox_id="sbx-stopped", labels={"docsgpt_session_id": "conv-1"}, state="stopped")
    sandbox._client.existing = [prior]
    sandbox.open("conv-1")
    sandbox._client.start.assert_called_once()
    assert prior.state == "started"
    assert sandbox._client.create.call_count == 0


def test_open_ignores_existing_for_other_session(sandbox):
    other = _FakeSandbox(sandbox_id="sbx-other", labels={"docsgpt_session_id": "conv-OTHER"})
    sandbox._client.existing = [other]
    handle_id = sandbox.open("conv-1")
    assert handle_id == "sbx-1"  # a fresh one is created
    assert sandbox._client.create.call_count == 1


def test_open_enforces_concurrency_cap(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_sandboxes=2)
    s.open("conv-1")
    s.open("conv-2")
    with pytest.raises(RuntimeError):
        s.open("conv-3")
    assert s._client.create.call_count == 2


def test_open_deletes_sandbox_if_registration_fails(sandbox):
    """Crash between create and register must delete the orphaned cloud sandbox."""

    class _BoomSandbox(_FakeSandbox):
        def __init__(self):
            super().__init__(sandbox_id="sbx-boom")

        @property
        def id(self):
            raise RuntimeError("id blew up")

        @id.setter
        def id(self, value):
            pass  # absorb _FakeSandbox.__init__'s assignment

    boom = _BoomSandbox()
    sandbox._client.create.side_effect = lambda params=None, timeout=60: boom
    with pytest.raises(RuntimeError):
        sandbox.open("conv-1")
    sandbox._client.delete.assert_called_once_with(boom)
    assert "conv-1" not in sandbox._handles


# --- Execution -----------------------------------------------------------


def test_exec_maps_success_to_exec_result(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.process.code_run.return_value = _FakeExecuteResponse(
        exit_code=0, result="ignored", artifacts=_FakeArtifacts(stdout="42\n")
    )
    res = sandbox.exec("conv-1", "print(42)")
    assert isinstance(res, ExecResult)
    assert res.ok and res.stdout == "42\n" and res.exit_code == 0


def test_exec_prepends_workspace_chdir(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.exec("conv-1", "print('x')")
    sent_code = created.process.code_run.call_args.args[0]
    assert "_os.chdir" in sent_code and "print('x')" in sent_code


def test_exec_nonzero_exit_is_error(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.process.code_run.return_value = _FakeExecuteResponse(
        exit_code=1, artifacts=_FakeArtifacts(stdout="Traceback...")
    )
    res = sandbox.exec("conv-1", "raise ValueError()")
    assert res.status == "error" and res.exit_code == 1
    assert res.error_name == "ExecutionError"


def test_exec_captures_charts_as_plots(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.process.code_run.return_value = _FakeExecuteResponse(
        exit_code=0, artifacts=_FakeArtifacts(stdout="", charts=[_FakeChart("BASE64PNG")])
    )
    res = sandbox.exec("conv-1", "plt.plot(...)")
    assert len(res.plots) == 1
    assert res.plots[0].format == "png" and res.plots[0].content_base64 == "BASE64PNG"


def test_exec_sdk_error_becomes_error_result(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.process.code_run.side_effect = RuntimeError("boom")
    res = sandbox.exec("conv-1", "1/0")
    assert res.status == "error" and res.error_name == "RuntimeError"
    assert res.exit_code == -1


def test_exec_requires_open_session(sandbox):
    with pytest.raises(KeyError):
        sandbox.exec("missing", "1+1")


# --- File transfer -------------------------------------------------------


def test_put_file_uploads_under_workspace(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    sandbox.put_file("conv-1", "out/data.csv", b"a,b\n")
    data, remote = created.fs.upload_file.call_args.args
    assert data == b"a,b\n"
    assert remote.endswith("/docsgpt-sandbox/out/data.csv")


def test_put_file_creates_parent_dirs(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.create_folder.reset_mock()
    sandbox.put_file("conv-1", "out/nested/data.csv", b"x")
    folder = created.fs.create_folder.call_args.args[0]
    assert folder.endswith("/docsgpt-sandbox/out/nested")


def test_put_file_swallows_existing_folder_error(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.create_folder.side_effect = RuntimeError("already exists")
    sandbox.put_file("conv-1", "out/data.csv", b"x")  # must not raise
    created.fs.upload_file.assert_called_once()


def test_put_file_rejects_nul_path(sandbox):
    sandbox.open("conv-1")
    with pytest.raises(ValueError):
        sandbox.put_file("conv-1", "bad\x00name.csv", b"x")


def test_put_file_error_wrapped_as_ioerror(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.upload_file.side_effect = RuntimeError("internal://api.daytona/upload")
    with pytest.raises(IOError) as exc:
        sandbox.put_file("conv-1", "data.csv", b"x")
    assert "api.daytona" not in str(exc.value)


def test_get_file_error_wrapped_as_ioerror(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.download_file.side_effect = RuntimeError("internal://api.daytona/download")
    with pytest.raises(IOError) as exc:
        sandbox.get_file("conv-1", "a.txt")
    assert "api.daytona" not in str(exc.value)


def test_put_file_rejects_absolute_path(sandbox):
    sandbox.open("conv-1")
    with pytest.raises(ValueError):
        sandbox.put_file("conv-1", "/etc/passwd", b"x")


def test_put_file_rejects_traversal(sandbox):
    sandbox.open("conv-1")
    with pytest.raises(ValueError):
        sandbox.put_file("conv-1", "../../escape", b"x")


def test_get_file_returns_bytes(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.download_file.return_value = b"hello"
    created.fs.get_file_info.return_value = _FakeFileInfo("a.txt", size=5)
    assert sandbox.get_file("conv-1", "a.txt") == b"hello"


def test_get_file_too_large_rejected(sandbox):
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_file_bytes=3)
    s.open("conv-1")
    _, created = s._client.created[0]
    created.fs.get_file_info.return_value = _FakeFileInfo("a.txt", size=99)
    with pytest.raises(IOError):
        s.get_file("conv-1", "a.txt")


def test_get_file_post_download_size_guard(sandbox):
    """Oversized payloads are rejected even when get_file_info reports no size."""
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_file_bytes=3)
    s.open("conv-1")
    _, created = s._client.created[0]
    created.fs.get_file_info.return_value = _FakeFileInfo("a.txt", size=None)
    created.fs.download_file.return_value = b"way-too-long"
    with pytest.raises(IOError):
        s.get_file("conv-1", "a.txt")


def test_get_file_none_payload_raises(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.download_file.return_value = None
    with pytest.raises(IOError):
        sandbox.get_file("conv-1", "a.txt")


_WS = "/home/daytona/docsgpt-sandbox"


def test_list_files_returns_top_level_files(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.tree = {
        _WS: [_FakeFileInfo("a.txt"), _FakeFileInfo("nested", is_dir=True), _FakeFileInfo("b.json")],
        f"{_WS}/nested": [],
    }
    assert sorted(sandbox.list_files("conv-1")) == ["a.txt", "b.json"]


def test_list_files_recurses_into_subdirs(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.tree = {
        _WS: [_FakeFileInfo("top.txt"), _FakeFileInfo("sub", is_dir=True)],
        f"{_WS}/sub": [_FakeFileInfo("a.txt"), _FakeFileInfo("deep", is_dir=True)],
        f"{_WS}/sub/deep": [_FakeFileInfo("c.bin")],
    }
    assert sorted(sandbox.list_files("conv-1")) == ["sub/a.txt", "sub/deep/c.bin", "top.txt"]


def test_list_files_error_wrapped_as_ioerror(sandbox):
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.fs.list_files.side_effect = RuntimeError("internal://api.daytona/list")
    with pytest.raises(IOError) as exc:
        sandbox.list_files("conv-1")
    # generic error: no internal endpoint leaked to the model
    assert "api.daytona" not in str(exc.value)


# --- Output cap in _to_result --------------------------------------------


def test_to_result_truncates_stdout_over_cap(fake_sdk):
    """Stdout beyond max_output_bytes is byte-capped, noted, and flagged truncated."""
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_output_bytes=10)
    resp = _FakeExecuteResponse(exit_code=0, artifacts=_FakeArtifacts(stdout="X" * 100))
    res = s._to_result(resp)
    assert res.truncated is True
    prefix = res.stdout.split("\n[output truncated")[0]
    assert prefix == "X" * 10  # capped to exactly the byte budget before the note
    assert "[output truncated at 10 bytes]" in res.stdout


def test_to_result_keeps_small_stdout_intact(fake_sdk):
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_output_bytes=1000)
    res = s._to_result(_FakeExecuteResponse(exit_code=0, artifacts=_FakeArtifacts(stdout="hello")))
    assert res.truncated is False
    assert res.stdout == "hello"


def test_to_result_cap_disabled_by_default(fake_sdk):
    """max_output_bytes defaults to 0 (disabled): a large stdout is passed through whole."""
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k")
    res = s._to_result(_FakeExecuteResponse(exit_code=0, artifacts=_FakeArtifacts(stdout="Y" * 5000)))
    assert res.truncated is False
    assert res.stdout == "Y" * 5000


def test_to_result_truncation_bounds_error_value(fake_sdk):
    """On a nonzero exit the capped stdout (not the raw buffer) is what feeds error_value."""
    from application.sandbox.daytona import DaytonaSandbox

    s = DaytonaSandbox(api_key="k", max_output_bytes=10)
    res = s._to_result(_FakeExecuteResponse(exit_code=1, artifacts=_FakeArtifacts(stdout="E" * 100)))
    assert res.status == "error" and res.truncated is True
    assert res.error_value == res.stdout
    assert res.error_value.split("\n[output truncated")[0] == "E" * 10


# --- Wake an auto-stopped sandbox on the cached-handle path ---------------


def test_exec_wakes_auto_stopped_sandbox_and_retries(sandbox):
    """A cached handle to an auto-stopped sandbox: exec wakes it and retries once."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.state = "stopped"  # Daytona auto-stopped it under the still-cached handle
    created.process.code_run.side_effect = [
        RuntimeError("sandbox is stopped"),
        _FakeExecuteResponse(exit_code=0, artifacts=_FakeArtifacts(stdout="woke\n")),
    ]
    res = sandbox.exec("conv-1", "print('x')")
    assert res.ok and res.stdout == "woke\n"
    sandbox._client.start.assert_called_once()
    assert created.process.code_run.call_count == 2


def test_exec_does_not_retry_when_started(sandbox):
    """A started sandbox that raises is a genuine transport fault: no wake, no spurious retry."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.process.code_run.side_effect = RuntimeError("transport blip")
    res = sandbox.exec("conv-1", "print('x')")
    assert res.status == "error" and res.error_name == "RuntimeError"
    sandbox._client.start.assert_not_called()
    assert created.process.code_run.call_count == 1


def test_exec_no_retry_when_wake_fails(sandbox):
    """If the stopped sandbox cannot be started, exec returns the error without retrying."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.state = "stopped"
    sandbox._client.start.side_effect = RuntimeError("cannot start")
    created.process.code_run.side_effect = RuntimeError("stopped")
    res = sandbox.exec("conv-1", "print('x')")
    assert res.status == "error"
    assert created.process.code_run.call_count == 1


def test_put_file_wakes_auto_stopped_sandbox_and_retries(sandbox):
    """put_file wakes an auto-stopped sandbox and retries the upload once."""
    sandbox.open("conv-1")
    _, created = sandbox._client.created[0]
    created.state = "stopped"
    created.fs.upload_file.side_effect = [RuntimeError("stopped"), None]
    sandbox.put_file("conv-1", "data.csv", b"x")
    sandbox._client.start.assert_called_once()
    assert created.fs.upload_file.call_count == 2


def test_ensure_started_returns_false_when_get_fails(sandbox):
    """A failed refresh means we cannot wake, so no retry is attempted."""
    sandbox.open("conv-1")
    handle = sandbox._handles["conv-1"]
    sandbox._client.get = mock.Mock(side_effect=KeyError("gone"))
    assert sandbox._ensure_started(handle) is False


# --- from __future__ imports survive the workspace prelude ---------------


def test_with_workspace_cwd_hoists_future_import(sandbox):
    """A leading ``from __future__`` import stays the first statement of the wrapped code."""
    wrapped = sandbox._with_workspace_cwd("/ws", "from __future__ import annotations\nprint('hi')\n")
    assert wrapped.startswith("from __future__ import annotations\n")
    assert wrapped.index("from __future__") < wrapped.index("import os as _os")
    assert "_os.chdir('/ws')" in wrapped
    assert wrapped.rstrip().endswith("print('hi')")


def test_with_workspace_cwd_no_future_import_is_prelude_prefix(sandbox):
    """Without a future import the wrapper is just prelude + code, unchanged."""
    wrapped = sandbox._with_workspace_cwd("/ws", "print('hi')\n")
    assert wrapped.startswith("import os as _os\n")
    assert wrapped.endswith("print('hi')\n")


def test_split_leading_future_imports_multiple_with_comment():
    from application.sandbox.daytona import DaytonaSandbox

    code = "# header\nfrom __future__ import annotations\nfrom __future__ import division\nx = 1\n"
    hoisted, rest = DaytonaSandbox._split_leading_future_imports(code)
    assert "from __future__ import annotations" in hoisted
    assert "from __future__ import division" in hoisted
    assert rest == "x = 1\n"


def test_split_leading_future_imports_none():
    from application.sandbox.daytona import DaytonaSandbox

    hoisted, rest = DaytonaSandbox._split_leading_future_imports("x = 1\n")
    assert hoisted == "" and rest == "x = 1\n"


def test_split_leading_future_imports_adds_trailing_newline():
    from application.sandbox.daytona import DaytonaSandbox

    hoisted, rest = DaytonaSandbox._split_leading_future_imports("from __future__ import annotations")
    assert hoisted.endswith("\n")  # ensures the prelude begins on its own line
    assert rest == ""


# --- Registry wiring -----------------------------------------------------


def test_sandbox_creator_selects_daytona_backend(fake_sdk, monkeypatch):
    from application.core.settings import settings
    from application.sandbox import sandbox_creator as sc
    from application.sandbox.daytona import DaytonaSandbox

    monkeypatch.setattr(settings, "DAYTONA_API_KEY", "dtn_test", raising=False)
    sc.SandboxCreator.reset()
    backend = sc.SandboxCreator.create_backend("daytona")
    assert isinstance(backend, DaytonaSandbox)
    sc.SandboxCreator.reset()


@pytest.mark.parametrize("configured", [0, -1, -5])
def test_factory_clamps_nonpositive_auto_delete_interval(fake_sdk, monkeypatch, configured):
    """A never-expiring auto_delete_interval (<= 0) is replaced so orphans always expire."""
    from application.core.settings import settings
    from application.sandbox import sandbox_creator as sc

    monkeypatch.setattr(settings, "DAYTONA_API_KEY", "dtn_test", raising=False)
    monkeypatch.setattr(settings, "DAYTONA_AUTO_DELETE_INTERVAL", configured, raising=False)
    sc.SandboxCreator.reset()
    backend = sc.SandboxCreator.create_backend("daytona")
    assert backend._auto_delete_interval > 0
    sc.SandboxCreator.reset()


def test_factory_forwards_max_sandboxes(fake_sdk, monkeypatch):
    from application.core.settings import settings
    from application.sandbox import sandbox_creator as sc

    monkeypatch.setattr(settings, "DAYTONA_API_KEY", "dtn_test", raising=False)
    monkeypatch.setattr(settings, "DAYTONA_MAX_SANDBOXES", 7, raising=False)
    sc.SandboxCreator.reset()
    backend = sc.SandboxCreator.create_backend("daytona")
    assert backend._max_sandboxes == 7
    sc.SandboxCreator.reset()
