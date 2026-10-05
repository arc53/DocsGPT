"""Unit tests for CodeExecutorTool: payload shaping, mime/kind inference, and allowlist wiring.

These tests exercise the pure logic (no sandbox, no DB, no storage) so they
run in the fast unit suite. The end-to-end persistence path is covered by
``tests/integration/test_code_executor_e2e.py`` against a live gateway + PG.
"""

from __future__ import annotations

import uuid

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


def test_exec_timeout_is_a_fixed_uncapped_value(monkeypatch):
    from docsgpt.core import settings as settings_module

    # The per-run wall-clock cap is fixed from settings; callers cannot pass one.
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", 60, raising=False)
    assert CodeExecutorTool._exec_timeout() == 60.0
    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", 90, raising=False)
    assert CodeExecutorTool._exec_timeout() == 90.0
    # The action schema no longer advertises language/libraries/timeout.
    props = _tool().get_actions_metadata()[0]["parameters"]["properties"]
    assert "timeout" not in props and "language" not in props and "libraries" not in props


def test_is_timeout_detects_any_backend_naming():
    assert CodeExecutorTool._is_timeout(ExecResult(error_name="TimeoutError", error_value="x"))
    assert CodeExecutorTool._is_timeout(ExecResult(error_name="DaytonaTimeoutError"))
    assert CodeExecutorTool._is_timeout(ExecResult(error_value="process timed out"))
    assert not CodeExecutorTool._is_timeout(ExecResult(error_name="ValueError", error_value="boom"))


def test_timeout_result_guides_backgrounding(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_EXEC_TIMEOUT", 60, raising=False)
    tool = _tool()
    timed_out = ExecResult(status="error", error_name="TimeoutError", error_value="execution exceeded 60s")
    err = tool._shape_payload(timed_out, [], [])["error"]
    assert "60s" in err and "background" in err.lower() and "poll" in err.lower()
    # The session is kept by default now; asking for persist=true is no longer needed.
    assert "persist=true" not in err.lower()
    assert "persist=false" in err
    # A non-timeout failure keeps the raw name/value.
    crashed = ExecResult(status="error", error_name="ValueError", error_value="boom")
    assert tool._shape_payload(crashed, [], [])["error"] == "ValueError: boom"


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
# Metadata: workspace contract and preinstalled packages
# ---------------------------------------------------------------------------


def test_inputs_metadata_names_the_staging_path():
    props = _tool().get_actions_metadata()[0]["parameters"]["properties"]
    assert "inputs/<filename>" in props["inputs"]["description"]
    assert "inputs_loaded" in props["inputs"]["description"]


def test_description_lists_jupyter_preinstalled_packages(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", "jupyter", raising=False)
    desc = _tool().get_actions_metadata()[0]["description"]
    for pkg in ("pandas", "matplotlib", "python-docx"):
        assert pkg in desc


def test_description_renders_the_sandbox_manifest(monkeypatch):
    """The package, command and font lists come from the manifest both images are built from."""
    from docsgpt.core import settings as settings_module
    from docsgpt.sandbox import manifest

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", "jupyter", raising=False)
    desc = _tool().get_actions_metadata()[0]["description"]
    assert manifest.preinstalled_summary() in desc
    for text in (
        "python-docx (import docx)",
        "beautifulsoup4 (import bs4)",
        "pdfplumber",
        "office-convert FILE --to pdf",
        "html-to-pdf",
        "tesseract",
        "ffmpeg",
        "node",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        assert text in desc, text
    assert "pip install anything else" in desc


def test_environment_note_lists_every_manifest_package(monkeypatch):
    from docsgpt.agents.tools.code_executor import CodeExecutorTool
    from docsgpt.core import settings as settings_module
    from docsgpt.sandbox import manifest

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", "jupyter", raising=False)
    note = CodeExecutorTool._environment_note()
    for pkg in manifest.PIP_PACKAGES:
        assert manifest.dist_name(pkg["spec"]) in note
    for binary in manifest.BINARIES:
        assert binary["name"] in note
    for font in manifest.FONTS:
        assert font["path"] in note


def test_description_warns_bare_daytona_image(monkeypatch):
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", "daytona", raising=False)
    monkeypatch.setattr(settings_module.settings, "DAYTONA_SNAPSHOT", None, raising=False)
    desc = _tool().get_actions_metadata()[0]["description"]
    assert "Only the Python stdlib is preinstalled" in desc
    # Without a snapshot none of the image's tools exist; do not advertise them.
    for absent in ("office-convert", "tesseract", "DejaVuSans.ttf", "pdfplumber"):
        assert absent not in desc


def test_description_lists_daytona_snapshot_packages(monkeypatch):
    from docsgpt.core import settings as settings_module
    from docsgpt.sandbox import manifest

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", "daytona", raising=False)
    monkeypatch.setattr(
        settings_module.settings, "DAYTONA_SNAPSHOT", "docsgpt-sandbox-py312-v2", raising=False
    )
    desc = _tool().get_actions_metadata()[0]["description"]
    for pkg in ("python-pptx", "pandas", "openpyxl", "matplotlib"):
        assert pkg in desc
    assert manifest.preinstalled_summary() in desc
    # A snapshot built by an older script lacks some of this: the model is told to pip install on import failure.
    assert "If an import fails" in desc
    assert "pip install" in desc


def test_daytona_snapshot_bakes_the_spreadsheet_libraries():
    """Spreadsheets reach the sandbox by ref; both images must be able to open and chart them."""
    from docsgpt.sandbox import manifest

    names = {manifest.dist_name(spec) for spec in manifest.pip_specs()}
    assert {"pandas", "openpyxl", "matplotlib", "python-pptx", "python-docx", "reportlab"} <= names


# ---------------------------------------------------------------------------
# Description: what persists between calls, per backend
# ---------------------------------------------------------------------------
def _description(monkeypatch, backend: str) -> str:
    from docsgpt.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "SANDBOX_BACKEND", backend, raising=False)
    return _tool().get_actions_metadata()[0]["description"]


def test_description_no_longer_asks_for_persist_to_keep_state(monkeypatch):
    meta = _tool().get_actions_metadata()[0]
    assert "persist=true" not in meta["description"]
    persist = meta["parameters"]["properties"]["persist"]["description"]
    assert "default" in persist.lower() and "false" in persist.lower()


def test_jupyter_description_says_variables_carry_over(monkeypatch):
    desc = _description(monkeypatch, "jupyter")
    assert "variables" in desc and "carry over" in desc
    assert "fresh Python interpreter" not in desc


def test_daytona_description_says_variables_do_not_carry_over(monkeypatch):
    desc = _description(monkeypatch, "daytona")
    assert "fresh Python interpreter" in desc
    assert "re-import" in desc.lower() and "through files" in desc


def test_description_explains_the_session_field_and_paths(monkeypatch):
    for backend in ("jupyter", "daytona"):
        desc = _description(monkeypatch, backend)
        assert "`session`" in desc and "`new`" in desc
        assert "scratch/" in desc and "/tmp" in desc
        assert "new version" in desc
        assert "savefig" in desc
    outputs = _tool().get_actions_metadata()[0]["parameters"]["properties"]["outputs"]["description"]
    assert "scratch/" in outputs
