"""A sync changes a source's content, never the settings it was queued with.

``sync`` is queued with a snapshot (remote_data, sync_frequency, config); it
re-reads the row under the index lock and crawls what the row holds then.
Anything changed while it ran (a config edit, saved skip rules, a schedule
change, a wiki conversion) must survive its final write, and a source
deleted meanwhile is never re-created. Two jobs on one source's index take
turns through ``source_index_lock``. A skipped sync tells the UI why.
"""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "sam"
# A syncable Website config: a sync crawls the row's own remote_data.
SITE = {"entries": [{"url": "https://x.io/", "mode": "site"}]}


@pytest.mark.unit
class TestSyncWrite:
    def test_a_sync_sends_content_only(self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline):
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
        [sent] = remote_pipeline.uploads
        assert sent["operation"] == "sync"
        # Chunked with the stored config, but never written back from the snapshot.
        assert "config" not in sent
        assert json.loads(sent["directory_structure"])["guide.md"]["token_count"] >= 1

    def test_a_syncs_events_carry_its_task_id(
        self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline, published,
    ):
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website", remote_data=SITE)
        task_self.request.id = "sync-task-1"
        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), directory=str(tmp_path))

        assert published.kinds() == ["source.ingest.queued", "source.ingest.completed"]
        assert all(payload["task_id"] == "sync-task-1" for _, payload in published)

    def test_a_sync_holds_the_source_index_lock(
        self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline, held_lock, monkeypatch,
    ):
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website", remote_data=SITE)
        monkeypatch.setattr(worker, "upload_index", lambda full_path, file_data: held_lock.append("upload"))
        worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]), directory=str(tmp_path))

        assert held_lock == [str(src["id"]), "upload", "released"]

    def test_a_scheduled_sync_skips_a_busy_source_quietly(
        self, pg_conn, patch_worker_db, task_self, monkeypatch, busy_lock, published,
    ):
        SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", sync_frequency="daily",
            remote_data={"entries": [{"url": "https://x.io/", "mode": "page"}]},
        )
        waits = busy_lock()
        remote = MagicMock(name="remote_worker")
        monkeypatch.setattr(worker, "remote_worker", remote)
        counts = worker.sync_worker(task_self, "daily")

        # The beat run doesn't wait on a long job, and nobody waits on it:
        # the next schedule picks the source up, without a notice.
        assert waits == [0]
        assert counts["sync_skipped"] == 1 and counts["sync_failure"] == 0
        remote.assert_not_called()
        assert published == []


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


@pytest.mark.unit
class TestSyncReadsTheRow:
    """A queued sync crawls the source as it is when the sync starts, not as it was queued."""

    def test_crawls_the_rows_current_remote_data(self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline):
        # Since the sync was queued, a page was removed (its skip rule saved) and the source renamed.
        current = {"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": ["https://x.io/secret"]}
        src = SourcesRepository(pg_conn).create("Renamed", user_id=USER, type="website", remote_data=current)
        queued = {"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": []}

        result = worker.sync(task_self, queued, "Docs", USER, "website", "never", "classic", str(src["id"]),
                             directory=str(tmp_path))

        assert result == {"status": "success"}
        crawled = remote_pipeline.loader.load_data.call_args.args[0]
        assert crawled["skip"] == ["https://x.io/secret"]
        assert remote_pipeline.uploads[-1]["name"] == "Renamed"

    def test_a_legacy_source_converted_meanwhile_syncs_as_a_website(
        self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline, monkeypatch,
    ):
        loaders = []
        loader = remote_pipeline.loader
        monkeypatch.setattr(worker.RemoteCreator, "create_loader", lambda name: (loaders.append(name), loader)[1])
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://x.io/a", "mode": "page"}]},
        )

        worker.sync(task_self, "https://x.io/a", "Docs", USER, "url", "never", "classic", str(src["id"]),
                    directory=str(tmp_path))

        assert loaders == ["website"]
        assert loader.load_data.call_args.args[0]["entries"][0]["url"] == "https://x.io/a"

    def test_does_not_run_when_the_row_cant_be_read(
        self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline, published, monkeypatch,
    ):
        """The queued snapshot has no config and can't tell a wiki: rebuilding from it could lose both."""

        @contextmanager
        def broken():
            raise RuntimeError("database unavailable")
            yield

        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")
        monkeypatch.setattr(worker, "db_readonly", broken)
        queued = {"entries": [{"url": "https://x.io/", "mode": "site"}], "skip": []}

        result = worker.sync(task_self, queued, "Docs", USER, "website", "never", "classic", str(src["id"]),
                             directory=str(tmp_path))

        assert result["status"] == "error"
        remote_pipeline.loader.load_data.assert_not_called()
        assert remote_pipeline.uploads == []
        [(kind, payload)] = published
        assert kind == "source.ingest.failed" and payload["source_id"] == str(src["id"])

    def test_a_deleted_source_is_skipped_and_never_embedded(
        self, pg_conn, patch_worker_db, task_self, tmp_path, remote_pipeline, published, monkeypatch,
    ):
        embedded = []
        monkeypatch.setattr(worker, "embed_and_store_documents", lambda *a, **k: embedded.append(1))
        task_self.request.id = "sync-gone"
        gone = str(uuid.uuid4())

        result = worker.sync(task_self, {"entries": [{"url": "https://x.io/", "mode": "site"}]}, "Docs", USER,
                             "website", "daily", "classic", gone, directory=str(tmp_path))

        assert result == {"status": "skipped", "reason": "gone"}
        assert embedded == [] and remote_pipeline.uploads == []
        [(kind, payload)] = published
        assert kind == "source.ingest.failed"
        assert payload["reason"] == "gone" and payload["task_id"] == "sync-gone"
        assert payload["source_id"] == gone and payload["operation"] == "sync"


@pytest.mark.unit
class TestASkippedSyncTellsTheUI:
    def test_a_busy_source_publishes_a_failed_event(self, pg_conn, patch_worker_db, task_self, busy_lock, published):
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website")
        busy_lock()
        task_self.request.id = "sync-busy"

        result = worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]))

        assert result == {"status": "skipped", "reason": "busy"}
        [(kind, payload)] = published
        assert kind == "source.ingest.failed"
        assert payload == {
            "source_id": str(src["id"]), "job_name": "Docs", "loader": "website", "operation": "sync",
            "error": payload["error"], "reason": "busy", "task_id": "sync-busy",
        }
        assert payload["error"]

    def test_a_wiki_publishes_a_failed_event(self, pg_conn, patch_worker_db, task_self, published, monkeypatch):
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", remote_data=SITE, config={"kind": "wiki"},
        )
        remote = MagicMock(name="remote_worker")
        monkeypatch.setattr(worker, "remote_worker", remote)

        result = worker.sync(task_self, {}, "Docs", USER, "website", "never", "classic", str(src["id"]))

        assert result == {"status": "skipped", "reason": "wiki"}
        assert [(kind, payload["reason"]) for kind, payload in published] == [("source.ingest.failed", "wiki")]
        remote.assert_not_called()


@pytest.fixture
def refused_upload(monkeypatch, remote_pipeline, published):
    """A sync whose upload the API refuses, with what it does afterwards recorded."""
    from docsgpt.vectorstore import vector_creator

    store = MagicMock(name="vector_store")
    monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)
    remote_pipeline.answer = {"status": "skipped", "reason": "gone"}
    after = {"pipeline": remote_pipeline, "events": published, "graph": [], "reports": [], "store": store}
    monkeypatch.setattr(worker, "_maybe_enqueue_graph_extraction", lambda *a, **k: after["graph"].append(a))
    monkeypatch.setattr(worker, "_record_website_report", lambda *a, **k: after["reports"].append(a) or {})
    return after


@pytest.mark.unit
class TestARefusedSyncUploadIsNotCompleted:
    """The API answers 200 ``skipped`` when the source was deleted, or became a wiki, while the sync ran."""

    def _run(self, task_self, src, tmp_path):
        task_self.request.id = "sync-refused"
        return worker.sync(task_self, {}, "Docs", USER, "website", "daily", "classic", str(src["id"]),
                           directory=str(tmp_path))

    def test_a_deleted_source_fails_with_gone_and_drops_its_vectors(
        self, pg_conn, patch_worker_db, task_self, tmp_path, refused_upload, monkeypatch,
    ):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website", remote_data=SITE)

        result = self._run(task_self, src, tmp_path)

        assert result == {"status": "skipped", "reason": "gone"}
        assert refused_upload["events"].kinds() == ["source.ingest.queued", "source.ingest.failed"]
        failed = refused_upload["events"][-1][1]
        assert failed["reason"] == "gone" and failed["task_id"] == "sync-refused"
        assert failed["operation"] == "sync" and failed["error"]
        # The sync re-filled the index under the deleted id; nothing else would clear it.
        refused_upload["store"].delete_index.assert_called_once()
        assert refused_upload["graph"] == [] and refused_upload["reports"] == []

    def test_a_wiki_keeps_its_vectors(self, pg_conn, patch_worker_db, task_self, tmp_path, refused_upload,
                                      monkeypatch):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        refused_upload["pipeline"].answer = {"status": "skipped", "reason": "wiki"}
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website", remote_data=SITE)

        result = self._run(task_self, src, tmp_path)

        assert result == {"status": "skipped", "reason": "wiki"}
        assert [(kind, payload.get("reason")) for kind, payload in refused_upload["events"]][-1] == (
            "source.ingest.failed", "wiki",
        )
        refused_upload["store"].delete_index.assert_not_called()
        assert refused_upload["graph"] == []

    def test_faiss_has_no_vectors_to_drop(self, pg_conn, patch_worker_db, task_self, tmp_path, refused_upload,
                                          monkeypatch):
        from docsgpt.core.settings import settings

        # The API refused before saving the files: the index only ever lived in the scratch directory.
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        src = SourcesRepository(pg_conn).create("Docs", user_id=USER, type="website", remote_data=SITE)

        assert self._run(task_self, src, tmp_path) == {"status": "skipped", "reason": "gone"}
        refused_upload["store"].delete_index.assert_not_called()

    def test_upload_index_returns_the_apis_answer(self, monkeypatch, tmp_path):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        answer = MagicMock(status_code=200)
        answer.json.return_value = {"status": "skipped", "reason": "gone"}
        monkeypatch.setattr(worker.requests, "post", lambda *a, **k: answer)

        assert worker.upload_index(str(tmp_path), {"id": "s"}) == {"status": "skipped", "reason": "gone"}

    def test_upload_index_tolerates_a_body_that_is_not_json(self, monkeypatch, tmp_path):
        from docsgpt.core.settings import settings

        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        answer = MagicMock(status_code=200)
        answer.json.side_effect = ValueError("no json")
        monkeypatch.setattr(worker.requests, "post", lambda *a, **k: answer)

        assert worker.upload_index(str(tmp_path), {"id": "s"}) == {}


@pytest.mark.unit
class TestUploadIndexForAConnectorSync:
    def _seed(self, pg_conn, **fields):
        values = {
            "type": "connector:file", "sync_frequency": "daily",
            "remote_data": {"provider": "google_drive", "folder_ids": ["picked-meanwhile"], "sync_fingerprint": "old"},
            "config": {"kind": "wiki"}, "directory_structure": {"/page.md": {"token_count": 1}},
        }
        values.update(fields)
        return SourcesRepository(pg_conn).create("Drive", user_id=USER, **values)

    def _form(self, src, **extra):
        return {
            "user": USER, "name": "Drive", "tokens": "9", "retriever": "classic", "id": str(src["id"]),
            "type": "connector:file", "sync_frequency": "never", "operation": "sync",
            "remote_data": json.dumps({"provider": "google_drive", "folder_ids": ["root"], "sync_fingerprint": "new"}),
            "directory_structure": json.dumps({"drive.pdf": {"token_count": 9}}), **extra,
        }

    def test_a_wiki_converted_meanwhile_is_kept(self, pg_conn):
        src = self._seed(pg_conn)

        response = _post(pg_conn, self._form(src, sync_fingerprint="new"))

        assert response.json == {"status": "skipped", "reason": "wiki"}
        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert row["config"]["kind"] == "wiki" and row["directory_structure"] == {"/page.md": {"token_count": 1}}

    def test_stores_the_fingerprint_on_the_rows_selection(self, pg_conn):
        src = self._seed(pg_conn, config={"chunking": {"max_tokens": 300}})

        _post(pg_conn, self._form(src, sync_fingerprint="new"))

        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert row["remote_data"] == {"provider": "google_drive", "folder_ids": ["picked-meanwhile"],
                                      "sync_fingerprint": "new"}
        assert row["sync_frequency"] == "daily" and row["config"]["chunking"]["max_tokens"] == 300
        assert row["directory_structure"] == {"drive.pdf": {"token_count": 9}}

    def test_an_empty_fingerprint_clears_it(self, pg_conn):
        src = self._seed(pg_conn, config={})

        _post(pg_conn, self._form(src, sync_fingerprint=""))

        row = SourcesRepository(pg_conn).get(str(src["id"]), USER)
        assert "sync_fingerprint" not in row["remote_data"]


@pytest.mark.unit
class TestUploadIndexSavesFilesOutsideTheRowLock:
    """The FAISS files are saved between two short row locks, never while one is held."""

    def _seed(self, pg_conn):
        return SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website", remote_data=SITE, sync_frequency="weekly",
            directory_structure={"old.md": {"token_count": 1}},
        )

    def _form(self, src, **extra):
        import io

        from docsgpt.vectorstore.faiss_docstore import dump_pickle_sidecar

        pickle_bytes = dump_pickle_sidecar({}, {})
        return {
            "user": USER, "name": "Docs", "tokens": "5", "retriever": "classic", "id": str(src["id"]),
            "type": "website", "sync_frequency": "weekly", "remote_data": json.dumps(SITE),
            "directory_structure": json.dumps({"new.md": {"token_count": 5}}),
            "file_faiss": (io.BytesIO(b"faiss"), "index.faiss"), "file_pkl": (io.BytesIO(pickle_bytes), "index.pkl"),
            **extra,
        }

    def _post_recording(self, pg_conn, form, on_save=None):
        from unittest.mock import patch

        from flask import Flask

        from docsgpt.api.internal.routes import internal

        events = []

        @contextmanager
        def recording_session():
            events.append("begin")
            yield pg_conn
            events.append("commit")

        storage = MagicMock()

        def save(file, path):
            events.append("save")
            if on_save:
                on_save()

        storage.save_file.side_effect = save
        app = Flask(__name__)
        app.register_blueprint(internal)
        with patch("docsgpt.api.internal.routes.settings.INTERNAL_KEY", "k"), patch(
            "docsgpt.api.internal.routes.settings.VECTOR_STORE", "faiss"
        ), patch("docsgpt.api.internal.routes.StorageCreator.get_storage", return_value=storage), patch(
            "docsgpt.api.internal.routes.db_session", recording_session
        ):
            response = app.test_client().post("/api/upload_index", headers={"X-Internal-Key": "k"}, data=form)
        return response, events

    @pytest.mark.parametrize("operation", ["sync", None])
    def test_no_transaction_is_open_while_the_files_are_saved(self, pg_conn, operation):
        src = self._seed(pg_conn)
        form = self._form(src, **({"operation": operation} if operation else {}))

        response, events = self._post_recording(pg_conn, form)

        assert response.json == {"status": "ok"}
        saves = [i for i, event in enumerate(events) if event == "save"]
        assert len(saves) == 3  # index.faiss, index.pkl and the index.json built from it
        opened = 0
        for i, event in enumerate(events):
            opened += {"begin": 1, "commit": -1}.get(event, 0)
            if i in saves:
                assert opened == 0
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["directory_structure"] == {
            "new.md": {"token_count": 5}
        }

    def test_a_wiki_conversion_during_the_save_keeps_the_rows_fields(self, pg_conn):
        src = self._seed(pg_conn)

        def convert():
            SourcesRepository(pg_conn).update(str(src["id"]), USER, {"config": {"kind": "wiki"}})

        response, _events = self._post_recording(pg_conn, self._form(src, operation="sync"), on_save=convert)

        assert response.json == {"status": "skipped", "reason": "wiki"}
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER)["directory_structure"] == {
            "old.md": {"token_count": 1}
        }

    def test_a_source_deleted_during_the_save_is_not_recreated(self, pg_conn):
        src = self._seed(pg_conn)

        def delete():
            SourcesRepository(pg_conn).delete(str(src["id"]), USER)

        response, _events = self._post_recording(pg_conn, self._form(src, operation="sync"), on_save=delete)

        assert response.json == {"status": "skipped", "reason": "gone"}
        assert SourcesRepository(pg_conn).get(str(src["id"]), USER) is None


@pytest.mark.unit
class TestUploadIndexForADeletedSource:
    def test_a_sync_never_recreates_a_deleted_source(self, pg_conn):
        import uuid

        sid = str(uuid.uuid4())
        form = {
            "user": USER, "name": "Gone", "tokens": "5", "retriever": "classic", "id": sid, "type": "website",
            "remote_data": json.dumps({"entries": [{"url": "https://x.io/", "mode": "site"}]}),
            "sync_frequency": "weekly", "directory_structure": json.dumps({"a.md": {"token_count": 5}}),
            "operation": "sync",
        }
        storage = MagicMock()

        response = _post(pg_conn, form, storage=storage)

        assert response.json == {"status": "skipped", "reason": "gone"}
        assert SourcesRepository(pg_conn).get(sid, USER) is None
        storage.save_file.assert_not_called()
