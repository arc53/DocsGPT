"""Smoke test for ``application.worker.ingest_worker``.

``ingest_worker`` does **not** write to Postgres directly. Its PG
side-effect (creating the ``sources`` row) goes through the
``upload_index`` HTTP callback to the backend, which writes to PG in
its own request context. That callback is intentionally out of scope
here — we can't reach it from the worker test without spinning up the
Flask app.

What we *can* smoke: the task body runs end-to-end, the pipeline gets
invoked with the expected job metadata, and ``upload_index`` is handed
a ``file_data`` payload that carries the caller-provided ``user``,
``job_name``, and ``retriever``. That's the contract the
backend-facing write depends on.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document


@pytest.mark.unit
class TestIngestWorker:
    def test_invokes_upload_index_with_expected_payload(
        self, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        # Storage: pretend a single file was uploaded at ``inputs/.../a.txt``.
        from io import BytesIO
        fake_storage = MagicMock(name="storage")
        fake_storage.is_directory.return_value = False
        fake_storage.get_file.return_value = BytesIO(b"hello")
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )

        # Reader: return a parsed doc.
        fake_reader = MagicMock(name="reader")
        fake_reader.load_data.return_value = [
            Document(text="hello body", extra_info={"source": "a.txt"})
        ]
        fake_reader.directory_structure = {
            "a.txt": {
                "type": "text/plain",
                "size_bytes": 5,
                "token_count": 2,
            }
        }
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
        )

        monkeypatch.setattr(
            worker,
            "embed_and_store_documents",
            lambda docs, full_path, source_id, task: None,
        )

        captured: list[dict] = []

        def _fake_upload(full_path, file_data):
            captured.append(file_data)

        monkeypatch.setattr(worker, "upload_index", _fake_upload)

        result = worker.ingest_worker(
            task_self,
            directory="inputs",
            formats=[".txt"],
            job_name="job1",
            file_path="inputs/eve/job1/a.txt",
            filename="a.txt",
            user="eve",
            retriever="classic",
        )

        assert result["limited"] is False
        assert result["user"] == "eve"
        assert result["name_job"] == "job1"

        assert len(captured) == 1
        payload = captured[0]
        assert payload["user"] == "eve"
        assert payload["name"] == "job1"
        assert payload["retriever"] == "classic"
        assert payload["type"] == "local"
        # A fresh source UUID is minted for the backend /upload_index route.
        assert payload["id"]
