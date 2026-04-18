"""Smoke test for ``application.worker.attachment_worker``.

The happy path parses an uploaded file and inserts a row into
``attachments``. We mock the parser boundary (``StorageCreator.get_storage``
returns a storage whose ``process_file`` produces a pre-built Document)
but let the PG insert run against the ephemeral ``pg_conn`` so we can
assert one concrete row is visible after the task returns.
"""

from __future__ import annotations

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
