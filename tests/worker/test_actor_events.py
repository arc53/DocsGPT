"""A team editor who changes a source they don't own hears its ``source.ingest.*`` events.

The route runs the job as the source's owner and passes the editor as
``actor_id``; each event goes to the owner and to the editor. The connector
and Website page cases live with their workers' tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "u-owner"
EDITOR = "editor-1"


@pytest.mark.unit
class TestReingest:
    def test_a_refused_reingest_goes_to_both(self, pg_conn, patch_worker_db, task_self, published):
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")

        result = worker.reingest_source_worker(task_self, str(src["id"]), USER, actor_id=EDITOR)

        assert result["reason"] == "no_files"
        assert published.recipients("source.ingest.failed") == sorted([USER, EDITOR])

    def test_a_reingest_goes_to_both(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
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

        assert published.recipients("source.ingest.queued") == sorted([USER, EDITOR])
        assert published.recipients("source.ingest.completed") == sorted([USER, EDITOR])


@pytest.mark.unit
class TestSync:
    def test_a_skipped_sync_goes_to_both(self, pg_conn, patch_worker_db, task_self, published, busy_lock):
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")
        busy_lock()

        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), actor_id=EDITOR)

        assert published.recipients("source.ingest.failed") == sorted([USER, EDITOR])

    def test_a_sync_goes_to_both(
        self, pg_conn, patch_worker_db, task_self, published, remote_pipeline, monkeypatch, tmp_path,
    ):
        monkeypatch.setattr(worker, "_record_website_report", lambda *a, **k: {})
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
        )

        result = worker.sync(
            task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]),
            directory=str(tmp_path), actor_id=EDITOR,
        )

        assert result == {"status": "success"}
        assert published.recipients("source.ingest.queued") == sorted([USER, EDITOR])
        assert published.recipients("source.ingest.completed") == sorted([USER, EDITOR])
