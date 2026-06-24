"""Unit tests for DocumentExtractorTool: staging, fixed-program shaping, schema validation, and injection safety.

Docling and the sandbox exec are MOCKED so no heavy import (torch/models) or real
kernel is touched. These cover: a parent-scoped input is staged and extracted into
a compact payload; json_schema validation (pass + fail); a cross-tenant input id is
denied; and the extraction program is FIXED with params travelling as data so a
malicious filename/parameter is never executed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import os
import sys
import tempfile
import types

import application.agents.tools.document_extractor as de
from application.agents.tools.document_extractor import (
    _EXTRACT_PROGRAM,
    _MARKDOWN_MAX_BYTES,
    _MAX_CELL_CHARS,
    _MAX_TABLE_ROWS,
    DocumentExtractorTool,
)
from application.sandbox.base import ExecResult

# A canned Docling-style extraction result the mocked program "writes" to result.json.
_CANNED_EXTRACT = {
    "ok": True,
    "markdown": "# Statement\n\nBalance: 1000",
    "markdown_truncated": False,
    "tables": [{"columns": ["item", "amount"], "rows": [["fee", "10"]]}],
    "page_count": 2,
    "structured": {
        "schema_name": "DoclingDocument",
        "texts": [{"text": "Balance: 1000"}],
        "tables": [{"data": "..."}],
        "pages": {"1": {}, "2": {}},
    },
}


class _FakeManager:
    """In-memory sandbox stand-in: records put_file calls and the exact exec program/code."""

    def __init__(self, result: ExecResult, result_file: bytes) -> None:
        self._result = result
        self._result_file = result_file
        self.put_files: Dict[str, bytes] = {}
        self.exec_programs: List[str] = []
        self.opened: List[Any] = []
        self.closed: List[str] = []
        self.removed: List[str] = []

    def open(self, session_id, ttl=None):
        self.opened.append((session_id, ttl))
        return session_id

    def remove_path(self, session_id, path):
        self.removed.append(path)

    def put_file(self, session_id, dest_path, data):
        self.put_files[dest_path] = data

    def exec(self, session_id, code, timeout=None):
        self.exec_programs.append(code)
        return self._result

    def get_file(self, session_id, path):
        return self._result_file

    def close(self, session_id):
        self.closed.append(session_id)


class _FakeVersion(dict):
    pass


def _stub_repo(monkeypatch, *, found: bool, conv: Optional[str], run: Optional[str]):
    """Patch db_readonly + ArtifactsRepository so input scoping is exercised without a DB."""

    class _Repo:
        def __init__(self, conn):
            pass

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            # Mirror the real scope gate: the artifact resolves only for the right parent.
            if not found:
                return None
            if conv is not None and conversation_id != conv:
                return None
            if run is not None and workflow_run_id != run:
                return None
            return {"id": artifact_id, "current_version": 1, "title": "statement.pdf"}

        def get_version(self, artifact_id, version):
            return _FakeVersion(
                {"filename": "statement.pdf", "storage_path": f"inputs/u/artifacts/{artifact_id}/v1/statement.pdf"}
            )

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(de, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(de, "ArtifactsRepository", _Repo)


class _FakeStorage:
    """Returns canned input bytes for any storage path."""

    def __init__(self, data: bytes = b"%PDF-1.4 fake") -> None:
        self._data = data

    def get_file(self, path):
        import io

        return io.BytesIO(self._data)


def _patch_storage(monkeypatch):
    monkeypatch.setattr(de.StorageCreator, "get_storage", staticmethod(lambda: _FakeStorage()))


def _patch_manager(monkeypatch, manager):
    monkeypatch.setattr(de.SandboxCreator, "get_manager", lambda: manager)


def _patch_no_persist(monkeypatch):
    # Default the persist path to a no-op so most tests don't touch the artifact store.
    monkeypatch.setattr(de, "persist_new_artifact", lambda **kwargs: None)


def _tool(**config) -> DocumentExtractorTool:
    base = {"conversation_id": "conv-1", "tool_id": "t-1"}
    base.update(config)
    return DocumentExtractorTool(tool_config=base, user_id="u-1")


def _manager_with_extract(extract: Dict[str, Any]) -> _FakeManager:
    return _FakeManager(ExecResult(status="ok"), json.dumps(extract).encode("utf-8"))


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------
def test_unknown_action_rejected():
    out = _tool().execute_action("nope", input="a")
    assert out["status"] == "error" and "unknown action" in out["error"]


def test_requires_user_and_parent():
    no_user = DocumentExtractorTool({"conversation_id": "c"}, user_id=None)
    out = no_user.execute_action("extract_document", input="a")
    assert out["status"] == "error" and "user_id" in out["error"]

    no_parent = DocumentExtractorTool({}, user_id="u")
    out2 = no_parent.execute_action("extract_document", input="a")
    assert out2["status"] == "error" and "conversation_id" in out2["error"]


def test_input_id_required():
    out = _tool().execute_action("extract_document", input="   ")
    assert out["status"] == "error" and "input artifact id is required" in out["error"]


def test_action_metadata_shape():
    meta = _tool().get_actions_metadata()[0]
    assert meta["name"] == "extract_document"
    assert meta["parameters"]["required"] == ["input"]
    assert "json_schema" in meta["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Happy path: staging + compact payload shaping
# ---------------------------------------------------------------------------
def test_extract_stages_input_and_shapes_compact_payload(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="art-1", persist=False)

    assert out["status"] == "ok"
    structured = out["structured"]
    # Compact payload: markdown + tables + page_count + a structure summary, no raw bytes.
    assert structured["markdown"].startswith("# Statement")
    assert structured["tables"] == _CANNED_EXTRACT["tables"]
    assert structured["page_count"] == 2
    assert structured["summary"] == {"texts": 1, "tables": 1, "pages": 2}
    assert "bytes" not in out

    # The input document was staged into the workspace as a DATA file (not code).
    staged = [p for p in manager.put_files if p.endswith("statement.pdf")]
    assert staged, "input document should be staged into the workspace"
    assert manager.put_files[staged[0]] == b"%PDF-1.4 fake"
    # The session is closed after a one-shot extraction.
    assert manager.closed == ["conv-1"]


def test_extract_removes_its_scratch_token_dir(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    _tool().execute_action("extract_document", input="art-1", persist=False)

    # The per-render token dir (extract/<token>) is removed before/at teardown so
    # a reused session doesn't accumulate staged inputs + results on disk.
    assert manager.removed, "extractor should remove its scratch token dir"
    removed_dir = manager.removed[0]
    assert removed_dir.startswith("extract/")
    # The dir prefix must cover the files that were staged under it.
    assert all(p.startswith(removed_dir + "/") for p in manager.put_files)


def test_extract_persists_data_artifact_by_reference(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    captured: Dict[str, Any] = {}

    def _fake_persist(**kwargs):
        captured.update(kwargs)
        return {"artifact_id": "new-art", "version": 1, "filename": "x.json",
                "mime_type": "application/json", "size": 10}

    monkeypatch.setattr(de, "persist_new_artifact", _fake_persist)

    tool = _tool()
    out = tool.execute_action("extract_document", input="art-1")  # persist defaults to true
    assert out["status"] == "ok"
    assert out["artifact"]["artifact_id"] == "new-art"
    assert tool.get_artifact_id("extract_document") == "new-art"
    # Persisted as a JSON data artifact carrying the full extraction (by reference).
    assert captured["kind"] == "data"
    assert captured["mime_type"] == "application/json"
    assert json.loads(captured["data"].decode("utf-8")) == _CANNED_EXTRACT


def test_quota_exceeded_on_persist_surfaces_cleanly(monkeypatch):
    from application.sandbox.artifacts_capture import QuotaExceeded

    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    def _quota_blocked(**kwargs):
        raise QuotaExceeded("artifact storage quota reached")

    monkeypatch.setattr(de, "persist_new_artifact", _quota_blocked)

    out = _tool().execute_action("extract_document", input="art-1")
    # Extraction still succeeds; the quota failure surfaces as a non-fatal note.
    assert out["status"] == "ok"
    assert "artifact" not in out
    assert "quota" in out["artifact_error"].lower()


# ---------------------------------------------------------------------------
# Cross-tenant scope
# ---------------------------------------------------------------------------
def test_cross_tenant_input_is_denied(monkeypatch):
    # Tool is bound to conv-1; the artifact only exists under conv-OTHER, so the
    # parent-scoped fetch returns None and the extraction is refused.
    _stub_repo(monkeypatch, found=True, conv="conv-OTHER", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "error"
    assert "not found in this conversation/run" in out["error"]
    # Nothing was staged or executed for a denied input.
    assert manager.exec_programs == []


def test_missing_input_artifact_is_denied(monkeypatch):
    _stub_repo(monkeypatch, found=False, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="ghost", persist=False)
    assert out["status"] == "error" and "not found" in out["error"]
    assert manager.exec_programs == []


# ---------------------------------------------------------------------------
# json_schema validation (pass + fail)
# ---------------------------------------------------------------------------
def _schema_requiring_texts() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {"texts": {"type": "array"}, "schema_name": {"type": "string"}},
        "required": ["texts", "schema_name"],
    }


def test_json_schema_validation_passes(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    _patch_manager(monkeypatch, _manager_with_extract(_CANNED_EXTRACT))

    out = _tool().execute_action(
        "extract_document", input="art-1", json_schema=_schema_requiring_texts(), persist=False
    )
    assert out["status"] == "ok"


def test_json_schema_validation_fails_with_clean_error(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    # structured payload lacks the required "amount" field the schema demands.
    schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}}}
    _patch_manager(monkeypatch, _manager_with_extract(_CANNED_EXTRACT))

    out = _tool().execute_action("extract_document", input="art-1", json_schema=schema, persist=False)
    assert out["status"] == "error"
    assert "did not match json_schema" in out["error"]


def test_malformed_json_schema_rejected_before_run(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    # No "type"/"schema" key -> normalize_json_schema_payload rejects it up front.
    out = _tool().execute_action("extract_document", input="art-1", json_schema={"properties": {}}, persist=False)
    assert out["status"] == "error" and "invalid json_schema" in out["error"]
    assert manager.exec_programs == []


# ---------------------------------------------------------------------------
# Docling-unavailable / extractor error surfacing
# ---------------------------------------------------------------------------
def test_docling_unavailable_surfaces_clean_error(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    # The program's own "docling not available" branch writes an {"error": ...} result.
    err_result = {
        "error": "docling is not available in the sandbox runner: ModuleNotFoundError: No module named 'docling'"
    }
    _patch_manager(monkeypatch, _manager_with_extract(err_result))

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "error"
    assert "docling is not available" in out["error"]


def test_exec_error_surfaces_clean_error(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _FakeManager(
        ExecResult(status="error", error_name="TimeoutError", error_value="exceeded 60s"), b""
    )
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "error"
    assert "TimeoutError: exceeded 60s" in out["error"]


# ---------------------------------------------------------------------------
# Injection safety: the extraction program is FIXED; params travel as data
# ---------------------------------------------------------------------------
def test_extraction_program_is_fixed_and_params_are_data(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    _tool().execute_action("extract_document", input="art-1", persist=False)

    program = manager.exec_programs[0]
    # The executed program is the fixed template with only server-controlled path
    # literals substituted — no input id, filename, or document content appears.
    assert "json.load(open(" in program
    assert "DocumentConverter" in program
    assert "art-1" not in program
    assert "statement.pdf" not in program
    # Params reached the program as a JSON DATA file, not via interpolation.
    params_files = [p for p in manager.put_files if p.endswith("params.json")]
    assert params_files
    params = json.loads(manager.put_files[params_files[0]].decode("utf-8"))
    assert params["input_path"].endswith("statement.pdf")


def test_malicious_param_value_is_not_executed(monkeypatch):
    """A hostile filename ends up only in a DATA file the program json.loads, never in the program text."""
    # The artifact's stored filename is attacker-controlled in the worst case;
    # prove a code-shaped filename never lands in the executed program.
    payload = "__import__('os').system('echo PWNED'); x = 'a.pdf"

    class _Repo:
        def __init__(self, conn):
            pass

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            return {"id": artifact_id, "current_version": 1, "title": payload}

        def get_version(self, artifact_id, version):
            return {"filename": payload, "storage_path": "inputs/u/artifacts/x/v1/f"}

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(de, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(de, "ArtifactsRepository", _Repo)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "ok"

    program = manager.exec_programs[0]
    # The injection payload is absent from the program; it (sanitized) only rides
    # in the params DATA file, so it is parsed as a string, never executed.
    assert "PWNED" not in program
    assert "__import__" not in program
    params_files = [p for p in manager.put_files if p.endswith("params.json")]
    params = json.loads(manager.put_files[params_files[0]].decode("utf-8"))
    # The path is sanitized but even unsanitized it is pure data inside params.json.
    assert "input_path" in params


# ---------------------------------------------------------------------------
# The fixed program template itself
# ---------------------------------------------------------------------------
def test_program_template_has_no_unbound_interpolation_points():
    # Only the two server-controlled path placeholders may be formatted in; the
    # template must format cleanly with just those, proving nothing else is a hole.
    rendered = _EXTRACT_PROGRAM.format(params_path="extract/x/params.json", result_path="extract/x/result.json")
    assert "params.json" in rendered
    assert "result.json" in rendered
    # Compiles as valid Python (no broken escapes from the doubled braces).
    compile(rendered, "<extractor>", "exec")


# ---------------------------------------------------------------------------
# Markdown head+tail window (finding: the END of compliance docs must survive)
# ---------------------------------------------------------------------------
def _run_program_with_fake_docling(monkeypatch, markdown: str, md_cap: int) -> Dict[str, Any]:
    """Exec the REAL extraction program with docling stubbed so we test the markdown windowing."""

    class _FakeDoc:
        tables: List[Any] = []
        pages: Dict[str, Any] = {}

        def export_to_markdown(self):
            return markdown

        def export_to_dict(self):
            return {"texts": []}

    class _FakeConverter:
        def convert(self, src):
            return types.SimpleNamespace(document=_FakeDoc())

    fake_mod = types.ModuleType("docling")
    fake_sub = types.ModuleType("docling.document_converter")
    fake_sub.DocumentConverter = _FakeConverter
    fake_mod.document_converter = fake_sub
    monkeypatch.setitem(sys.modules, "docling", fake_mod)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_sub)

    workdir = tempfile.mkdtemp()
    params_path = os.path.join(workdir, "params.json")
    result_path = os.path.join(workdir, "result.json")
    with open(params_path, "w") as fh:
        json.dump({"input_path": "x", "markdown_max_bytes": md_cap, "max_tables": 20}, fh)

    program = _EXTRACT_PROGRAM.format(params_path=params_path, result_path=result_path)
    ns: Dict[str, Any] = {}
    exec(compile(program, "<extractor>", "exec"), ns, ns)  # noqa: S102
    with open(result_path) as fh:
        return json.load(fh)


def test_markdown_window_keeps_head_and_tail_when_truncated(monkeypatch):
    head_marker = "HEAD_START_OF_DOC"
    tail_marker = "TAIL_END_OF_DOC_TOTALS"
    body = "x" * (_MARKDOWN_MAX_BYTES * 2)
    markdown = head_marker + body + tail_marker

    result = _run_program_with_fake_docling(monkeypatch, markdown, _MARKDOWN_MAX_BYTES)

    assert result["markdown_truncated"] is True
    out = result["markdown"]
    # Both the beginning AND the end of the document survive the byte budget.
    assert head_marker in out
    assert tail_marker in out
    assert "...[truncated" in out
    # The window respects the budget (plus the small truncation marker).
    assert len(out) <= _MARKDOWN_MAX_BYTES + 64


def test_markdown_full_content_when_under_cap(monkeypatch):
    markdown = "# Short doc\n\nBalance: 1000\n\nSignature: Jane"
    result = _run_program_with_fake_docling(monkeypatch, markdown, _MARKDOWN_MAX_BYTES)

    assert result["markdown_truncated"] is False
    assert result["markdown"] == markdown


# ---------------------------------------------------------------------------
# Per-table content cap (a single giant table must not bloat context)
# ---------------------------------------------------------------------------
def test_compact_payload_bounds_table_rows_and_cell_bytes(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_storage(monkeypatch)
    _patch_no_persist(monkeypatch)

    big_cell = "y" * (_MAX_CELL_CHARS * 3)
    huge_table = {
        "columns": ["a", "b"],
        "rows": [[str(i), big_cell] for i in range(_MAX_TABLE_ROWS * 4)],
    }
    extract = dict(_CANNED_EXTRACT)
    extract["tables"] = [huge_table]
    _patch_manager(monkeypatch, _manager_with_extract(extract))

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "ok"
    table = out["structured"]["tables"][0]
    # Rows are capped and flagged with the original total.
    assert len(table["rows"]) == _MAX_TABLE_ROWS
    assert table["rows_truncated"] is True
    assert table["total_rows"] == _MAX_TABLE_ROWS * 4
    # Long cell strings are truncated.
    assert len(table["rows"][0][1]) <= _MAX_CELL_CHARS + len("...[truncated]")
    assert table["rows"][0][1].endswith("...[truncated]")


# ---------------------------------------------------------------------------
# Input size cap (don't load an unbounded artifact into backend + kernel memory)
# ---------------------------------------------------------------------------
def test_oversized_input_is_rejected_before_exec(monkeypatch):
    _stub_repo(monkeypatch, found=True, conv="conv-1", run=None)
    _patch_no_persist(monkeypatch)
    monkeypatch.setattr(de.StorageCreator, "get_storage", staticmethod(lambda: _FakeStorage(b"P" * 4096)))
    monkeypatch.setattr(de.settings, "SANDBOX_MAX_INPUT_BYTES", 1024, raising=False)
    manager = _manager_with_extract(_CANNED_EXTRACT)
    _patch_manager(monkeypatch, manager)

    out = _tool().execute_action("extract_document", input="art-1", persist=False)
    assert out["status"] == "error"
    assert "too large" in out["error"]
    # Nothing was staged or executed for an oversized input.
    assert manager.exec_programs == []
    assert manager.opened == []
