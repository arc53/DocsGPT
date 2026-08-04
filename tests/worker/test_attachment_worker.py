"""Smoke test for ``application.worker.attachment_worker``.

The happy path parses an uploaded file and inserts a row into
``attachments``. We mock the parser boundary (``StorageCreator.get_storage``
returns a storage whose ``process_file`` produces a pre-built Document)
but let the PG insert run against the ephemeral ``pg_conn`` so we can
assert one concrete row is visible after the task returns.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.attachments import AttachmentsRepository


@pytest.mark.unit
class TestAttachmentWorker:
    def test_inserts_row_in_attachments(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        fake_doc = Document(
            text="hello world",
            extra_info={"transcript_language": "en"},
        )

        fake_storage = MagicMock(name="storage")
        fake_storage.process_file.return_value = fake_doc
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )

        # Stub the parser selection so the docling import path isn't taken.
        monkeypatch.setattr(
            worker, "get_default_file_extractor", lambda ocr_enabled=False: {}
        )

        file_info = {
            "filename": "notes.txt",
            "attachment_id": "507f1f77bcf86cd799439011",
            "path": "uploads/user1/notes.txt",
            "metadata": {"source": "chat"},
        }

        result = worker.attachment_worker(task_self, file_info, "user1")

        assert result["filename"] == "notes.txt"
        assert result["token_count"] > 0
        # Parser metadata (``transcript_*``) should have been merged in.
        assert result["metadata"]["transcript_language"] == "en"
        assert result["metadata"]["source"] == "chat"

        # Row should be resolvable by the caller-visible handle stored in
        # ``legacy_mongo_id``.
        row = AttachmentsRepository(pg_conn).get_by_legacy_id(
            file_info["attachment_id"], "user1"
        )
        assert row is not None, "attachment_worker should insert a row"
        assert row["filename"] == "notes.txt"
        assert row["upload_path"] == "uploads/user1/notes.txt"
        assert row["content"] == "hello world"
        assert row["user_id"] == "user1"


@pytest.mark.unit
class TestBoundedAttachmentCopy:
    """``_bounded_attachment_copy`` head-truncates oversized line-oriented
    text attachments to a temp copy before parsing.

    The parsed content is capped at ~250k chars downstream anyway, so bytes
    beyond the cap only cost parse time and memory. Local storage hands the
    canonical stored file to the processor, so truncation must never happen
    in place.
    """

    def _write(self, tmp_path, name: str, data: bytes):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    def test_oversized_csv_is_copied_and_truncated(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_BYTES", 1024)
        original = self._write(
            tmp_path, "big.csv", b"".join(b"%d,%d\n" % (i, i) for i in range(1000))
        )
        original_size = original.stat().st_size

        parse_path, is_temp = worker._bounded_attachment_copy(str(original))

        assert is_temp is True
        assert parse_path != str(original)
        assert parse_path.endswith(".csv")
        copied = Path(parse_path).read_bytes()
        assert 0 < len(copied) <= 1024
        assert copied.endswith(b"\n"), "must cut on a line boundary"
        # The stored original must be untouched.
        assert original.stat().st_size == original_size
        Path(parse_path).unlink()

    def test_small_file_returned_as_is(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_BYTES", 1024)
        original = self._write(tmp_path, "small.csv", b"a,b\n1,2\n")

        parse_path, is_temp = worker._bounded_attachment_copy(str(original))

        assert parse_path == str(original)
        assert is_temp is False

    def test_non_text_suffix_is_never_truncated(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_BYTES", 64)
        original = self._write(tmp_path, "doc.pdf", b"%PDF-1.7 " + b"x" * 500)

        parse_path, is_temp = worker._bounded_attachment_copy(str(original))

        assert parse_path == str(original)
        assert is_temp is False

    def test_cap_zero_disables_truncation(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_BYTES", 0)
        original = self._write(tmp_path, "big.csv", b"1,2\n" * 1000)

        parse_path, is_temp = worker._bounded_attachment_copy(str(original))

        assert parse_path == str(original)
        assert is_temp is False

    def test_single_line_without_newline_falls_back_to_hard_cut(
        self, tmp_path, monkeypatch
    ):
        from application import worker
        from application.core.settings import settings

        monkeypatch.setattr(settings, "ATTACHMENT_TEXT_MAX_BYTES", 256)
        original = self._write(tmp_path, "oneline.txt", b"x" * 5000)

        parse_path, is_temp = worker._bounded_attachment_copy(str(original))

        assert is_temp is True
        data = Path(parse_path).read_bytes()
        assert len(data) == 256
        Path(parse_path).unlink()


@pytest.mark.unit
class TestAttachmentZipBombGuard:
    """``_reject_attachment_zip_bomb`` brings the ingest-path zip-bomb guard to
    the attachment path (which previously had none): a zip-container attachment
    that declares too many entries / too much inner data is rejected before any
    parser touches it, with a non-retryable error."""

    def _make_xlsx(self, path: Path, rows: int = 20):
        from openpyxl import Workbook

        wb = Workbook(write_only=True)
        ws = wb.create_sheet()
        for i in range(rows):
            ws.append([i, i * 2, i * 3])
        wb.save(str(path))

    def test_rejects_when_inner_size_exceeds_cap(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        path = tmp_path / "book.xlsx"
        self._make_xlsx(path)
        monkeypatch.setattr(settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 100)

        with pytest.raises(worker.AttachmentRejectedError):
            worker._reject_attachment_zip_bomb(str(path))

    def test_rejects_when_too_many_entries(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        path = tmp_path / "book.xlsx"
        self._make_xlsx(path)
        monkeypatch.setattr(settings, "DOCUMENT_MAX_ARCHIVE_ENTRIES", 1)

        with pytest.raises(worker.AttachmentRejectedError):
            worker._reject_attachment_zip_bomb(str(path))

    def test_allows_reasonable_archive(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        path = tmp_path / "book.xlsx"
        self._make_xlsx(path)
        monkeypatch.setattr(settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 300 * 1024 * 1024)
        monkeypatch.setattr(settings, "DOCUMENT_MAX_ARCHIVE_ENTRIES", 10000)

        # Must not raise.
        worker._reject_attachment_zip_bomb(str(path))

    def test_non_container_suffix_is_ignored(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        path = tmp_path / "notes.txt"
        path.write_bytes(b"x" * 5000)
        monkeypatch.setattr(settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1)

        # Text files are not zip containers — never inspected, never rejected.
        worker._reject_attachment_zip_bomb(str(path))

    def test_corrupt_zip_is_left_to_the_parser(self, tmp_path, monkeypatch):
        from application import worker
        from application.core.settings import settings

        path = tmp_path / "broken.xlsx"
        path.write_bytes(b"not a real zip")
        monkeypatch.setattr(settings, "DOCUMENT_MAX_DECOMPRESSED_BYTES", 1)

        # BadZipFile → return quietly; the format parser surfaces a clean error.
        worker._reject_attachment_zip_bomb(str(path))
