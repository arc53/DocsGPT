"""Smoke test for ``docsgpt.worker.ingest_connector`` in sync mode.

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

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository


@pytest.fixture
def _mock_connector_pipeline(monkeypatch):
    """Stub the connector + pipeline so only PG writes are real."""
    from docsgpt import worker

    fake_connector = MagicMock(name="connector")
    fake_connector.connection_id = None
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
        staticmethod(lambda source_type, session_token=None, connection_id=None: fake_connector),
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
    return fake_connector


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
        from docsgpt import worker
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
        # row_to_dict coerces datetimes to ISO 8601 strings; UTC
        # timezone-aware ISO strings sort chronologically.
        assert refreshed["date"] > old_date.isoformat(), (
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
        from docsgpt import worker

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
        from docsgpt import worker

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


def _gdrive_source(pg_conn, remote_data):
    import datetime as dt

    return SourcesRepository(pg_conn).create(
        "gdrive-folder",
        user_id="dave",
        type="connector:file",
        retriever="classic",
        sync_frequency="daily",
        remote_data={"provider": "google_drive", "folder_ids": ["root"], **remote_data},
        date=dt.datetime(2019, 6, 1, tzinfo=dt.timezone.utc),
    )


def _sync(worker, task_self, source_id, config=None):
    return worker.ingest_connector(
        task_self,
        "gdrive-folder",
        "dave",
        "google_drive",
        session_token="tok",
        folder_ids=["root"],
        operation_mode="sync",
        doc_id=source_id,
        sync_frequency="daily",
        config=config,
    )


@pytest.mark.unit
class TestIngestConnectorSkipsUnchangedSync:
    """A sync whose selection fingerprint matches the stored one keeps the index."""

    def test_unchanged_selection_skips_download_and_embed(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.sync_fingerprint.return_value = "fp-1"
        src = _gdrive_source(pg_conn, {"sync_fingerprint": worker._connector_sync_fingerprint("fp-1", None)})
        uploads: list[dict] = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))

        result = _sync(worker, task_self, str(src["id"]))

        assert result["status"] == "unchanged"
        connector.download_to_directory.assert_not_called()
        assert uploads == []
        refreshed = SourcesRepository(pg_conn).get(str(src["id"]), "dave")
        assert refreshed["date"] > "2019-06-01", "an unchanged sync still records that it ran"

    def test_changed_selection_reingests_and_stores_new_fingerprint(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        import json

        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.sync_fingerprint.return_value = "fp-2"
        connector.download_to_directory.return_value = {
            "files_downloaded": 1, "empty_result": False, "sync_fingerprint": "fp-2",
        }
        src = _gdrive_source(pg_conn, {"sync_fingerprint": worker._connector_sync_fingerprint("fp-1", None)})
        uploads: list[dict] = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))

        _sync(worker, task_self, str(src["id"]))

        connector.download_to_directory.assert_called_once()
        remote_data = json.loads(uploads[0]["remote_data"])
        assert remote_data["sync_fingerprint"] == worker._connector_sync_fingerprint("fp-2", None)
        assert remote_data["folder_ids"] == ["root"]

    def test_settings_change_forces_reingest(
        self, pg_conn, patch_worker_db, task_self, _mock_connector_pipeline,
    ):
        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.sync_fingerprint.return_value = "fp-1"
        src = _gdrive_source(pg_conn, {"sync_fingerprint": worker._connector_sync_fingerprint("fp-1", None)})
        # The source's settings changed after its last ingest.
        SourcesRepository(pg_conn).update(str(src["id"]), "dave", {"config": {"chunking": {"max_tokens": 500}}})

        _sync(worker, task_self, str(src["id"]))

        connector.download_to_directory.assert_called_once()

    @pytest.mark.parametrize("stored, current", [(None, "fp-1"), ("fp-1", None)])
    def test_missing_fingerprint_reingests(
        self, pg_conn, patch_worker_db, task_self, _mock_connector_pipeline, stored, current,
    ):
        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.sync_fingerprint.return_value = current
        remote_data = {"sync_fingerprint": worker._connector_sync_fingerprint(stored, None)} if stored else {}
        src = _gdrive_source(pg_conn, remote_data)

        _sync(worker, task_self, str(src["id"]))

        connector.download_to_directory.assert_called_once()

    def test_fingerprint_error_reingests(
        self, pg_conn, patch_worker_db, task_self, _mock_connector_pipeline,
    ):
        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.sync_fingerprint.side_effect = RuntimeError("drive down")
        src = _gdrive_source(pg_conn, {"sync_fingerprint": worker._connector_sync_fingerprint("fp-1", None)})

        _sync(worker, task_self, str(src["id"]))

        connector.download_to_directory.assert_called_once()

    def test_upload_without_fingerprint_stores_none(self, task_self, monkeypatch, _mock_connector_pipeline):
        import json

        from docsgpt import worker

        uploads: list[dict] = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))

        worker.ingest_connector(
            task_self, "gdrive-folder", "dave", "google_drive",
            session_token="tok", file_ids=["f1"], operation_mode="upload",
        )

        assert "sync_fingerprint" not in json.loads(uploads[0]["remote_data"])
        _mock_connector_pipeline.sync_fingerprint.assert_not_called()


@pytest.mark.unit
class TestConnectorSyncFingerprint:
    def test_none_without_selection_fingerprint(self):
        from docsgpt import worker

        assert worker._connector_sync_fingerprint(None, {"a": 1}) is None

    def test_config_changes_it_and_json_matches_dict(self):
        from docsgpt import worker

        base = worker._connector_sync_fingerprint("fp", None)
        assert base == worker._connector_sync_fingerprint("fp", {})
        tuned = worker._connector_sync_fingerprint("fp", {"chunking": {"max_tokens": 500}})
        assert tuned != base
        assert tuned == worker._connector_sync_fingerprint("fp", '{"chunking": {"max_tokens": 500}}')


@pytest.mark.unit
class TestConnectorSyncTakesTheIndexLock:
    """A connector sync takes turns with the source's other index jobs, and keeps the row's settings."""

    def test_a_sync_uploads_holding_the_lock(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        from contextlib import contextmanager

        from docsgpt import worker

        src = _gdrive_source(pg_conn, {})
        held = []

        @contextmanager
        def fake_lock(source_id, **kwargs):
            held.append(source_id)
            yield
            held.append("released")

        monkeypatch.setattr(worker, "source_index_lock", fake_lock)
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: held.append("upload"))

        _sync(worker, task_self, str(src["id"]))

        assert held == [str(src["id"]), "upload", "released"]

    def test_a_wiki_conversion_finished_while_waiting_is_respected(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        from contextlib import contextmanager

        from docsgpt import worker

        src = _gdrive_source(pg_conn, {})

        @contextmanager
        def converted_while_waiting(source_id, **kwargs):
            SourcesRepository(pg_conn).update(str(src["id"]), "dave", {"config": {"kind": "wiki"}})
            yield

        monkeypatch.setattr(worker, "source_index_lock", converted_while_waiting)
        events = []
        monkeypatch.setattr(
            worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((kind, payload))
        )

        result = _sync(worker, task_self, str(src["id"]))

        assert result == {"status": "skipped", "reason": "wiki"}
        _mock_connector_pipeline.download_to_directory.assert_not_called()
        assert [(kind, payload["reason"]) for kind, payload in events] == [("source.ingest.failed", "wiki")]

    def test_a_deleted_source_is_skipped(self, pg_conn, patch_worker_db, task_self, _mock_connector_pipeline):
        from docsgpt import worker

        result = _sync(worker, task_self, str(uuid.uuid4()))

        assert result == {"status": "skipped", "reason": "gone"}
        _mock_connector_pipeline.download_to_directory.assert_not_called()

    def test_a_busy_source_is_skipped(self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline):
        from contextlib import contextmanager

        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = _gdrive_source(pg_conn, {})

        @contextmanager
        def busy(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        monkeypatch.setattr(worker, "source_index_lock", busy)

        assert _sync(worker, task_self, str(src["id"])) == {"status": "skipped", "reason": "busy"}
        _mock_connector_pipeline.download_to_directory.assert_not_called()

    def test_a_sync_sends_content_and_its_fingerprint_only(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, _mock_connector_pipeline,
    ):
        from docsgpt import worker

        connector = _mock_connector_pipeline
        connector.download_to_directory.return_value = {
            "files_downloaded": 1, "empty_result": False, "sync_fingerprint": "fp-2",
        }
        src = _gdrive_source(pg_conn, {})
        SourcesRepository(pg_conn).update(str(src["id"]), "dave", {"config": {"chunking": {"max_tokens": 300}}})
        uploads = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))

        _sync(worker, task_self, str(src["id"]), config={"chunking": {"max_tokens": 900}})

        [sent] = uploads
        assert sent["operation"] == "sync"
        assert "config" not in sent
        # Chunked, and fingerprinted, with the row's settings as they are under the lock.
        stored = {"chunking": {"max_tokens": 300}}
        assert sent["sync_fingerprint"] == worker._connector_sync_fingerprint("fp-2", stored)

    def test_a_sync_reads_the_rows_selection(
        self, pg_conn, patch_worker_db, task_self, _mock_connector_pipeline,
    ):
        from docsgpt import worker

        src = _gdrive_source(pg_conn, {"folder_ids": ["picked-meanwhile"], "file_ids": ["f9"]})

        _sync(worker, task_self, str(src["id"]))

        selection = _mock_connector_pipeline.download_to_directory.call_args.args[1]
        assert selection["folder_ids"] == ["picked-meanwhile"] and selection["file_ids"] == ["f9"]

    def test_the_first_ingest_still_sends_everything(self, task_self, monkeypatch, _mock_connector_pipeline):
        from docsgpt import worker

        uploads = []
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: uploads.append(file_data))

        worker.ingest_connector(
            task_self, "gdrive-folder", "dave", "google_drive",
            session_token="tok", file_ids=["f1"], operation_mode="upload", config={"chunking": {"max_tokens": 9}},
        )

        assert "operation" not in uploads[0]
        assert uploads[0]["config"]
