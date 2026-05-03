"""Smoke test for ``application.worker.ingest_connector`` in sync mode.

Sync mode (``operation_mode="sync"``) bumps ``sources.date`` on the
target source row, the same PG side-effect as ``remote_worker``. Upload
mode does not write to PG directly — that happens indirectly via the
``upload_index`` HTTP callback to the backend — so the happy-path smoke
is the sync variant.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def _mock_connector_pipeline(monkeypatch):
    """Stub the connector + pipeline so only PG writes are real."""
    from application import worker

    fake_connector = MagicMock(name="connector")
    fake_connector.download_to_directory.return_value = {
        "files_downloaded": 1,
        "empty_result": False,
    }
    monkeypatch.setattr(
        worker.ConnectorCreator, "is_supported", staticmethod(lambda s: True)
    )
    monkeypatch.setattr(
        worker.ConnectorCreator,
        "create_connector",
        staticmethod(lambda source_type, session_token: fake_connector),
    )

    fake_reader = MagicMock(name="reader")
    fake_reader.load_data.return_value = [
        Document(
            text="connector body",
            extra_info={"source": "connector/file.md", "file_path": "file.md"},
        )
    ]
    fake_reader.directory_structure = {
        "file.md": {
            "type": "text/markdown",
            "size_bytes": 12,
            "token_count": 3,
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
        worker, "upload_index", lambda full_path, file_data: None
    )


@pytest.mark.unit
class TestIngestConnectorSyncUpdatesDate:
    def test_sync_mode_bumps_source_date(
        self,
        pg_conn,
        patch_worker_db,
        task_self,
        monkeypatch,
        _mock_connector_pipeline,
    ):
        from application import worker
        import datetime as dt

        old_date = dt.datetime(2019, 6, 1, tzinfo=dt.timezone.utc)
        src = SourcesRepository(pg_conn).create(
            "gdrive-folder",
            user_id="dave",
            type="connector:file",
            retriever="classic",
            sync_frequency="weekly",
            remote_data={"provider": "google_drive"},
            date=old_date,
        )
        source_id = str(src["id"])

        worker.ingest_connector(
            task_self,
            "gdrive-folder",
            "dave",
            "google_drive",
            session_token="tok",
            file_ids=["f1"],
            folder_ids=[],
            operation_mode="sync",
            doc_id=source_id,
            sync_frequency="weekly",
        )

        refreshed = SourcesRepository(pg_conn).get(source_id, "dave")
        assert refreshed is not None
        assert refreshed["date"] > old_date, (
            "ingest_connector(sync) should push sources.date forward"
        )


@pytest.mark.unit
class TestIngestConnectorDeterministicSourceId:
    """Upload-mode ``ingest_connector`` derives a stable ``source_id`` from the key."""

    def test_uses_uuid5_when_idempotency_key_present(
        self,
        task_self,
        monkeypatch,
        _mock_connector_pipeline,
    ):
        from application import worker

        captured: list[dict] = []
        monkeypatch.setattr(
            worker, "upload_index",
            lambda full_path, file_data: captured.append(file_data),
        )

        for _ in range(2):
            worker.ingest_connector(
                task_self,
                "gdrive-folder",
                "dave",
                "google_drive",
                session_token="tok",
                file_ids=["f1"],
                folder_ids=[],
                operation_mode="upload",
                idempotency_key="abc",
            )

        expected = str(uuid.uuid5(worker.DOCSGPT_INGEST_NAMESPACE, "abc"))
        assert len(captured) == 2
        assert captured[0]["id"] == expected
        assert captured[1]["id"] == expected

    def test_falls_back_to_uuid4_without_key(
        self,
        task_self,
        monkeypatch,
        _mock_connector_pipeline,
    ):
        from application import worker

        captured: list[dict] = []
        monkeypatch.setattr(
            worker, "upload_index",
            lambda full_path, file_data: captured.append(file_data),
        )

        for _ in range(2):
            worker.ingest_connector(
                task_self,
                "gdrive-folder",
                "dave",
                "google_drive",
                session_token="tok",
                file_ids=["f1"],
                folder_ids=[],
                operation_mode="upload",
            )

        assert len(captured) == 2
        assert captured[0]["id"] != captured[1]["id"]
