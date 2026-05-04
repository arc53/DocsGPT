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

import uuid
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document


def _patch_ingest_pipeline(monkeypatch, captured):
    """Stub the non-PG boundaries used by ``ingest_worker``.

    Storage, the directory reader, the embedding pipeline, and
    ``upload_index`` are all replaced with cheap fakes so the worker
    runs end-to-end inside the test process. ``captured`` is appended
    with each ``upload_index`` payload so callers can assert on the
    derived ``source_id``.
    """
    from application import worker

    fake_storage = MagicMock(name="storage")
    fake_storage.is_directory.return_value = False
    fake_storage.get_file.return_value = BytesIO(b"hello")
    monkeypatch.setattr(
        worker.StorageCreator, "get_storage", lambda: fake_storage
    )

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
        lambda docs, full_path, source_id, task, **kw: None,
    )

    monkeypatch.setattr(
        worker, "upload_index",
        lambda full_path, file_data: captured.append(file_data),
    )


@pytest.mark.unit
class TestIngestWorker:
    def test_invokes_upload_index_with_expected_payload(
        self, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)

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


@pytest.mark.unit
class TestIngestWorkerDeterministicSourceId:
    """Retried ingests with the same key should land on the same source row."""

    def test_uses_uuid5_when_idempotency_key_present(
        self, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)

        worker.ingest_worker(
            task_self,
            directory="inputs",
            formats=[".txt"],
            job_name="job1",
            file_path="inputs/eve/job1/a.txt",
            filename="a.txt",
            user="eve",
            idempotency_key="abc",
        )
        worker.ingest_worker(
            task_self,
            directory="inputs",
            formats=[".txt"],
            job_name="job1",
            file_path="inputs/eve/job1/a.txt",
            filename="a.txt",
            user="eve",
            idempotency_key="abc",
        )

        expected = str(
            uuid.uuid5(worker.DOCSGPT_INGEST_NAMESPACE, "abc")
        )
        assert len(captured) == 2
        assert captured[0]["id"] == expected
        assert captured[1]["id"] == expected

    def test_falls_back_to_uuid4_without_key(
        self, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)

        for _ in range(2):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
            )

        assert len(captured) == 2
        # Random uuid4 fallback: two runs must produce different ids.
        assert captured[0]["id"] != captured[1]["id"]

    def test_double_ingest_writes_one_source_row(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """Run the worker body twice with the same key; assert the
        backend-side ``upload_index`` would persist one row, not two.

        ``upload_index`` is the actual backend write path; the worker
        feeds it a ``file_data`` payload keyed by the derived id. We
        emulate that path locally (``SourcesRepository.create``) on the
        first call and assert the second call hits the existing-row
        branch instead of inserting again.
        """
        from application import worker
        from application.storage.db.repositories.sources import SourcesRepository

        captured: list[dict] = []
        _patch_ingest_pipeline(monkeypatch, captured)

        def _persist(full_path, file_data):
            captured.append(file_data)
            repo = SourcesRepository(pg_conn)
            existing = repo.get(file_data["id"], file_data["user"])
            if existing is None:
                repo.create(
                    file_data["name"],
                    source_id=file_data["id"],
                    user_id=file_data["user"],
                    type=file_data["type"],
                    retriever=file_data["retriever"],
                    tokens=file_data["tokens"],
                )

        monkeypatch.setattr(worker, "upload_index", _persist)

        for _ in range(2):
            worker.ingest_worker(
                task_self,
                directory="inputs",
                formats=[".txt"],
                job_name="job1",
                file_path="inputs/eve/job1/a.txt",
                filename="a.txt",
                user="eve",
                idempotency_key="dedupe-key",
            )

        expected = str(
            uuid.uuid5(worker.DOCSGPT_INGEST_NAMESPACE, "dedupe-key")
        )
        assert captured[0]["id"] == expected
        assert captured[1]["id"] == expected

        # Exactly one row in PG for that derived id.
        result = pg_conn.exec_driver_sql(
            "SELECT count(*) FROM sources WHERE id = %s",
            (expected,),
        ).fetchone()
        assert result[0] == 1
