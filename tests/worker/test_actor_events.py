"""A team editor who changes a source they don't own hears its ``source.ingest.*`` events.

The route runs the job as the source's owner and passes the editor as
``actor_id``; each event goes to the owner and to the editor.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository
from tests.worker.test_ingest_connector import _gdrive_source, _mock_connector_pipeline  # noqa: F401
from tests.worker.test_website_pages_worker import USER, pipeline, source  # noqa: F401

EDITOR = "editor-1"


@pytest.fixture
def heard(monkeypatch):
    """``(recipient, event type)`` of every event published."""
    from docsgpt import worker

    events = []
    monkeypatch.setattr(
        worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((user, kind, payload)),
    )
    return events


def _recipients(events, kind):
    return sorted(user for user, event_kind, _payload in events if event_kind == kind)


@pytest.mark.unit
class TestWebsitePages:
    def test_every_event_goes_to_the_owner_and_the_editor(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, heard,  # noqa: F811
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(
            task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"], actor_id=EDITOR,
        )

        assert _recipients(heard, "source.ingest.queued") == sorted([USER, EDITOR])
        assert _recipients(heard, "source.ingest.completed") == sorted([USER, EDITOR])

    def test_a_failure_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, heard,  # noqa: F811
    ):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(
                task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"], actor_id=EDITOR,
            )

        assert _recipients(heard, "source.ingest.failed") == sorted([USER, EDITOR])

    @pytest.mark.parametrize("actor", [None, USER])
    def test_the_owner_alone_hears_it_once(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, heard, actor,  # noqa: F811
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(
            task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"], actor_id=actor,
        )

        assert {user for user, _kind, _payload in heard} == {USER}
        assert _recipients(heard, "source.ingest.completed") == [USER]


@pytest.mark.unit
class TestReingest:
    def test_a_refused_reingest_goes_to_both(self, pg_conn, patch_worker_db, task_self, heard):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")

        result = worker.reingest_source_worker(task_self, str(src["id"]), USER, actor_id=EDITOR)

        assert result["reason"] == "no_files"
        assert _recipients(heard, "source.ingest.failed") == sorted([USER, EDITOR])

    def test_a_reingest_goes_to_both(self, pg_conn, patch_worker_db, task_self, heard, monkeypatch):
        from docsgpt import worker

        storage = MagicMock(name="storage")
        storage.is_directory.return_value = True
        storage.list_files.return_value = []
        monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
        reader = MagicMock(name="reader")
        reader.load_data.return_value = []
        reader.directory_structure = {}
        reader.file_token_counts = {}
        monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **kw: reader)
        src = SourcesRepository(pg_conn).create(
            "doc-set", user_id=USER, type="local", file_path="inputs/u/doc-set", directory_structure={},
        )

        worker.reingest_source_worker(task_self, str(src["id"]), USER, actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.queued") == sorted([USER, EDITOR])
        assert _recipients(heard, "source.ingest.completed") == sorted([USER, EDITOR])


@pytest.mark.unit
class TestSync:
    def test_a_skipped_sync_goes_to_both(self, pg_conn, patch_worker_db, task_self, heard, monkeypatch):
        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")

        @contextmanager
        def busy(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        monkeypatch.setattr(worker, "source_index_lock", busy)

        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.failed") == sorted([USER, EDITOR])

    def test_a_sync_goes_to_both(self, pg_conn, patch_worker_db, task_self, heard, monkeypatch, tmp_path):
        from docsgpt import worker

        loader = MagicMock(name="remote_loader")
        loader.load_data.return_value = [
            Document(text="page body", extra_info={"file_path": "guide.md", "title": "Guide"}, doc_id="d1"),
        ]
        loader.report = {"pages": 1, "sites": []}
        monkeypatch.setattr(worker.RemoteCreator, "create_loader", lambda name: loader)
        monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: None)
        monkeypatch.setattr(worker, "assert_index_complete", lambda *a, **k: None)
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: {})
        monkeypatch.setattr(worker, "_record_website_report", lambda *a, **k: {})
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
        )

        result = worker.sync(
            task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]),
            directory=str(tmp_path), actor_id=EDITOR,
        )

        assert result == {"status": "success"}
        assert _recipients(heard, "source.ingest.queued") == sorted([USER, EDITOR])
        assert _recipients(heard, "source.ingest.completed") == sorted([USER, EDITOR])


@pytest.mark.unit
class TestTheTasksPassTheActor:
    def test_website_pages(self, monkeypatch):
        from docsgpt import worker
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(worker, "website_pages_worker", lambda *a, **k: seen.append(k) or {"status": "ok"})

        tasks.website_pages.run("src", USER, "add", urls=["https://x.io/a"], actor_id=EDITOR)
        tasks.website_pages.run("src", USER, "add", urls=["https://x.io/a"])

        assert seen[0]["actor_id"] == EDITOR and "actor_id" not in seen[1]

    def test_reingest(self, monkeypatch):
        from docsgpt import worker
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(worker, "reingest_source_worker", lambda *a, **k: seen.append((a[1:], k)) or {})

        tasks.reingest_source_task("src", USER, actor_id=EDITOR)

        assert seen == [(("src", USER), {"actor_id": EDITOR})]

    def test_sync_source(self, monkeypatch):
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(tasks, "sync", lambda *a, **k: seen.append(k) or {})

        tasks.sync_source({}, "Docs", USER, "website", "never", "classic", "src", actor_id=EDITOR)

        assert seen[0]["actor_id"] == EDITOR

    def test_ingest_connector(self, monkeypatch):
        from docsgpt import worker
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(worker, "ingest_connector", lambda *a, **k: seen.append(k) or {})

        tasks.ingest_connector_task.run("job", "dave", "google_drive", actor_id=EDITOR)
        tasks.ingest_connector_task.run("job", "dave", "google_drive")

        assert seen[0]["actor_id"] == EDITOR and "actor_id" not in seen[1]


@pytest.mark.unit
class TestConnector:
    """A team editor's connector re-ingest or Sync now: its events reach the editor too."""

    def _sync(self, worker, task_self, source_id, **kwargs):
        return worker.ingest_connector(
            task_self, "gdrive-folder", "dave", "google_drive", session_token="tok", folder_ids=["root"],
            operation_mode="sync", doc_id=source_id, sync_frequency="daily", **kwargs,
        )

    def test_a_sync_goes_to_both_and_the_embedding_knows_the_editor(
        self, pg_conn, patch_worker_db, task_self, heard, monkeypatch, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker

        embedded = []
        monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: embedded.append(k))
        src = _gdrive_source(pg_conn, {})

        self._sync(worker, task_self, str(src["id"]), actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.queued") == sorted(["dave", EDITOR])
        assert _recipients(heard, "source.ingest.completed") == sorted(["dave", EDITOR])
        assert embedded[0]["actor_id"] == EDITOR

    def test_an_unchanged_sync_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, heard, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker

        _mock_connector_pipeline.sync_fingerprint.return_value = "fp-1"
        src = _gdrive_source(pg_conn, {"sync_fingerprint": worker._connector_sync_fingerprint("fp-1", None)})

        self._sync(worker, task_self, str(src["id"]), actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.completed") == sorted(["dave", EDITOR])

    def test_an_empty_download_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, heard, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker

        _mock_connector_pipeline.download_to_directory.return_value = {"files_downloaded": 0, "empty_result": True}
        src = _gdrive_source(pg_conn, {})

        self._sync(worker, task_self, str(src["id"]), actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.completed") == sorted(["dave", EDITOR])

    def test_a_failure_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, heard, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker

        _mock_connector_pipeline.download_to_directory.side_effect = RuntimeError("drive down")
        src = _gdrive_source(pg_conn, {})

        with pytest.raises(RuntimeError):
            self._sync(worker, task_self, str(src["id"]), actor_id=EDITOR)

        assert _recipients(heard, "source.ingest.failed") == sorted(["dave", EDITOR])

    def test_a_skipped_sync_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, heard, monkeypatch, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = _gdrive_source(pg_conn, {})

        @contextmanager
        def busy(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        monkeypatch.setattr(worker, "source_index_lock", busy)

        assert self._sync(worker, task_self, str(src["id"]), actor_id=EDITOR)["reason"] == "busy"
        assert _recipients(heard, "source.ingest.failed") == sorted(["dave", EDITOR])

    def test_the_owner_alone_hears_it_once(
        self, pg_conn, patch_worker_db, task_self, heard, _mock_connector_pipeline,  # noqa: F811
    ):
        from docsgpt import worker

        src = _gdrive_source(pg_conn, {})

        self._sync(worker, task_self, str(src["id"]))

        assert {user for user, _kind, _payload in heard} == {"dave"}
