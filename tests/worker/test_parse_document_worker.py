"""Unit tests for ``application.worker.parse_document_worker``.

The worker re-resolves the artifact through the run-scoped gate (independent of
the tool), reads its bytes, shapes the result, and persists when asked. The DB,
storage, parser, and persistence boundaries are mocked so no live worker / DB is
needed (call the underlying function directly).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

import application.worker as worker

_ART_ID = str(uuid.uuid4())


class _FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeStorage:
    def __init__(self, data: bytes = b"%PDF-1.4 fake") -> None:
        self._data = data

    def get_file(self, path):
        return _FakeFile(self._data)


def _patch_repo(monkeypatch, *, found: bool, run: Optional[str]):
    class _Repo:
        def __init__(self, conn):
            pass

        def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
            if not found or n != 1 or (run is not None and workflow_run_id != run):
                return None
            return _ART_ID

        def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
            if not found or (run is not None and workflow_run_id != run):
                return None
            return {"id": artifact_id, "current_version": 1, "title": "statement.pdf"}

        def get_version(self, artifact_id, version):
            return {"filename": "statement.pdf", "storage_path": f"inputs/u/artifacts/{artifact_id}/v1/x.pdf"}

    class _Conn:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(worker, "db_readonly", lambda: _Conn())
    monkeypatch.setattr(worker, "ArtifactsRepository", _Repo)
    monkeypatch.setattr(worker.StorageCreator, "get_storage", staticmethod(lambda: _FakeStorage()))


def _patch_parse(monkeypatch, result: Dict[str, Any]):
    import application.parser.document_reader as dr

    monkeypatch.setattr(dr, "parse_document_bytes", lambda data, filename, **opts: result)


@pytest.mark.unit
def test_requires_parent():
    out = worker.parse_document_worker(None, _ART_ID, {}, "u-1", {})
    assert out["status"] == "error" and "conversation_id or workflow_run_id" in out["error"]


@pytest.mark.unit
def test_happy_path_shapes_result(monkeypatch):
    _patch_repo(monkeypatch, found=True, run="run-1")
    _patch_parse(monkeypatch, {"output": "markdown", "content": "# Hi", "truncated": False})

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"output": "markdown", "persist": False}
    )
    assert out["status"] == "ok"
    assert out["content"] == "# Hi"
    assert out["output"] == "markdown"


@pytest.mark.unit
def test_cross_run_artifact_is_rejected(monkeypatch):
    # The artifact only resolves for run-OTHER; the worker is asked for run-1 -> denied.
    _patch_repo(monkeypatch, found=True, run="run-OTHER")
    _patch_parse(monkeypatch, {"output": "markdown", "content": "x", "truncated": False})

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"persist": False}
    )
    assert out["status"] == "error" and "not found in this conversation/run" in out["error"]


@pytest.mark.unit
def test_missing_artifact_is_rejected(monkeypatch):
    _patch_repo(monkeypatch, found=False, run="run-1")
    _patch_parse(monkeypatch, {"output": "markdown", "content": "x", "truncated": False})

    out = worker.parse_document_worker(
        None, "ghost", {"workflow_run_id": "run-1"}, "u-1", {"persist": False}
    )
    assert out["status"] == "error" and "not found in this conversation/run" in out["error"]


@pytest.mark.unit
def test_parse_error_is_surfaced(monkeypatch):
    _patch_repo(monkeypatch, found=True, run="run-1")
    _patch_parse(monkeypatch, {"error": "unsupported file type '.exe'."})

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"persist": False}
    )
    assert out["status"] == "error" and "unsupported file type" in out["error"]


@pytest.mark.unit
def test_persist_stores_full_result_and_returns_ref(monkeypatch):
    _patch_repo(monkeypatch, found=True, run="run-1")
    full = {"output": "structured", "content": "# Big", "structured": {"texts": [{}]}, "truncated": False}
    _patch_parse(monkeypatch, full)

    captured: Dict[str, Any] = {}

    def _fake_persist(**kwargs):
        captured.update(kwargs)
        return {"artifact_id": "new-art", "version": 1, "filename": "x.json",
                "mime_type": "application/json", "size": 10}

    import application.sandbox.artifacts_capture as ac

    monkeypatch.setattr(ac, "persist_new_artifact", _fake_persist)

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"output": "structured", "persist": True}
    )
    assert out["status"] == "ok"
    assert out["artifact"]["artifact_id"] == "new-art"
    # The FULL shaped result is persisted by reference (not just the bounded view).
    import json

    assert captured["kind"] == "data"
    assert json.loads(captured["data"].decode("utf-8")) == full
    assert captured["workflow_run_id"] == "run-1"


@pytest.mark.unit
def test_persist_quota_surfaces_as_artifact_error(monkeypatch):
    _patch_repo(monkeypatch, found=True, run="run-1")
    _patch_parse(monkeypatch, {"output": "markdown", "content": "x", "truncated": False})

    import application.sandbox.artifacts_capture as ac

    def _quota(**kwargs):
        raise ac.QuotaExceeded("artifact storage quota reached")

    monkeypatch.setattr(ac, "persist_new_artifact", _quota)

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"persist": True}
    )
    # Parse still succeeded; quota failure is a non-fatal note.
    assert out["status"] == "ok"
    assert "artifact" not in out
    assert "quota" in out["artifact_error"].lower()


@pytest.mark.unit
def test_result_payload_content_is_bounded(monkeypatch):
    _patch_repo(monkeypatch, found=True, run="run-1")
    huge = "Z" * 50000
    _patch_parse(monkeypatch, {"output": "markdown", "content": huge, "truncated": False})

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"persist": False}
    )
    # The bounded view ridden back to the (Redis) result backend is far smaller.
    assert len(out["content"]) < len(huge)
    assert "...[truncated" in out["content"]


@pytest.mark.unit
def test_result_payload_chunks_are_bounded(monkeypatch):
    import application.parser.document_reader as dr

    _patch_repo(monkeypatch, found=True, run="run-1")
    # Many oversized chunks: count is capped AND each chunk is windowed.
    huge_chunk = "Z" * 50000
    chunks = [huge_chunk for _ in range(dr._MAX_CHUNKS_RETURNED * 3)]
    _patch_parse(monkeypatch, {"output": "chunks", "chunks": chunks, "truncated": False})

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"persist": False}
    )
    assert len(out["chunks"]) == dr._MAX_CHUNKS_RETURNED
    assert out["chunks_truncated"] is True
    assert out["total_chunks"] == dr._MAX_CHUNKS_RETURNED * 3
    assert all("...[truncated" in c for c in out["chunks"])
    assert all(len(c) < len(huge_chunk) for c in out["chunks"])


def _capture_persist(monkeypatch):
    """Patch persist_new_artifact to record what would be stored; return the capture dict."""
    import application.sandbox.artifacts_capture as ac

    captured: Dict[str, Any] = {}

    def _fake_persist(**kwargs):
        captured.update(kwargs)
        return {"artifact_id": "new-art", "version": 1, "filename": "x.json",
                "mime_type": "application/json", "size": len(kwargs.get("data", b""))}

    monkeypatch.setattr(ac, "persist_new_artifact", _fake_persist)
    return captured


@pytest.mark.unit
def test_persist_keeps_full_content_while_view_is_bounded(monkeypatch):
    # A >8000-byte doc: the persisted artifact must keep the FULL text, while the returned
    # (Redis/LLM) view is head+tail windowed.
    import json

    _patch_repo(monkeypatch, found=True, run="run-1")
    big = "Z" * 12000
    _patch_parse(monkeypatch, {"output": "markdown", "content": big, "truncated": False})
    captured = _capture_persist(monkeypatch)

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1", {"output": "markdown", "persist": True}
    )

    persisted = json.loads(captured["data"].decode("utf-8"))
    assert persisted["content"] == big  # FULL parse persisted
    assert len(persisted["content"]) == 12000
    assert len(out["content"]) < len(big)  # bounded view
    assert "...[truncated" in out["content"]
    assert out["truncated"] is True


@pytest.mark.unit
def test_persist_full_but_view_respects_max_chars(monkeypatch):
    # max_chars bounds only the returned view; the persisted artifact stays full.
    import json

    _patch_repo(monkeypatch, found=True, run="run-1")
    big = "Z" * 5000
    _patch_parse(monkeypatch, {"output": "markdown", "content": big, "truncated": False})
    captured = _capture_persist(monkeypatch)

    out = worker.parse_document_worker(
        None, _ART_ID, {"workflow_run_id": "run-1"}, "u-1",
        {"output": "markdown", "persist": True, "max_chars": 100},
    )

    assert json.loads(captured["data"].decode("utf-8"))["content"] == big  # full persisted
    assert len(out["content"]) == 100  # view capped by max_chars
    assert out["truncated"] is True
