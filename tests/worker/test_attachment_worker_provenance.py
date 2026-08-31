"""Extraction-provenance tests for ``attachment_worker``.

Every parse attempt must leave a queryable trace in ``attachments``:
``metadata.extraction`` records what happened (status, parser, truncation,
token counts, error) on success, truncation, and terminal failure alike.
Runs against a real ephemeral Postgres so the rows the worker writes are
asserted as stored, not as mocked calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

import application.storage.db.engine as engine_module
from application.parser.file.base_parser import DocumentParseError
from application.storage.db.repositories.attachments import AttachmentsRepository
from application.storage.db.session import db_readonly
from application.utils import get_encoding


class _StubTask:
    def update_state(self, *args, **kwargs):
        pass


class _Doc:
    def __init__(self, text):
        self.text = text
        self.extra_info = {}


@pytest.fixture()
def wired_engine(pg_engine, monkeypatch):
    """Point the app's module-level engine cache at the ephemeral DB."""
    monkeypatch.setattr(engine_module, "_engine", None)
    eng = engine_module.get_engine()
    yield eng
    eng.dispose()
    monkeypatch.setattr(engine_module, "_engine", None)


@pytest.fixture()
def storage_dir(tmp_path, monkeypatch):
    """LocalStorage rooted at tmp_path, patched into the worker."""
    from application.storage.local import LocalStorage

    storage = LocalStorage(base_dir=str(tmp_path))
    monkeypatch.setattr(
        "application.storage.storage_creator.StorageCreator.get_storage",
        classmethod(lambda cls: storage),
    )
    return tmp_path


def _run_worker(file_info, user="prov-user"):
    from application.worker import attachment_worker

    return attachment_worker(_StubTask(), file_info, user)


def _file_info(storage_dir, filename="doc.txt", content=b"hello attachment"):
    attachment_id = str(uuid.uuid4())
    rel_path = f"inputs/prov-user/attachments/{attachment_id}/{filename}"
    full = storage_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return {
        "filename": filename,
        "attachment_id": attachment_id,
        "path": rel_path,
        "metadata": {"storage_type": "local"},
    }


def _fetch(attachment_id, user="prov-user"):
    with db_readonly() as conn:
        return AttachmentsRepository(conn).get_by_legacy_id(str(attachment_id), user)


def _count(user="prov-user"):
    with db_readonly() as conn:
        return len(AttachmentsRepository(conn).list_for_user(user))


@pytest.mark.usefixtures("wired_engine")
class TestSuccessProvenance:
    def test_ok_row_records_extraction_metadata(self, storage_dir):
        info = _file_info(storage_dir)

        result = _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row is not None
        extraction = (row["metadata"] or {}).get("extraction")
        assert extraction is not None
        assert extraction["status"] == "ok"
        assert extraction["truncated"] is False
        assert extraction["original_tokens"] == extraction["stored_tokens"]
        assert extraction["stored_tokens"] == row["token_count"]
        assert extraction.get("parser")
        assert "hello attachment" in row["content"]
        assert result["token_count"] == row["token_count"]

    def test_upload_metadata_keys_preserved(self, storage_dir):
        info = _file_info(storage_dir)

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        # The storage-level metadata written at upload time must survive
        # the extraction merge.
        assert row["metadata"]["storage_type"] == "local"


@pytest.mark.usefixtures("wired_engine")
class TestTruncationProvenance:
    def test_over_gate_content_truncated_in_token_units(self, storage_dir, monkeypatch):
        # Dense CJK: ~1.4 tokens/char, so a char-unit cut (the old
        # behavior) would store far more than 100k tokens.
        dense = "統計資料表格內容分析、報告書類文書處理系統。設計開發運用管理。\n" * 10000
        info = _file_info(storage_dir)
        monkeypatch.setattr(
            "application.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc(dense)]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "ok"
        assert extraction["truncated"] is True
        assert extraction["stored_tokens"] == 100000
        assert extraction["original_tokens"] > 100000
        assert row["token_count"] == 100000
        # The stored content really is ~100k tokens, not a 250k-char cut
        # still worth 300k+ tokens.
        enc = get_encoding()
        assert len(enc.encode_ordinary(row["content"])) <= 100100

    def test_under_gate_content_not_truncated(self, storage_dir, monkeypatch):
        text = "plain short attachment content"
        info = _file_info(storage_dir)
        monkeypatch.setattr(
            "application.worker.SimpleDirectoryReader",
            lambda **kwargs: type("R", (), {"load_data": lambda self: [_Doc(text)]})(),
        )

        _run_worker(info)

        row = _fetch(info["attachment_id"])
        extraction = row["metadata"]["extraction"]
        assert extraction["truncated"] is False
        assert row["content"] == text


@pytest.mark.usefixtures("wired_engine")
class TestFailureProvenance:
    def test_terminal_parse_failure_writes_failed_row(self, storage_dir, monkeypatch):
        info = _file_info(storage_dir, filename="broken.xlsx")

        def _raise(**kwargs):
            raise DocumentParseError("Failed to parse broken.xlsx with docling: boom")

        monkeypatch.setattr("application.worker.SimpleDirectoryReader", _raise)

        with pytest.raises(DocumentParseError):
            _run_worker(info)

        row = _fetch(info["attachment_id"])
        assert row is not None, "terminal failure must leave a queryable row"
        assert row["content"] is None
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "failed"
        assert "boom" in extraction["error"]
        # The parser's exception text must never masquerade as document
        # content.
        assert row["token_count"] is None

    def test_retry_then_success_upserts_single_row(self, storage_dir, monkeypatch):
        info = _file_info(storage_dir)
        calls = {"n": 0}

        def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient blip")
            return type("R", (), {"load_data": lambda self: [_Doc("recovered fine")]})()

        monkeypatch.setattr("application.worker.SimpleDirectoryReader", _flaky)

        with pytest.raises(RuntimeError):
            _run_worker(info)
        failed_row = _fetch(info["attachment_id"])
        assert failed_row["metadata"]["extraction"]["status"] == "failed"

        _run_worker(info)

        assert _count() == 1, "retry success must update the failure row, not add one"
        row = _fetch(info["attachment_id"])
        assert row["metadata"]["extraction"]["status"] == "ok"
        assert row["content"] == "recovered fine"

    def test_post_store_failure_does_not_clobber_ok_row(self, storage_dir):
        # An exception after the success write (e.g. event publishing) must
        # not replace stored content with a NULL-content failed row; the
        # extraction result is already durable.
        from application.worker import record_attachment_failure

        info = _file_info(storage_dir)
        _run_worker(info)

        record_attachment_failure("prov-user", info, RuntimeError("post-store blip"))

        row = _fetch(info["attachment_id"])
        assert row["metadata"]["extraction"]["status"] == "ok"
        assert "hello attachment" in row["content"]

    def test_failure_row_write_failure_does_not_mask_original_error(
        self, storage_dir, monkeypatch
    ):
        info = _file_info(storage_dir)

        def _raise(**kwargs):
            raise DocumentParseError("original parse error")

        monkeypatch.setattr("application.worker.SimpleDirectoryReader", _raise)
        monkeypatch.setattr(
            "application.worker.db_session",
            _raising_db_session,
        )

        with pytest.raises(DocumentParseError, match="original parse error"):
            _run_worker(info)


def _raising_db_session():
    raise ConnectionError("db down")


@pytest.mark.usefixtures("wired_engine")
class TestPoisonProvenance:
    def test_poison_guard_writes_failed_row(self):
        from application.api.user.tasks import _emit_attachment_poison_event

        attachment_id = str(uuid.uuid4())
        bound = {
            "user": "prov-user",
            "file_info": {
                "filename": "poison.pdf",
                "attachment_id": attachment_id,
                "path": "inputs/prov-user/attachments/x/poison.pdf",
            },
        }

        with patch("application.events.publisher.publish_user_event"):
            _emit_attachment_poison_event("store_attachment", bound)

        row = _fetch(attachment_id)
        assert row is not None, "poison-guard trip must leave a queryable row"
        extraction = row["metadata"]["extraction"]
        assert extraction["status"] == "failed"
        assert "repeated failures" in extraction["error"]
