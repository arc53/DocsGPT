"""A sync changes a source's content, never the settings it was queued with.

``sync`` hands ``remote_worker`` a snapshot (remote_data, sync_frequency,
config) taken when it was queued. Anything changed while it ran (a config
edit, saved skip rules, a schedule change, a wiki conversion) must survive
its final write. The same goes for two jobs on one source's index: they take
turns through ``source_index_lock``.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "sam"


@pytest.fixture
def uploads(monkeypatch):
    from docsgpt import worker

    loader = MagicMock(name="remote_loader")
    loader.load_data.return_value = [
        Document(text="page body", extra_info={"file_path": "guide.md", "title": "Guide"}, doc_id="d1"),
    ]
    monkeypatch.setattr(worker.RemoteCreator, "create_loader", lambda name: loader)
    monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: None)
    monkeypatch.setattr(worker, "assert_index_complete", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: sent.append(file_data))
    return sent


@pytest.mark.unit
class TestSyncWrite:
    def test_a_sync_sends_content_only(self, pg_conn, patch_worker_db, task_self, tmp_path, uploads):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", sync_frequency="weekly",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "site"}]},
            config={"chunking": {"max_tokens": 400}},
        )
        result = worker.sync(
            task_self, {"entries": [{"url": "https://x.io/", "mode": "site"}]}, "Docs", USER, "website",
            "weekly", "classic", str(src["id"]), directory=str(tmp_path),
        )

        assert result == {"status": "success"}
        [sent] = uploads
        assert sent["operation"] == "sync"
        # Chunked with the stored config, but never written back from the snapshot.
        assert "config" not in sent
        assert json.loads(sent["directory_structure"])["guide.md"]["token_count"] >= 1

    def test_a_syncs_events_carry_its_task_id(
        self, pg_conn, patch_worker_db, task_self, tmp_path, uploads, monkeypatch,
    ):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")
        events = []
        monkeypatch.setattr(
            worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((kind, payload))
        )
        task_self.request.id = "sync-task-1"
        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), directory=str(tmp_path))

        assert [kind for kind, _ in events] == ["source.ingest.queued", "source.ingest.completed"]
        assert all(payload["task_id"] == "sync-task-1" for _, payload in events)

    def test_a_sync_holds_the_source_index_lock(
        self, pg_conn, patch_worker_db, task_self, tmp_path, uploads, monkeypatch,
    ):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")
        held = []

        @contextmanager
        def fake_lock(source_id, **kwargs):
            held.append(source_id)
            yield
            held.append("released")

        monkeypatch.setattr(worker, "source_index_lock", fake_lock)
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: held.append("upload"))
        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), directory=str(tmp_path))

        assert held == [str(src["id"]), "upload", "released"]

    def test_a_busy_source_is_skipped_by_a_scheduled_sync(
        self, pg_conn, patch_worker_db, task_self, monkeypatch,
    ):
        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", sync_frequency="daily",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "page"}]},
        )
        waits = []

        @contextmanager
        def busy(source_id, wait_seconds=None, **kwargs):
            waits.append(wait_seconds)
            raise SourceBusy("busy")
            yield

        remote = MagicMock(name="remote_worker")
        monkeypatch.setattr(worker, "source_index_lock", busy)
        monkeypatch.setattr(worker, "remote_worker", remote)
        counts = worker.sync_worker(task_self, "daily")

        # The beat run doesn't wait on a long job: the next schedule picks it up.
        assert waits == [0]
        assert counts["sync_skipped"] == 1 and counts["sync_failure"] == 0
        remote.assert_not_called()


@contextmanager
def _patch_db(conn):
    @contextmanager
    def _yield():
        yield conn

    from unittest.mock import patch

    with patch("docsgpt.api.internal.routes.db_session", _yield):
        yield


def _post(pg_conn, form, vector_store="milvus", storage=None):
    from unittest.mock import patch

    from flask import Flask

    from docsgpt.api.internal.routes import internal

    app = Flask(__name__)
    app.register_blueprint(internal)
    storage = storage or MagicMock()
    with patch("docsgpt.api.internal.routes.settings.INTERNAL_KEY", "k"), patch(
        "docsgpt.api.internal.routes.settings.VECTOR_STORE", vector_store
    ), patch("docsgpt.api.internal.routes.settings.EMBEDDINGS_NAME", "emb"), patch(
        "docsgpt.api.internal.routes.StorageCreator.get_storage", return_value=storage
    ), _patch_db(pg_conn):
        with app.test_client() as client:
            return client.post("/api/upload_index", headers={"X-Internal-Key": "k"}, data=form)


@pytest.mark.unit
class TestUploadIndexForASync:
    def _seed(self, pg_conn, **fields):
        values = {
            "type": "website",
            "remote_data": {"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": ["https://x.io/old"]},
            "sync_frequency": "monthly",
            "config": {"chunking": {"max_tokens": 300}},
            "directory_structure": {"old.md": {"token_count": 1}},
            "tokens": "1",
        }
        values.update(fields)
        return SourcesRepository(pg_conn).create("Renamed meanwhile", user_id=USER, **values)

    def _form(self, src, **extra):
        return {
            "user": USER,
            "name": "Queued name",
            "tokens": "50",
            "retriever": "classic",
            "id": str(src["id"]),
            "type": "crawler",
            "remote_data": json.dumps({"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": []}),
            "sync_frequency": "weekly",
            "directory_structure": json.dumps({"guide.md": {"token_count": 50}}),
            "config": json.dumps({"chunking": {"max_tokens": 900}}),
            "operation": "sync",
            **extra,
        }

    def test_keeps_the_rows_current_settings(self, pg_conn):
        src = self._seed(pg_conn)
        response = _post(pg_conn, self._form(src))

        assert response.json == {"status": "ok"}
        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert row["directory_structure"] == {"guide.md": {"token_count": 50}}
        assert row["tokens"] == "50"
        assert row["name"] == "Renamed meanwhile"
        assert row["type"] == "website"
        assert row["sync_frequency"] == "monthly"
        assert row["remote_data"]["skip"] == ["https://x.io/old"]
        assert row["config"]["chunking"]["max_tokens"] == 300

    def test_a_wiki_is_not_overwritten(self, pg_conn):
        import io

        src = self._seed(pg_conn, config={"kind": "wiki"})
        storage = MagicMock()
        form = self._form(
            src, file_faiss=(io.BytesIO(b"faiss"), "index.faiss"), file_pkl=(io.BytesIO(b"pkl"), "index.pkl"),
        )
        response = _post(pg_conn, form, vector_store="faiss", storage=storage)

        assert response.json == {"status": "skipped", "reason": "wiki"}
        storage.save_file.assert_not_called()
        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert row["directory_structure"] == {"old.md": {"token_count": 1}}

    def test_an_upload_still_writes_everything(self, pg_conn):
        src = self._seed(pg_conn)
        form = self._form(src)
        form.pop("operation")
        _post(pg_conn, form)

        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert row["name"] == "Queued name"
        assert row["sync_frequency"] == "weekly"
        assert row["config"]["chunking"]["max_tokens"] == 900
