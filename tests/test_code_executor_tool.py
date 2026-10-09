"""Unit tests for CodeExecutorTool: payload shaping, mime/kind inference, and allowlist wiring.

These tests exercise the pure logic (no sandbox, no DB, no storage) so they
run in the fast unit suite. The end-to-end persistence path is covered by
``tests/integration/test_code_executor_e2e.py`` against a live gateway + PG.
"""

from __future__ import annotations

import uuid

import pytest

from docsgpt.agents.tools.code_executor import (
    CodeExecutorTool,
    _infer_mime,
    _kind_for_mime,
    _tail,
    _OUTPUT_TAIL_BYTES,
)
from docsgpt.sandbox.base import ExecResult, OpenedSession


class _FakeManager:
    """In-memory sandbox stand-in recording open/close and serving a fixed exec result."""

    def __init__(self, result: ExecResult, created: bool = True) -> None:
        self._result = result
        self._created = created
        self.closed: list = []
        self.opened: list = []
        self.put_files: list = []
        self.list_calls = 0

    def open(self, session_id, ttl=None):
        return self.open_session(session_id, ttl=ttl).handle

    def open_session(self, session_id, ttl=None):
        self.opened.append((session_id, ttl))
        return OpenedSession(session_id, self._created)

    def exec(self, session_id, code, timeout=None):
        return self._result

    def list_files(self, session_id):
        self.list_calls += 1
        return []

    def close(self, session_id):
        self.closed.append(session_id)

    def put_file(self, session_id, dest_path, data):
        self.put_files.append(dest_path)


def _tool() -> CodeExecutorTool:
    return CodeExecutorTool(
        tool_config={"conversation_id": "conv-1", "tool_id": "t1"},
        user_id="user-1",
    )


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------
def test_tail_returns_short_text_unchanged():
    assert _tail("hello") == "hello"
    assert _tail("") == ""
    assert _tail(None) == ""


def test_tail_truncates_to_trailing_window():
    head = "HEAD_MARKER" + "X" * (_OUTPUT_TAIL_BYTES + 500)
    long_text = head + "TAIL_MARKER"
    out = _tail(long_text)
    assert len(out) == _OUTPUT_TAIL_BYTES
    # The tail keeps the END of the stream (where errors/results land), not the head.
    assert out.endswith("TAIL_MARKER")
    assert "HEAD_MARKER" not in out


# ---------------------------------------------------------------------------
# Mime / kind inference
# ---------------------------------------------------------------------------
def test_infer_mime_known_and_unknown():
    assert _infer_mime("deck.pptx").endswith("presentationml.presentation")
    assert _infer_mime("report.pdf") == "application/pdf"
    assert _infer_mime("out.txt") == "text/plain"
    assert _infer_mime("data.csv") == "text/csv"
    assert _infer_mime("blob.weirdext") == "application/octet-stream"


def test_kind_for_mime_maps_office_and_media():
    assert _kind_for_mime("image/png") == "image"
    assert _kind_for_mime("application/pdf") == "document"
    assert _kind_for_mime(_infer_mime("deck.pptx")) == "presentation"
    assert _kind_for_mime(_infer_mime("sheet.xlsx")) == "spreadsheet"
    assert _kind_for_mime("text/html") == "html"
    assert _kind_for_mime("application/octet-stream") == "file"


# ---------------------------------------------------------------------------
# Payload shaping
# ---------------------------------------------------------------------------
def test_shape_payload_ok_with_artifacts():
    tool = _tool()
    artifacts = [{"artifact_id": "a1", "version": 1, "filename": "out.txt",
                  "mime_type": "text/plain", "size": 9}]
    result = ExecResult(status="ok", stdout="done\n", stderr="")
    payload = tool._shape_payload(result, artifacts, inputs_loaded=["inputs/seed.txt"])
    assert payload["status"] == "ok"
    assert payload["stdout_tail"] == "done\n"
    assert payload["artifacts"] == artifacts
    assert payload["inputs_loaded"] == ["inputs/seed.txt"]
    assert "error" not in payload
    # No raw bytes ever leak into the payload.
    assert "bytes" not in payload


def test_shape_payload_error_carries_clean_message_no_hang():
    tool = _tool()
    result = ExecResult(
        status="error", error_name="RuntimeError",
        error_value="kernel reset mid-run", exit_code=-1,
    )
    payload = tool._shape_payload(result, artifacts=[], inputs_loaded=[])
    assert payload["status"] == "error"
    assert payload["error"] == "RuntimeError: kernel reset mid-run"
    assert payload["artifacts"] == []


def test_shape_payload_includes_stderr_tail_only_when_present():
    tool = _tool()
    with_err = tool._shape_payload(
        ExecResult(status="ok", stdout="ok", stderr="warn"), [], []
    )
    assert with_err["stderr_tail"] == "warn"
    no_err = tool._shape_payload(ExecResult(status="ok", stdout="ok", stderr=""), [], [])
    assert "stderr_tail" not in no_err


# ---------------------------------------------------------------------------
# Session id resolution & timeout / ttl coercion
# ---------------------------------------------------------------------------
def test_resolve_session_id_prefers_conversation_then_run():
    conv = CodeExecutorTool({"conversation_id": "conv-1"}, user_id="u")
    assert conv._resolve_session_id() == "conv-1"
    run = CodeExecutorTool({"workflow_run_id": "run-9"}, user_id="u")
    assert run._resolve_session_id() == "run-9"
    none = CodeExecutorTool({}, user_id="u")
    assert none._resolve_session_id() is None


def test_resolve_session_id_sanitizes_disallowed_chars():
    tool = CodeExecutorTool({"conversation_id": "../evil id;rm"}, user_id="u")
    sid = tool._resolve_session_id()
    # Only [A-Za-z0-9_-] survives; path-traversal / shell chars are collapsed.
    import re

    assert re.fullmatch(r"[A-Za-z0-9_-]+", sid)


def test_exec_timeout_defaults_and_max_come_from_settings(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", 60, raising=False)
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_MAX_TIMEOUT", 1000, raising=False)
    assert CodeExecutorTool._exec_timeout() == 60.0
    assert CodeExecutorTool._max_exec_timeout() == 1000.0
    # A maximum below the default never lowers the default.
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_MAX_TIMEOUT", 30, raising=False)
    assert CodeExecutorTool._max_exec_timeout() == 60.0


def test_settings_default_the_max_timeout_to_1000():
    from docsgpt.core.settings.sandbox import SandboxSettings

    assert SandboxSettings.model_fields["SANDBOX_EXEC_MAX_TIMEOUT"].default == 1000
    assert SandboxSettings.model_fields["SANDBOX_EXEC_TIMEOUT"].default == 60


@pytest.mark.parametrize(
    "requested, effective, clamped",
    [
        (None, 60.0, False),
        (300, 300.0, False),
        ("300", 300.0, False),
        (" 240 ", 240.0, False),
        (120.0, 120.0, False),
        ("90.5", 90.0, False),
        (1000, 1000.0, False),
        (5000, 1000.0, True),
        ("5000", 1000.0, True),
        (0, 60.0, False),
        (-5, 60.0, False),
        ("abc", 60.0, False),
        ("", 60.0, False),
        (True, 60.0, False),
        ([300], 60.0, False),
        (float("nan"), 60.0, False),
        (float("inf"), 60.0, False),
    ],
)
def test_requested_timeout_is_coerced_and_clamped(monkeypatch, requested, effective, clamped):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", 60, raising=False)
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_MAX_TIMEOUT", 1000, raising=False)
    assert CodeExecutorTool._requested_timeout(requested) == (effective, clamped)


def test_run_code_schema_offers_a_timeout(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    timeout = _tool().get_actions_metadata()[0]["parameters"]["properties"]["timeout"]
    assert timeout["type"] == "integer"
    text = timeout["description"]
    assert "60" in text and "1000" in text
    # Rough budgets help the model pick a value instead of guessing.
    for budget in ("pip install", "office-convert", "OCR", "video"):
        assert budget in text, budget
    # Removed parameters stay removed.
    props = _tool().get_actions_metadata()[0]["parameters"]["properties"]
    assert "language" not in props and "libraries" not in props


class _RecordingManager(_FakeManager):
    def __init__(self, result: ExecResult, created: bool = False) -> None:
        super().__init__(result, created)
        self.exec_timeouts: list = []

    def exec(self, session_id, code, timeout=None):
        self.exec_timeouts.append(timeout)
        return self._result


def test_run_code_passes_the_requested_timeout_to_the_sandbox(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    manager = _RecordingManager(ExecResult(status="ok", stdout="ok"))
    payload = _run_with_fake_manager(monkeypatch, manager, code="render()", timeout=600, capture_artifacts=False)
    assert manager.exec_timeouts == [600.0]
    assert "timeout" not in payload  # not clamped: nothing to report


def test_run_code_without_a_timeout_uses_the_default(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    manager = _RecordingManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert manager.exec_timeouts == [60.0]


def test_a_clamped_timeout_is_reported_in_the_result(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    manager = _RecordingManager(ExecResult(status="ok", stdout="ok"))
    payload = _run_with_fake_manager(monkeypatch, manager, code="render()", timeout=3600, capture_artifacts=False)
    assert manager.exec_timeouts == [1000.0]
    assert "1000s" in payload["timeout"] and "3600" in payload["timeout"]


def test_timeout_below_the_max_says_to_pass_a_larger_timeout(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    tool = _tool()
    timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60s")
    err = tool._shape_payload(timed_out, [], [], timeout=60.0)["error"]
    assert "60s" in err and "`timeout`" in err and "1000" in err
    assert "cannot be raised" not in err
    # Splitting or backgrounding stays an option for work longer than any cap.
    assert "background" in err.lower()


def test_timeout_at_the_max_says_to_split_or_background(monkeypatch):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    tool = _tool()
    timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 1000s")
    err = tool._shape_payload(timed_out, [], [], timeout=1000.0)["error"]
    assert "1000s" in err and "maximum" in err
    assert "background" in err.lower() and "poll" in err.lower()
    assert "persist=false" in err
    # A non-timeout failure keeps the raw name/value.
    crashed = ExecResult(status="error", error_name="ValueError", error_value="boom")
    assert tool._shape_payload(crashed, [], [])["error"] == "ValueError: boom"


def test_out_of_memory_is_reported_as_such_not_as_a_timeout(monkeypatch, fresh_failures):
    _configure(monkeypatch, timeout=60, max_timeout=1000)
    oom = ExecResult(status="error", error_name="KernelDiedError", error_value="the kernel died", exit_code=-1,
                     out_of_memory=True)
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(oom, created=False), code="big()")
    assert payload["error"].lower().startswith("out of memory")
    assert "timed out" not in payload["error"].lower()
    assert any("chunks" in h for h in payload["hint"])


def test_is_timeout_detects_any_backend_naming():
    assert CodeExecutorTool._is_timeout(ExecResult(error_name="TimeoutError", error_value="x"))
    assert CodeExecutorTool._is_timeout(ExecResult(error_name="DaytonaTimeoutError"))
    assert CodeExecutorTool._is_timeout(ExecResult(error_value="process timed out"))
    assert not CodeExecutorTool._is_timeout(ExecResult(error_name="ValueError", error_value="boom"))


def test_coerce_int_and_keep_alive():
    assert CodeExecutorTool._coerce_int("3") == 3
    assert CodeExecutorTool._coerce_int(0) is None
    assert CodeExecutorTool._coerce_int(None) is None
    assert CodeExecutorTool._keep_alive(True, None) is True
    assert CodeExecutorTool._keep_alive(False, 30) is True
    assert CodeExecutorTool._keep_alive(False, None) is False


def test_keep_alive_is_the_default():
    # Unset means keep: files, installs and variables from one call are expected in the next.
    assert CodeExecutorTool._keep_alive(None, None) is True


def test_keep_alive_reads_string_forms():
    for closing in ("false", "False", " FALSE ", "0", "no", "No"):
        assert CodeExecutorTool._keep_alive(closing, None) is False, closing
    for keeping in ("true", "1", "yes", "anything"):
        assert CodeExecutorTool._keep_alive(keeping, None) is True, keeping
    # A positive ttl still keeps the session whatever persist says.
    assert CodeExecutorTool._keep_alive("false", 30) is True
    assert CodeExecutorTool._keep_alive(0, None) is False


def test_normalize_outputs():
    n = CodeExecutorTool._normalize_outputs
    assert n(["a.csv", "b.pdf"]) == ["a.csv", "b.pdf"]
    assert n("report.pdf") == ["report.pdf"]      # a bare string is tolerated
    assert n([" x ", "", 5, "y"]) == ["x", "y"]   # stripped; empties/non-strings dropped
    assert n([]) is None
    assert n(None) is None
    assert n("   ") is None


# ---------------------------------------------------------------------------
# Action metadata / approval surface
# ---------------------------------------------------------------------------
def test_run_code_metadata_reflects_require_approval():
    gated = CodeExecutorTool({"require_approval": True}, user_id="u")
    meta = gated.get_actions_metadata()[0]
    assert meta["name"] == "run_code"
    assert meta["require_approval"] is True
    assert "code" in meta["parameters"]["required"]
    assert gated.preview_decision("run_code", {}) == (True, False)

    ungated = CodeExecutorTool({}, user_id="u")
    assert ungated.get_actions_metadata()[0]["require_approval"] is False
    assert ungated.preview_decision("run_code", {}) == (False, False)
    # An unknown action always requires approval (fail closed).
    assert ungated.preview_decision("other", {}) == (True, False)


def test_config_requirements_is_empty():
    # Approval is an action-level flag (see test_run_code_metadata_reflects_require_approval)
    # and the sandbox backend is a deployment-level setting, so the tool advertises no
    # user-configurable requirements.
    assert CodeExecutorTool({}, user_id="u").get_config_requirements() == {}


def test_execute_action_rejects_unknown_action_and_missing_code():
    tool = _tool()
    assert tool.execute_action("nope")["status"] == "error"
    missing = tool.execute_action("run_code", code="   ")
    assert missing["status"] == "error"
    assert "code is required" in missing["error"]


def test_execute_action_requires_user_and_parent():
    no_user = CodeExecutorTool({"conversation_id": "c"}, user_id=None)
    out = no_user.execute_action("run_code", code="print(1)")
    assert out["status"] == "error" and "user_id" in out["error"]

    no_parent = CodeExecutorTool({}, user_id="u")
    out2 = no_parent.execute_action("run_code", code="print(1)")
    assert out2["status"] == "error" and "conversation_id" in out2["error"]


# ---------------------------------------------------------------------------
# Allowlist wiring
# ---------------------------------------------------------------------------
def test_tool_manager_injects_user_and_conversation():
    """code_executor must be in the per-user allowlist so it receives user_id/conversation_id."""
    # Importing the app first resolves the mcp_tool<->api.user import cycle that
    # ToolManager's eager tool discovery would otherwise trip in a bare process.
    import docsgpt.app  # noqa: F401
    from docsgpt.agents.tools.tool_manager import ToolManager

    tm = ToolManager(config={})
    tool = tm.load_tool(
        "code_executor",
        {"conversation_id": "conv-xyz", "tool_id": "tool-abc", "require_approval": True},
        user_id="user-42",
    )
    assert isinstance(tool, CodeExecutorTool)
    assert tool.user_id == "user-42"
    assert tool.conversation_id == "conv-xyz"
    assert tool.tool_id == "tool-abc"
    assert tool._require_approval is True


# ---------------------------------------------------------------------------
# Keep-alive vs. close behavior
# ---------------------------------------------------------------------------
def _run_with_fake_manager(monkeypatch, manager, **run_kwargs):
    from docsgpt.agents.tools import code_executor as ce

    monkeypatch.setattr(ce.SandboxCreator, "get_manager", lambda: manager)
    return _tool().execute_action("run_code", **run_kwargs)


def test_session_kept_alive_by_default(monkeypatch):
    # Closing after every run deleted the Daytona sandbox, so the next call lost the
    # files, the pip installs and the variables the model had just made.
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    payload = _run_with_fake_manager(
        monkeypatch, manager, code="print(1)", capture_artifacts=False
    )
    assert payload["status"] == "ok"
    assert manager.closed == []


def test_default_keep_alive_asks_for_the_full_idle_ttl(monkeypatch):
    """A session another tool opened at a short TTL must not be reaped under the model."""
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_MAX_TTL", 1200, raising=False)
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert manager.opened == [("conv-1", 1200.0)]

    explicit = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(monkeypatch, explicit, code="print(1)", ttl=90, capture_artifacts=False)
    assert explicit.opened == [("conv-1", 90)]


def test_session_closed_when_persist_false(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(
        monkeypatch, manager, code="print(1)", persist=False, capture_artifacts=False
    )
    assert manager.closed == ["conv-1"]
    assert manager.opened == [("conv-1", None)]


def test_session_closed_when_persist_is_the_string_false(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(
        monkeypatch, manager, code="print(1)", persist="false", capture_artifacts=False
    )
    assert manager.closed == ["conv-1"]


def test_result_reports_a_new_session(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"), created=True)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert payload["session"] == "new"


def test_result_reports_a_reused_session(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"), created=False)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert payload["session"] == "reused"


def test_failed_runs_still_report_the_session(monkeypatch):
    errored = _FakeManager(ExecResult(status="error", error_name="NameError", error_value="x"), created=True)
    payload = _run_with_fake_manager(monkeypatch, errored, code="x", capture_artifacts=False)
    assert payload["status"] == "error" and payload["session"] == "new"

    class _ExecRaises(_FakeManager):
        def exec(self, session_id, code, timeout=None):
            raise RuntimeError("transport")

    raising = _ExecRaises(ExecResult(), created=False)
    payload = _run_with_fake_manager(monkeypatch, raising, code="print(1)", capture_artifacts=False)
    assert payload["status"] == "error" and payload["session"] == "reused"


def test_a_failed_input_staging_reports_the_session(monkeypatch):
    from docsgpt.agents.tools import code_executor as ce

    monkeypatch.setattr(ce.CodeExecutorTool, "_materialize_inputs", lambda self, *a: {"error": "nope"})
    manager = _FakeManager(ExecResult(status="ok"), created=True)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", inputs=["A1"])
    assert payload == {"status": "error", "error": "nope", "session": "new"}


def test_an_unavailable_sandbox_reports_no_session(monkeypatch):
    class _OpenFails(_FakeManager):
        def open_session(self, session_id, ttl=None):
            raise RuntimeError("down")

    payload = _run_with_fake_manager(monkeypatch, _OpenFails(ExecResult()), code="print(1)")
    assert payload["status"] == "error" and "session" not in payload


def test_session_kept_alive_on_persist(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(
        monkeypatch, manager, code="print(1)", persist=True, capture_artifacts=False
    )
    assert manager.closed == []


def test_session_kept_alive_on_positive_ttl(monkeypatch):
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"))
    _run_with_fake_manager(
        monkeypatch, manager, code="print(1)", ttl=30, capture_artifacts=False
    )
    assert manager.closed == []


def test_invalidated_runtime_skips_post_exec_artifact_capture(monkeypatch):
    manager = _FakeManager(
        ExecResult(
            status="error",
            error_name="TimeoutError",
            error_value="execution exceeded 60s",
            runtime_invalidated=True,
        )
    )

    payload = _run_with_fake_manager(monkeypatch, manager, code="while True: pass", persist=True)

    assert payload["status"] == "error"
    assert "timed out" in payload["error"].lower()
    # The pre-exec signature snapshot lists files once; a post-exec capture
    # would issue a second list against the now-destroyed runtime.
    assert manager.list_calls == 1


# ---------------------------------------------------------------------------
# Input materialization: short-ref + uuid resolution (no live sandbox/DB)
# ---------------------------------------------------------------------------
_ART_ID = str(uuid.uuid4())


class _InputManager:
    """Records files staged into the workspace by _materialize_inputs."""

    def __init__(self) -> None:
        self.put_files: dict = {}

    def put_file(self, session_id, dest_path, data):
        self.put_files[dest_path] = data


def _patch_input_repo(monkeypatch, *, found_position: bool, conv: str):
    """Patch db_readonly + ArtifactsRepository so a ref/uuid resolves only within ``conv``."""
    from docsgpt.agents.tools import code_executor as ce

    class _Repo:
        def __init__(self, conn):
            pass

        def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
            if not found_position or n != 1 or conversation_id != conv:
                return None
            return _ART_ID

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            if conversation_id != conv:
                return None
            return {"id": artifact_id, "current_version": 1, "title": "seed.csv"}

        def get_version(self, artifact_id, version):
            return {"filename": "seed.csv", "storage_path": f"inputs/u/artifacts/{artifact_id}/v1/seed.csv"}

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    class _Storage:
        def get_file(self, path):
            import io

            return io.BytesIO(b"col\n1\n")

    monkeypatch.setattr(ce, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(ce, "ArtifactsRepository", _Repo)
    monkeypatch.setattr(ce.StorageCreator, "get_storage", staticmethod(lambda: _Storage()))


def test_materialize_inputs_accepts_short_ref(monkeypatch):
    _patch_input_repo(monkeypatch, found_position=True, conv="conv-1")
    manager = _InputManager()
    out = _tool()._materialize_inputs(manager, "conv-1", ["A1"])
    assert "error" not in out
    assert out["loaded"] == ["inputs/seed.csv"]
    assert manager.put_files["inputs/seed.csv"] == b"col\n1\n"


def test_materialize_inputs_accepts_uuid(monkeypatch):
    _patch_input_repo(monkeypatch, found_position=False, conv="conv-1")
    manager = _InputManager()
    out = _tool()._materialize_inputs(manager, "conv-1", [_ART_ID])
    assert "error" not in out
    assert out["loaded"] == ["inputs/seed.csv"]


def test_materialize_inputs_out_of_range_ref_is_clean_error(monkeypatch):
    _patch_input_repo(monkeypatch, found_position=True, conv="conv-1")
    manager = _InputManager()
    out = _tool()._materialize_inputs(manager, "conv-1", ["A2"])
    assert "A2" in out["error"]
    assert "not found in this conversation/run" in out["error"]
    assert manager.put_files == {}


def test_materialize_inputs_rejects_oversize_by_declared_size(monkeypatch):
    """An input whose declared version ``size`` exceeds SANDBOX_MAX_INPUT_BYTES is rejected pre-read."""
    from docsgpt.agents.tools import code_executor as ce
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_MAX_INPUT_BYTES", 100, raising=False)

    class _Repo:
        def __init__(self, conn):
            pass

        def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
            return None

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            if conversation_id != "conv-1":
                return None
            return {"id": artifact_id, "current_version": 1, "title": "big.csv"}

        def get_version(self, artifact_id, version):
            return {
                "filename": "big.csv",
                "size": 10_000,  # far over the 100-byte cap
                "storage_path": f"inputs/u/artifacts/{artifact_id}/v1/big.csv",
            }

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    class _Storage:
        def get_file(self, path):
            raise AssertionError("bytes must not be read when declared size exceeds the cap")

    monkeypatch.setattr(ce, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(ce, "ArtifactsRepository", _Repo)
    monkeypatch.setattr(ce.StorageCreator, "get_storage", staticmethod(lambda: _Storage()))

    manager = _InputManager()
    out = _tool()._materialize_inputs(manager, "conv-1", [_ART_ID])
    assert "exceeds" in out["error"] and "sandbox input limit" in out["error"]
    assert manager.put_files == {}  # nothing staged


def test_materialize_inputs_dedupes_same_filename(monkeypatch):
    """Two inputs whose current versions share a filename stage to DISTINCT inputs/ paths."""
    from docsgpt.agents.tools import code_executor as ce

    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())

    class _Repo:
        def __init__(self, conn):
            pass

        def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
            return None

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            if conversation_id != "conv-1":
                return None
            return {"id": artifact_id, "current_version": 1, "title": "seed.csv"}

        def get_version(self, artifact_id, version):
            # Both inputs carry the SAME current filename but distinct stored bytes.
            return {"filename": "seed.csv", "storage_path": f"p/{artifact_id}.csv"}

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    class _Storage:
        def get_file(self, path):
            import io

            return io.BytesIO(path.encode())  # distinct bytes per artifact path

    monkeypatch.setattr(ce, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(ce, "ArtifactsRepository", _Repo)
    monkeypatch.setattr(ce.StorageCreator, "get_storage", staticmethod(lambda: _Storage()))

    manager = _InputManager()
    out = _tool()._materialize_inputs(manager, "conv-1", [id_a, id_b])

    assert "error" not in out
    # The colliding second input is suffixed before the extension; both are reported.
    assert out["loaded"] == ["inputs/seed.csv", "inputs/seed-2.csv"]
    assert set(manager.put_files) == {"inputs/seed.csv", "inputs/seed-2.csv"}
    # Each path holds its own artifact's bytes (no clobber).
    assert manager.put_files["inputs/seed.csv"] != manager.put_files["inputs/seed-2.csv"]


# ---------------------------------------------------------------------------
# Description: what the model is told, per backend
# ---------------------------------------------------------------------------
def _configure(
    monkeypatch,
    backend: str = "jupyter",
    snapshot=None,
    ttl: int = 1200,
    timeout: int = 60,
    max_timeout: int = 1000,
) -> None:
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", backend, raising=False)
    monkeypatch.setattr(settings_module.settings, "DAYTONA_SNAPSHOT", snapshot, raising=False)
    monkeypatch.setattr(settings_module.settings, "SANDBOX_MAX_TTL", ttl, raising=False)
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", timeout, raising=False)
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_MAX_TIMEOUT", max_timeout, raising=False)


def _description(monkeypatch, backend: str = "jupyter", **kwargs) -> str:
    _configure(monkeypatch, backend, **kwargs)
    return _tool().get_actions_metadata()[0]["description"]


_SNAPSHOT = "docsgpt-sandbox-py312-v3"


def test_inputs_metadata_names_the_staging_path():
    props = _tool().get_actions_metadata()[0]["parameters"]["properties"]
    assert "inputs/<filename>" in props["inputs"]["description"]
    assert "inputs_loaded" in props["inputs"]["description"]


@pytest.mark.parametrize("backend, snapshot", [("jupyter", None), ("daytona", _SNAPSHOT), ("daytona", None)])
def test_description_stays_short(monkeypatch, backend, snapshot):
    """About 250 words: the long lists moved to the new-session environment summary."""
    words = len(_description(monkeypatch, backend, snapshot=snapshot).split())
    assert words <= 300, words


def test_description_is_the_same_for_every_call_and_conversation(monkeypatch):
    """No per-call content, so a provider can cache the tool schema."""
    _configure(monkeypatch)
    first = CodeExecutorTool({"conversation_id": "c1"}, user_id="u1").get_actions_metadata()
    second = CodeExecutorTool({"conversation_id": "c2", "workflow_run_id": "r"}, user_id="u2").get_actions_metadata()
    assert first == second


def test_description_renders_the_manifest_and_settings(monkeypatch):
    from docsgpt.sandbox import manifest

    desc = _description(monkeypatch, ttl=900, timeout=45, max_timeout=600)
    assert manifest.description_note() in desc
    assert f"Python {manifest.PYTHON_SERIES}" in desc
    assert "15 min idle" in desc
    assert "45s per call by default" in desc
    assert "pass `timeout` up to 600s for long jobs" in desc
    assert "prefer splitting work" in desc
    assert "`environment`" in desc


def test_description_states_the_workspace_contract(monkeypatch):
    for backend, snapshot in (("jupyter", None), ("daytona", _SNAPSHOT)):
        desc = _description(monkeypatch, backend, snapshot=snapshot)
        for text in (
            "`session: new`",
            "scratch/",
            "/tmp",
            "new version",
            "final name",
            "plt.show()",
            "savefig()",
            "never write links or sandbox paths",
            "`inputs/<name>`",
            "`A1`",
            "`F3`",
            "can't be downloaded from inside the sandbox",
            "pass `timeout` up to",
            "Network:",
            "artifact_generator",
            "don't apt-get",
        ):
            assert text in desc, (backend, text)
        # Showing a saved chart no longer saves it twice, so both are allowed.
        assert "never both" not in desc.lower()


def test_jupyter_description_says_variables_carry_over(monkeypatch):
    desc = _description(monkeypatch, "jupyter")
    assert "variables, imports, files and installed packages persist" in desc
    assert "fresh interpreter" not in desc
    assert "never pip-install a listed one" in desc


def test_daytona_description_says_each_call_is_a_fresh_interpreter(monkeypatch):
    desc = _description(monkeypatch, "daytona", snapshot=_SNAPSHOT)
    assert "files and installed packages persist" in desc
    assert "fresh interpreter" in desc and "re-import" in desc
    # An operator's older snapshot can lack a newer package.
    assert "only if its import fails" in desc


def test_bare_daytona_description_advertises_nothing_it_lacks(monkeypatch):
    desc = _description(monkeypatch, "daytona", snapshot=None)
    assert "Only the Python stdlib is preinstalled" in desc
    for absent in ("office-convert", "tesseract", "pdfplumber", "never pip-install", "Python 3.12"):
        assert absent not in desc


def test_description_no_longer_asks_for_persist_to_keep_state(monkeypatch):
    meta = _tool().get_actions_metadata()[0]
    assert "persist=true" not in meta["description"]
    persist = meta["parameters"]["properties"]["persist"]["description"]
    assert "default" in persist.lower() and "false" in persist.lower()


def test_outputs_parameter_mentions_scratch():
    outputs = _tool().get_actions_metadata()[0]["parameters"]["properties"]["outputs"]["description"]
    assert "scratch/" in outputs


def test_daytona_snapshot_bakes_the_spreadsheet_libraries():
    """Spreadsheets reach the sandbox by ref; both images must be able to open and chart them."""
    from docsgpt.sandbox import manifest

    names = {manifest.dist_name(spec) for spec in manifest.pip_specs()}
    assert {"pandas", "openpyxl", "matplotlib", "python-pptx", "python-docx", "reportlab"} <= names


# ---------------------------------------------------------------------------
# Environment summary on a new session
# ---------------------------------------------------------------------------
def test_a_new_session_result_carries_the_environment_summary(monkeypatch):
    from docsgpt.sandbox import manifest

    _configure(monkeypatch, ttl=1200, timeout=60)
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"), created=True)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert payload["environment"] == manifest.environment_summary(timeout=60, idle_minutes=20, max_timeout=1000)
    # It comes right after the session marker, before the output.
    assert list(payload)[:3] == ["status", "session", "environment"]


def test_a_reused_session_result_has_no_environment_summary(monkeypatch):
    _configure(monkeypatch)
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"), created=False)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)
    assert "environment" not in payload


def test_a_bare_daytona_session_summary_says_stdlib_only(monkeypatch):
    _configure(monkeypatch, "daytona", snapshot=None)
    manager = _FakeManager(ExecResult(status="ok", stdout="ok"), created=True)
    env = _run_with_fake_manager(monkeypatch, manager, code="print(1)", capture_artifacts=False)["environment"]
    assert "only the stdlib" in env and "office-convert" not in env


# ---------------------------------------------------------------------------
# Hints and output hygiene in the result
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_failures(monkeypatch):
    from docsgpt.agents.tools import code_executor as ce
    from docsgpt.agents.tools.code_executor_hints import FailureMemory

    memory = FailureMemory()
    monkeypatch.setattr(ce, "_FAILURES", memory)
    return memory


def test_result_carries_fix_hints(monkeypatch, fresh_failures):
    _configure(monkeypatch)
    manager = _FakeManager(ExecResult(status="error", error_name="ModuleNotFoundError",
                                      error_value="No module named 'fitz'"), created=False)
    payload = _run_with_fake_manager(monkeypatch, manager, code="import fitz", capture_artifacts=False)
    assert any("fitz (PyMuPDF) is not installed" in h for h in payload["hint"])


def test_result_without_a_recognized_mistake_has_no_hint_key(monkeypatch, fresh_failures):
    _configure(monkeypatch)
    manager = _FakeManager(ExecResult(status="ok", stdout="42\n"), created=False)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(42)", capture_artifacts=False)
    assert "hint" not in payload


def test_the_same_failure_twice_in_a_conversation_says_change_approach(monkeypatch, fresh_failures):
    from docsgpt.agents.tools.code_executor_hints import REPEATED_FAILURE_HINT

    _configure(monkeypatch)
    failing = ExecResult(status="error", error_name="KeyError", error_value="'total'")
    # Each request builds a new tool instance; the memory spans them.
    first = _run_with_fake_manager(monkeypatch, _FakeManager(failing, created=False), code="df['total']")
    second = _run_with_fake_manager(monkeypatch, _FakeManager(failing, created=False), code="df['total']")
    assert REPEATED_FAILURE_HINT not in first.get("hint", [])
    assert second["hint"][0] == REPEATED_FAILURE_HINT


def test_a_success_between_failures_resets_the_repeat_guard(monkeypatch, fresh_failures):
    from docsgpt.agents.tools.code_executor_hints import REPEATED_FAILURE_HINT

    _configure(monkeypatch)
    failing = ExecResult(status="error", error_name="KeyError", error_value="'total'")
    _run_with_fake_manager(monkeypatch, _FakeManager(failing, created=False), code="x")
    _run_with_fake_manager(monkeypatch, _FakeManager(ExecResult(status="ok", stdout="1"), created=False), code="y")
    third = _run_with_fake_manager(monkeypatch, _FakeManager(failing, created=False), code="x")
    assert REPEATED_FAILURE_HINT not in third.get("hint", [])


def test_timeout_keeps_the_guidance_and_adds_the_lost_work_hint(monkeypatch, fresh_failures):
    _configure(monkeypatch)
    timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60.0s")
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(timed_out, created=False), code="train()")
    assert "background" in payload["error"] and "60s" in payload["error"]
    assert any("interrupted" in h and "scratch/" in h for h in payload["hint"])
    assert any("`timeout`" in h for h in payload["hint"])


def test_output_tails_drop_colour_codes_and_pip_noise(monkeypatch, fresh_failures):
    _configure(monkeypatch)
    stdout = "Requirement already satisfied: pandas in /usr/lib (2.2.3)\n\x1b[32mdone\x1b[0m\n"
    stderr = "\x1b[33mWARNING: Running pip as the 'root' user can result in broken permissions\x1b[0m\n"
    result = ExecResult(status="ok", stdout=stdout, stderr=stderr)
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(result, created=False), code="print('done')")
    assert payload["stdout_tail"] == "done\n"
    assert "stderr_tail" not in payload


def test_daytona_error_names_the_exception_instead_of_repeating_stdout(monkeypatch, fresh_failures):
    _configure(monkeypatch, "daytona", snapshot=_SNAPSHOT)
    stdout = "x" * 20000 + "\nTraceback (most recent call last):\nKeyError: 'total'\n"
    result = ExecResult(status="error", stdout=stdout, error_name="ExecutionError", error_value=stdout, exit_code=1)
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(result, created=False), code="df['total']")
    assert payload["error"] == "KeyError: 'total'"
    assert payload["stdout_tail"].endswith("KeyError: 'total'\n")


def test_daytona_error_without_a_traceback_reports_the_exit_code(monkeypatch, fresh_failures):
    _configure(monkeypatch, "daytona", snapshot=_SNAPSHOT)
    result = ExecResult(status="error", stdout="", error_name="ExecutionError",
                        error_value="exited with code 2", exit_code=2)
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(result, created=False), code="import sys; sys.exit(2)")
    assert payload["error"] == "ExecutionError: exited with code 2"


def test_a_long_error_message_is_bounded():
    tool = _tool()
    result = ExecResult(status="error", error_name="ValueError", error_value="v" * 50000)
    assert len(tool._shape_payload(result, [], [])["error"]) <= 1100


def test_is_timeout_ignores_a_process_that_failed_on_its_own():
    """A Daytona traceback through urllib3 mentions timeouts; only the sandbox's own cap is a timeout."""
    noisy = ExecResult(status="error", error_name="ExecutionError",
                       error_value="ConnectionError: ... (timeout=10) ... timed out")
    assert not CodeExecutorTool._is_timeout(noisy)
    assert not CodeExecutorTool._is_timeout(ExecResult(error_name="ReadTimeout", error_value="read timed out"))
    assert CodeExecutorTool._is_timeout(ExecResult(error_name="DaytonaProcessExecutionTimeoutError"))


def test_app_hosts_come_from_the_deployment_urls(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "API_URL", "https://api.example.com", raising=False)
    monkeypatch.setattr(settings_module.settings, "PUBLIC_API_BASE_URL", "http://localhost:7091", raising=False)
    monkeypatch.setattr(settings_module.settings, "OIDC_FRONTEND_URL", "https://app.example.com/", raising=False)
    monkeypatch.setattr(settings_module.settings, "CONNECTOR_REDIRECT_BASE_URI", None, raising=False)
    # A loopback host counts only with its port: code may run its own server on localhost.
    assert CodeExecutorTool._app_hosts() == ("api.example.com", "localhost:7091", "app.example.com")


def test_a_failing_hint_builder_never_breaks_the_result(monkeypatch, fresh_failures):
    from docsgpt.agents.tools import code_executor as ce

    def _boom(facts):
        raise RuntimeError("bug")

    _configure(monkeypatch)
    monkeypatch.setattr(ce, "fix_hints", _boom)
    payload = _run_with_fake_manager(monkeypatch, _FakeManager(ExecResult(status="ok", stdout=""), created=False),
                                     code="x = 1")
    assert payload["status"] == "ok" and "hint" not in payload


def test_an_error_without_a_name_keeps_its_cleaned_message():
    tool = _tool()
    assert tool._shape_payload(ExecResult(status="error", error_value="\x1b[31mboom\x1b[0m"), [], [])["error"] == "boom"
    assert tool._shape_payload(ExecResult(status="error"), [], [])["error"] == "execution error"


def test_app_hosts_skip_unparseable_and_hostless_urls(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "API_URL", "http://[::1", raising=False)
    monkeypatch.setattr(settings_module.settings, "PUBLIC_API_BASE_URL", "not a url", raising=False)
    monkeypatch.setattr(settings_module.settings, "OIDC_FRONTEND_URL", "http://localhost/", raising=False)
    monkeypatch.setattr(settings_module.settings, "CONNECTOR_REDIRECT_BASE_URI", None, raising=False)
    assert CodeExecutorTool._app_hosts() == ()


def test_a_new_session_gets_a_scratch_directory(monkeypatch):
    """Commands such as pdftoppm do not create directories; scratch/ must exist before the code runs."""
    _configure(monkeypatch)
    fresh = _FakeManager(ExecResult(status="ok", stdout="ok"), created=True)
    _run_with_fake_manager(monkeypatch, fresh, code="print(1)", capture_artifacts=False)
    assert fresh.put_files == ["scratch/.keep"]
    reused = _FakeManager(ExecResult(status="ok", stdout="ok"), created=False)
    _run_with_fake_manager(monkeypatch, reused, code="print(1)", capture_artifacts=False)
    assert reused.put_files == []


def test_a_failed_scratch_setup_does_not_stop_the_run(monkeypatch):
    class _PutFails(_FakeManager):
        def put_file(self, session_id, dest_path, data):
            raise IOError("down")

    _configure(monkeypatch)
    payload = _run_with_fake_manager(monkeypatch, _PutFails(ExecResult(status="ok", stdout="ok"), created=True),
                                     code="print(1)", capture_artifacts=False)
    assert payload["status"] == "ok"


# ---------------------------------------------------------------------------
# A reused session whose sandbox is gone
# ---------------------------------------------------------------------------
class _GoneOnReuseManager(_FakeManager):
    """A reused session whose sandbox another process deleted: ``fail_on`` finds it gone.

    The manager drops the dead session on ``SandboxGoneError``, so the next open is fresh.
    """

    def __init__(self, fail_on: str, *, still_gone: bool = False) -> None:
        super().__init__(ExecResult(status="ok", stdout="ok"), created=False)
        self.fail_on = fail_on
        self.still_gone = still_gone
        self.dropped = False
        self.exec_calls = 0
        self.staged: list = []

    def open_session(self, session_id, ttl=None):
        self.opened.append((session_id, ttl))
        return OpenedSession(session_id, self.dropped)

    def _maybe_gone(self, op: str) -> None:
        from docsgpt.sandbox.base import SandboxGoneError

        if op == self.fail_on and (not self.dropped or self.still_gone):
            self.dropped = True
            raise SandboxGoneError(f"{op} failed: sandbox gone (NotFound)")

    def put_file(self, session_id, dest_path, data):
        if dest_path.startswith("inputs/"):
            self._maybe_gone("put_file")
        self.staged.append((dest_path, self.dropped))
        super().put_file(session_id, dest_path, data)

    def list_files(self, session_id):
        self._maybe_gone("list_files")
        return super().list_files(session_id)

    def exec(self, session_id, code, timeout=None):
        self.exec_calls += 1
        return super().exec(session_id, code, timeout)


def test_a_gone_reused_session_is_retried_once_on_a_fresh_one_with_inputs_restaged(monkeypatch):
    _patch_input_repo(monkeypatch, found_position=True, conv="conv-1")
    manager = _GoneOnReuseManager("put_file")
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)", inputs=["A1"], capture_artifacts=False)
    assert payload["status"] == "ok"
    assert payload["session"] == "new"  # earlier files and installs are gone, and the model is told
    assert payload["inputs_loaded"] == ["inputs/seed.csv"]
    assert ("inputs/seed.csv", True) in manager.staged
    assert len(manager.opened) == 2
    assert manager.exec_calls == 1


def test_a_gone_session_found_by_the_pre_run_listing_is_retried(monkeypatch):
    manager = _GoneOnReuseManager("list_files")
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)")
    assert payload["status"] == "ok" and payload["session"] == "new"
    assert manager.exec_calls == 1


def test_a_session_gone_again_after_the_retry_is_reported_not_looped(monkeypatch):
    manager = _GoneOnReuseManager("list_files", still_gone=True)
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)")
    assert payload["status"] == "error"
    assert "sandbox" in payload["error"].lower()
    assert payload["session"] == "new"
    assert len(manager.opened) == 2
    assert manager.exec_calls == 0


def test_a_new_session_that_is_gone_is_not_retried(monkeypatch):
    manager = _GoneOnReuseManager("list_files")
    manager.open_session = lambda session_id, ttl=None: (manager.opened.append((session_id, ttl)),
                                                         OpenedSession(session_id, True))[1]
    payload = _run_with_fake_manager(monkeypatch, manager, code="print(1)")
    assert payload["status"] == "error" and payload["session"] == "new"
    assert len(manager.opened) == 1
