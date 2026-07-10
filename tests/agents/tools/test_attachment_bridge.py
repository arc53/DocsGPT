"""Unit tests for the lazy chat-attachment -> conversation-artifact bridge.

Covers the matcher (caller-only, by id and filename), the idempotent bridge
(reuse an already-bridged attachment), the quota-error surface, and the wiring
into ``code_executor._materialize_inputs`` / ``read_document._resolve_input``.
No live DB / storage / sandbox / LLM is touched: the repos, storage, and
``persist_new_artifact`` are stubbed.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any, Dict, List, Optional

import pytest

import application.agents.tools.attachment_bridge as bridge_mod
from application.agents.tools.attachment_bridge import (
    AttachmentBridgeError,
    bridge_attachment,
    match_attachment,
)
from application.sandbox.artifacts_capture import QuotaExceeded

CONV = "11111111-1111-1111-1111-111111111111"
USER = "user-1"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, size: int = -1) -> bytes:
        # Mirror BinaryIO.read(n): the bridge does a bounded read to cap memory.
        return self._data if size is None or size < 0 else self._data[:size]

    def close(self) -> None:
        pass


class _FakeStorage:
    def __init__(self, data: bytes = b"hello bytes") -> None:
        self._data = data
        self.requested: List[str] = []

    def get_file(self, path):
        self.requested.append(path)
        return _FakeFile(self._data)


class _FakeAttachmentsRepo:
    """Confirms ownership: returns the row only for the owner user_id."""

    rows: Dict[str, Dict[str, Any]] = {}

    def __init__(self, conn=None) -> None:
        pass

    def get_any(self, attachment_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(str(attachment_id))
        if row is None or row.get("user_id") != user_id:
            return None
        return row


class _FakeArtifactsRepo:
    """Idempotency gate + parent-scoped artifact lookups for the bridge + tools."""

    bridged: Dict[str, str] = {}  # attachment_id -> existing artifact id
    artifacts: Dict[str, Dict[str, Any]] = {}  # artifact_id -> {conversation_id, current_version, versions}

    def __init__(self, conn=None) -> None:
        pass

    def find_bridged_attachment(self, attachment_id: str, *, conversation_id: str):
        aid = self.bridged.get(str(attachment_id))
        if aid is None:
            return None
        return {"id": aid}

    def artifact_id_at_position(self, n, *, conversation_id=None, workflow_run_id=None):
        return None

    def get_artifact_in_parent(self, artifact_id, *, conversation_id=None, workflow_run_id=None):
        art = self.artifacts.get(str(artifact_id))
        if art is None or art.get("conversation_id") != conversation_id:
            return None
        return {"id": artifact_id, "current_version": art["current_version"]}

    def get_version(self, artifact_id, version):
        art = self.artifacts.get(str(artifact_id))
        return art["versions"].get(version) if art is not None else None


@contextlib.contextmanager
def _fake_db():
    yield object()


def _attachment(*, aid=None, filename="report.pdf", user_id=USER, mime="application/pdf", path="up/report.pdf"):
    return {
        "id": aid or str(uuid.uuid4()),
        "filename": filename,
        "user_id": user_id,
        "mime_type": mime,
        "upload_path": path,
    }


def _patch_bridge(monkeypatch, *, storage=None, persisted_id="art-new"):
    """Patch the bridge module's repos/storage/persist so no infra is touched."""
    storage = storage or _FakeStorage()
    monkeypatch.setattr(bridge_mod, "db_readonly", _fake_db)
    monkeypatch.setattr(bridge_mod, "AttachmentsRepository", _FakeAttachmentsRepo)
    monkeypatch.setattr(bridge_mod, "ArtifactsRepository", _FakeArtifactsRepo)
    monkeypatch.setattr(
        bridge_mod.StorageCreator, "get_storage", staticmethod(lambda: storage)
    )
    calls: List[Dict[str, Any]] = []

    def _persist(**kwargs):
        calls.append(kwargs)
        return {"artifact_id": persisted_id, "version": 1, "filename": kwargs["filename"]}

    monkeypatch.setattr(bridge_mod, "persist_new_artifact", _persist)
    return storage, calls


@pytest.fixture(autouse=True)
def _reset_state():
    _FakeAttachmentsRepo.rows = {}
    _FakeArtifactsRepo.bridged = {}
    _FakeArtifactsRepo.artifacts = {}
    yield


# ---------------------------------------------------------------------------
# Matcher: caller-only, by id and by filename
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_match_by_id_confirms_owner(monkeypatch):
    _patch_bridge(monkeypatch)
    att = _attachment()
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    out = match_attachment([att], att["id"], USER)
    assert out is not None and out["id"] == att["id"]


@pytest.mark.unit
def test_match_by_filename_exact_and_normalized(monkeypatch):
    _patch_bridge(monkeypatch)
    att = _attachment(filename="Report.PDF")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    assert match_attachment([att], "report.pdf", USER) is not None
    assert match_attachment([att], "  Report.PDF ", USER) is not None


@pytest.mark.unit
def test_no_match_returns_none(monkeypatch):
    _patch_bridge(monkeypatch)
    att = _attachment(filename="a.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    assert match_attachment([att], "other.pdf", USER) is None
    assert match_attachment([], "a.pdf", USER) is None
    assert match_attachment(None, "a.pdf", USER) is None


@pytest.mark.unit
def test_match_rejects_when_owner_check_fails(monkeypatch):
    """An attachment dict present in the request but NOT owned by user is rejected at the owner re-check."""
    _patch_bridge(monkeypatch)
    att = _attachment(user_id="someone-else")
    # repo has no row for USER -> ownership re-check fails even though the dict was supplied.
    _FakeAttachmentsRepo.rows = {}
    assert match_attachment([att], att["id"], USER) is None


# ---------------------------------------------------------------------------
# Bridge: create + idempotent reuse + quota
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_bridge_creates_conversation_artifact(monkeypatch):
    storage, calls = _patch_bridge(monkeypatch, persisted_id="art-A")
    att = _attachment()
    art_id = bridge_attachment(att, user_id=USER, conversation_id=CONV)
    assert art_id == "art-A"
    assert len(calls) == 1
    kw = calls[0]
    assert kw["conversation_id"] == CONV and kw["user_id"] == USER and kw["kind"] == "file"
    assert kw["produced_by"] == {"attachment_id": att["id"], "source": "chat_attachment"}
    assert storage.requested == ["up/report.pdf"]


@pytest.mark.unit
def test_bridge_reuses_existing(monkeypatch):
    _storage, calls = _patch_bridge(monkeypatch)
    att = _attachment()
    _FakeArtifactsRepo.bridged = {att["id"]: "art-existing"}
    art_id = bridge_attachment(att, user_id=USER, conversation_id=CONV)
    assert art_id == "art-existing"
    assert calls == []  # no second persist -> no extra quota slot


@pytest.mark.unit
def test_bridge_surfaces_quota_as_clean_error(monkeypatch):
    _patch_bridge(monkeypatch)
    att = _attachment()

    def _persist(**kwargs):
        raise QuotaExceeded("artifact count quota reached (5)")

    monkeypatch.setattr(bridge_mod, "persist_new_artifact", _persist)
    with pytest.raises(AttachmentBridgeError, match="quota"):
        bridge_attachment(att, user_id=USER, conversation_id=CONV)


@pytest.mark.unit
def test_bridge_missing_upload_path_errors(monkeypatch):
    _patch_bridge(monkeypatch)
    att = _attachment(path=None)
    att["upload_path"] = None
    att["path"] = None
    with pytest.raises(AttachmentBridgeError, match="no stored content"):
        bridge_attachment(att, user_id=USER, conversation_id=CONV)


@pytest.mark.unit
def test_bridge_rejects_oversize_attachment_before_reading(monkeypatch):
    # An oversize attachment is rejected via its authoritative ``size`` column,
    # BEFORE the bytes are buffered into worker memory (a memory-DoS guard).
    from application.core.settings import settings

    _FakeArtifactsRepo.bridged = {}
    storage, calls = _patch_bridge(monkeypatch)
    att = _attachment()
    att["size"] = int(settings.ARTIFACT_MAX_BYTES) + 1
    with pytest.raises(AttachmentBridgeError, match="size limit"):
        bridge_attachment(att, user_id=USER, conversation_id=CONV)
    assert calls == []  # never persisted
    assert storage.requested == []  # never even read the bytes


# ---------------------------------------------------------------------------
# code_executor wiring: fallback fires, stages bytes, succeeds
# ---------------------------------------------------------------------------
def _patch_code_executor_repo(monkeypatch):
    import application.agents.tools.code_executor as ce

    monkeypatch.setattr(ce, "db_readonly", _fake_db)
    monkeypatch.setattr(ce, "ArtifactsRepository", _FakeArtifactsRepo)


class _Manager:
    def __init__(self):
        self.staged: Dict[str, bytes] = {}

    def put_file(self, session_id, path, data):
        self.staged[path] = data


@pytest.mark.unit
def test_code_executor_bridges_referenced_attachment_by_name(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    storage, calls = _patch_bridge(monkeypatch, storage=_FakeStorage(b"PDFDATA"), persisted_id="art-A")
    _patch_code_executor_repo(monkeypatch)
    att = _attachment(filename="statement.pdf", path="up/statement.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    # After the bridge creates art-A, the tool re-reads it parent-scoped.
    _FakeArtifactsRepo.artifacts = {
        "art-A": {
            "conversation_id": CONV,
            "current_version": 1,
            "versions": {1: {"storage_path": "store/art-A", "filename": "statement.pdf"}},
        }
    }
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": [att]}, user_id=USER
    )
    mgr = _Manager()
    out = tool._materialize_inputs(mgr, "sess", ["statement.pdf"])
    assert out.get("error") is None
    assert out["loaded"] == ["inputs/statement.pdf"]
    assert mgr.staged["inputs/statement.pdf"] == b"PDFDATA"
    assert len(calls) == 1  # bridged once


@pytest.mark.unit
def test_code_executor_bridges_referenced_attachment_by_id(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    _patch_bridge(monkeypatch, storage=_FakeStorage(b"X"), persisted_id="art-B")
    _patch_code_executor_repo(monkeypatch)
    att = _attachment(filename="data.csv", path="up/data.csv")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    _FakeArtifactsRepo.artifacts = {
        "art-B": {
            "conversation_id": CONV,
            "current_version": 1,
            "versions": {1: {"storage_path": "store/art-B", "filename": "data.csv"}},
        }
    }
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": [att]}, user_id=USER
    )
    mgr = _Manager()
    out = tool._materialize_inputs(mgr, "sess", [att["id"]])
    assert out["loaded"] == ["inputs/data.csv"]


@pytest.mark.unit
def test_code_executor_idempotent_reuse_no_second_persist(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    _storage, calls = _patch_bridge(monkeypatch, persisted_id="art-A")
    _patch_code_executor_repo(monkeypatch)
    att = _attachment(filename="doc.pdf", path="up/doc.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    # Pretend it was already bridged once -> reuse path.
    _FakeArtifactsRepo.bridged = {att["id"]: "art-A"}
    _FakeArtifactsRepo.artifacts = {
        "art-A": {
            "conversation_id": CONV,
            "current_version": 1,
            "versions": {1: {"storage_path": "store/art-A", "filename": "doc.pdf"}},
        }
    }
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": [att]}, user_id=USER
    )
    mgr = _Manager()
    # Reference the same attachment twice in one call.
    out = tool._materialize_inputs(mgr, "sess", ["doc.pdf", att["id"]])
    assert out.get("error") is None
    assert calls == []  # never persisted -> reused the existing artifact both times


@pytest.mark.unit
def test_code_executor_rejects_foreign_attachment(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    _patch_bridge(monkeypatch)
    _patch_code_executor_repo(monkeypatch)
    foreign = _attachment(filename="secret.pdf", user_id="attacker")
    # The model names another user's file, but it is not in THIS request's attachments
    # and ownership re-check has no row for USER.
    _FakeAttachmentsRepo.rows = {}
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": []}, user_id=USER
    )
    out = tool._materialize_inputs(_Manager(), "sess", [foreign["id"]])
    assert "not found in this conversation/run" in out["error"]


@pytest.mark.unit
def test_code_executor_workflow_scope_does_not_bridge(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    _storage, calls = _patch_bridge(monkeypatch)
    _patch_code_executor_repo(monkeypatch)
    att = _attachment(filename="wf.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}
    # workflow_run_id set, no conversation_id -> attachment fallback must NOT fire.
    tool = CodeExecutorTool(
        tool_config={"workflow_run_id": CONV, "attachments": [att]}, user_id=USER
    )
    out = tool._materialize_inputs(_Manager(), "sess", ["wf.pdf"])
    assert "not found in this conversation/run" in out["error"]
    assert calls == []  # no double-bridge in workflow scope


@pytest.mark.unit
def test_code_executor_unresolvable_ref_still_errors(monkeypatch):
    from application.agents.tools.code_executor import CodeExecutorTool

    _patch_bridge(monkeypatch)
    _patch_code_executor_repo(monkeypatch)
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": []}, user_id=USER
    )
    out = tool._materialize_inputs(_Manager(), "sess", ["ghost.bin"])
    assert "not found in this conversation/run" in out["error"]


@pytest.mark.unit
def test_code_executor_existing_artifact_still_used(monkeypatch):
    """A ref that resolves to a real artifact uses it directly (no bridge regression)."""
    from application.agents.tools.code_executor import CodeExecutorTool

    storage, calls = _patch_bridge(monkeypatch)
    _patch_code_executor_repo(monkeypatch)
    real_id = str(uuid.uuid4())
    _FakeArtifactsRepo.artifacts = {
        real_id: {
            "conversation_id": CONV,
            "current_version": 1,
            "versions": {1: {"storage_path": "store/real", "filename": "real.txt"}},
        }
    }
    monkeypatch.setattr(
        "application.agents.tools.code_executor.StorageCreator.get_storage",
        staticmethod(lambda: storage),
    )
    tool = CodeExecutorTool(
        tool_config={"conversation_id": CONV, "attachments": []}, user_id=USER
    )
    mgr = _Manager()
    out = tool._materialize_inputs(mgr, "sess", [real_id])
    assert out["loaded"] == ["inputs/real.txt"]
    assert calls == []  # existing artifact -> no bridge


# ---------------------------------------------------------------------------
# read_document wiring
# ---------------------------------------------------------------------------
def _patch_read_document_repo(monkeypatch):
    import application.agents.tools.read_document as rd

    monkeypatch.setattr(rd, "db_readonly", _fake_db)
    monkeypatch.setattr(rd, "ArtifactsRepository", _FakeArtifactsRepo)


@pytest.mark.unit
def test_read_document_bridges_attachment_then_enqueues(monkeypatch):
    import application.agents.tools.read_document as rd
    from application.agents.tools.read_document import ReadDocumentTool

    _storage, calls = _patch_bridge(monkeypatch, persisted_id="art-RD")
    _patch_read_document_repo(monkeypatch)
    att = _attachment(filename="invoice.pdf", path="up/invoice.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}

    captured: Dict[str, Any] = {}

    class _AR:
        def get(self, timeout=None, disable_sync_subtasks=True):
            return {"status": "ok", "content": "parsed", "truncated": False}

    import application.api.user.tasks as tasks

    def _apply_async(args=None, queue=None, **kw):
        captured["args"] = args
        return _AR()

    monkeypatch.setattr(tasks.parse_document, "apply_async", _apply_async)

    tool = ReadDocumentTool(
        tool_config={"conversation_id": CONV, "attachments": [att]}, user_id=USER
    )
    out = tool.execute_action("read_document", input="invoice.pdf", persist=False)
    assert out["status"] == "ok"
    # The bridged artifact id (not the raw name) was enqueued, with the conversation parent.
    assert captured["args"][0] == "art-RD"
    assert captured["args"][1] == {"conversation_id": CONV}
    assert len(calls) == 1
    _ = rd  # keep import referenced


@pytest.mark.unit
def test_read_document_workflow_scope_does_not_bridge(monkeypatch):
    from application.agents.tools.read_document import ReadDocumentTool

    _storage, calls = _patch_bridge(monkeypatch)
    _patch_read_document_repo(monkeypatch)
    att = _attachment(filename="wf.pdf")
    _FakeAttachmentsRepo.rows = {att["id"]: att}

    import application.api.user.tasks as tasks
    monkeypatch.setattr(
        tasks.parse_document, "apply_async",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not enqueue")),
    )

    tool = ReadDocumentTool(
        tool_config={"workflow_run_id": CONV, "attachments": [att]}, user_id=USER
    )
    out = tool.execute_action("read_document", input="wf.pdf", persist=False)
    assert out["status"] == "error" and "not found in this conversation/run" in out["error"]
    assert calls == []
