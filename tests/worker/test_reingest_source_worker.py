"""Smoke test for ``docsgpt.worker.reingest_source_worker``.

The task reads a source row, diffs its stored ``directory_structure``
against what's currently in storage, updates the vector store, then
writes the refreshed ``directory_structure`` / ``date`` / ``tokens``
back to the ``sources`` row. We assert that last PG update actually
lands on the row for our ephemeral DB.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock

import pytest

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository


@pytest.mark.unit
class TestReingestSourceWorker:
    def test_updates_source_directory_structure_and_tokens(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from docsgpt import worker

        # Seed a source we can re-ingest.
        src = SourcesRepository(pg_conn).create(
            "doc-set",
            user_id="alice",
            type="local",
            retriever="classic",
            file_path="inputs/alice/doc-set",
            directory_structure={
                "stale.txt": {
                    "type": "text/plain",
                    "size_bytes": 10,
                    "token_count": 5,
                }
            },
        )
        source_id = str(src["id"])

        # Storage: pretend the source directory has one file now, a
        # different one from what the source row last stored — that way
        # the "added/removed" branch runs end-to-end.
        fake_storage = MagicMock(name="storage")
        fake_storage.is_directory.return_value = True
        fake_storage.list_files.return_value = []
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )

        # Reader: return no docs but advertise the new directory shape and
        # per-file token counts. The worker's update statement uses
        # ``sum(reader.file_token_counts.values())`` and the ``
        # directory_structure`` as-is.
        fake_reader = MagicMock(name="reader")
        fake_reader.load_data.return_value = []
        fake_reader.directory_structure = {
            "fresh.md": {
                "type": "text/markdown",
                "size_bytes": 42,
                "token_count": 17,
            }
        }
        fake_reader.file_token_counts = {"fresh.md": 17}
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
        )

        # Vector store: report no existing chunks, and swallow any add/
        # delete call.
        fake_store = MagicMock(name="vector_store")
        fake_store.get_chunks.return_value = []
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore",
            lambda *a, **kw: fake_store,
        )

        result = worker.reingest_source_worker(task_self, source_id, "alice")

        assert result["status"] == "completed"
        # ``fresh.md`` is new vs ``stale.txt``, which was removed.
        assert "fresh.md" in result["added_files"]
        assert "stale.txt" in result["removed_files"]

        refreshed = SourcesRepository(pg_conn).get(source_id, "alice")
        assert refreshed is not None
        # Token count was recomputed from the reader.
        assert refreshed["tokens"] == "17"
        # And the new directory_structure replaced the stale one.
        assert "fresh.md" in refreshed["directory_structure"]
        assert "stale.txt" not in refreshed["directory_structure"]

    def test_reingest_threads_source_chunking_config(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        """The source's stored ``config.chunking`` must drive re-chunking.

        Seeds a source with a non-default chunking config and an added file,
        then asserts ``ChunkerCreator.create_chunker`` is built with that
        config — not the 1250/150 classic defaults (D1/D8).
        """
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "doc-set",
            user_id="alice",
            type="local",
            retriever="classic",
            file_path="inputs/alice/doc-set",
            config={
                "chunking": {
                    "strategy": "recursive",
                    "max_tokens": 800,
                    "min_tokens": 50,
                }
            },
            directory_structure={},
        )
        source_id = str(src["id"])

        # Storage: one file in the source directory, downloaded to temp_dir so
        # the worker's added-files branch finds it on disk and chunks it.
        fake_storage = MagicMock(name="storage")
        fake_storage.is_directory.side_effect = lambda p: p == "inputs/alice/doc-set"
        fake_storage.list_files.return_value = ["inputs/alice/doc-set/fresh.md"]
        fake_storage.get_file.return_value = BytesIO(b"fresh body")
        monkeypatch.setattr(
            worker.StorageCreator, "get_storage", lambda: fake_storage
        )

        # Reader: advertise the new file and hand back one doc to chunk.
        fake_reader = MagicMock(name="reader")
        fake_reader.load_data.return_value = [
            Document(text="fresh body", extra_info={"source": "fresh.md"})
        ]
        fake_reader.directory_structure = {
            "fresh.md": {
                "type": "text/markdown",
                "size_bytes": 10,
                "token_count": 3,
            }
        }
        fake_reader.file_token_counts = {"fresh.md": 3}
        monkeypatch.setattr(
            worker, "SimpleDirectoryReader", lambda *a, **kw: fake_reader
        )

        fake_store = MagicMock(name="vector_store")
        fake_store.get_chunks.return_value = []
        monkeypatch.setattr(
            "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore",
            lambda *a, **kw: fake_store,
        )

        calls: list[dict] = []

        def _create_chunker(strategy, **kwargs):
            calls.append({"strategy": strategy, **kwargs})
            chunker = MagicMock(name="chunker")
            chunker.chunk.side_effect = lambda documents: documents
            return chunker

        monkeypatch.setattr(
            worker.ChunkerCreator,
            "create_chunker",
            staticmethod(_create_chunker),
        )

        result = worker.reingest_source_worker(task_self, source_id, "alice")

        assert result["status"] == "completed"
        assert "fresh.md" in result["added_files"]
        assert len(calls) == 1
        # Config-driven, not the 1250/150 classic defaults.
        assert calls[0]["strategy"] == "recursive"
        assert calls[0]["chunking_strategy"] == "recursive"
        assert calls[0]["max_tokens"] == 800
        assert calls[0]["min_tokens"] == 50


def _local_source(pg_conn):
    return SourcesRepository(pg_conn).create(
        "doc-set", user_id="alice", type="local", retriever="classic",
        file_path="inputs/alice/doc-set", directory_structure={},
    )


@pytest.fixture
def quiet_reingest(monkeypatch):
    """A reingest over an empty directory, with its events recorded."""
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
    events = []
    monkeypatch.setattr(
        worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((kind, payload))
    )
    return {"storage": storage, "events": events}


@pytest.mark.unit
class TestReingestNeedsStoredFiles:
    """A remote source (Website, crawler, connector...) keeps no files; reingest can't read them back."""

    @pytest.mark.parametrize("type_", ["website", "crawler", "connector:file"])
    def test_refused_without_raising(self, pg_conn, patch_worker_db, task_self, quiet_reingest, type_):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id="alice", type=type_,
            remote_data={"entries": [{"url": "https://docs.x.io/a", "mode": "page"}]},
            directory_structure={"a.md": {"type": "text/markdown", "size_bytes": 4, "token_count": 2}},
            tokens="2",
        )
        task_self.request.id = "reingest-1"

        # Returned, not raised: a durable task would retry it three times, then mark the source failed.
        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "no_files"
        [(kind, payload)] = quiet_reingest["events"]
        assert kind == "source.ingest.failed"
        assert payload["reason"] == "no_files" and payload["operation"] == "reingest"
        assert payload["task_id"] == "reingest-1" and payload["error"]
        quiet_reingest["storage"].is_directory.assert_not_called()
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        assert list(row["directory_structure"]) == ["a.md"] and row["tokens"] == "2"


@pytest.mark.unit
class TestReingestTakesTheIndexLock:
    def test_reingests_holding_the_lock(self, pg_conn, patch_worker_db, task_self, quiet_reingest, monkeypatch):
        from contextlib import contextmanager

        from docsgpt import worker

        src = _local_source(pg_conn)
        held = []

        @contextmanager
        def fake_lock(source_id, **kwargs):
            held.append(source_id)
            yield
            held.append("released")

        monkeypatch.setattr(worker, "source_index_lock", fake_lock)
        quiet_reingest["storage"].is_directory.side_effect = lambda path: held.append("read") or True

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "no_changes"
        assert held[0] == str(src["id"]) and held[-1] == "released" and "read" in held[1:-1]

    def test_a_busy_source_is_skipped(self, pg_conn, patch_worker_db, task_self, quiet_reingest, monkeypatch):
        from contextlib import contextmanager

        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        src = _local_source(pg_conn)

        @contextmanager
        def busy(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        monkeypatch.setattr(worker, "source_index_lock", busy)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "busy"
        assert quiet_reingest["events"][-1][0] == "source.ingest.failed"
        assert quiet_reingest["events"][-1][1]["reason"] == "busy"
        quiet_reingest["storage"].is_directory.assert_not_called()

    def test_a_source_deleted_while_waiting_is_skipped(
        self, pg_conn, patch_worker_db, task_self, quiet_reingest, monkeypatch,
    ):
        from contextlib import contextmanager

        from docsgpt import worker

        src = _local_source(pg_conn)

        @contextmanager
        def deleted_while_waiting(source_id, **kwargs):
            SourcesRepository(pg_conn).delete(str(src["id"]), "alice")
            yield

        monkeypatch.setattr(worker, "source_index_lock", deleted_while_waiting)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "gone"
        assert quiet_reingest["events"][-1][1]["reason"] == "gone"
        quiet_reingest["storage"].is_directory.assert_not_called()


@pytest.mark.unit
class TestReingestRefusesAWiki:
    """An upload converted to a wiki keeps its files; a reingest would swap the wiki's pages for them."""

    def _wiki(self, pg_conn):
        return SourcesRepository(pg_conn).create(
            "handbook", user_id="alice", type="local", retriever="classic",
            file_path="inputs/alice/handbook", config={"kind": "wiki"},
            directory_structure={
                "report.md": {"type": "text/markdown", "size_bytes": 10, "token_count": 5},
                "notes.md": {"type": "text/markdown", "size_bytes": 10, "token_count": 5},
            },
            tokens="10",
        )

    def test_a_wiki_is_refused(self, pg_conn, patch_worker_db, task_self, quiet_reingest):
        from docsgpt import worker

        src = self._wiki(pg_conn)
        task_self.request.id = "reingest-wiki"

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "wiki"
        kind, payload = quiet_reingest["events"][-1]
        assert kind == "source.ingest.failed"
        assert payload["reason"] == "wiki" and payload["operation"] == "reingest" and payload["error"]
        assert payload["task_id"] == "reingest-wiki"
        quiet_reingest["storage"].is_directory.assert_not_called()
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        assert sorted(row["directory_structure"]) == ["notes.md", "report.md"] and row["tokens"] == "10"

    def test_a_conversion_that_finished_while_waiting_is_refused(
        self, pg_conn, patch_worker_db, task_self, quiet_reingest, monkeypatch,
    ):
        from contextlib import contextmanager

        from docsgpt import worker

        src = _local_source(pg_conn)

        @contextmanager
        def converted_while_waiting(source_id, **kwargs):
            SourcesRepository(pg_conn).update(str(src["id"]), "alice", {"config": {"kind": "wiki"}})
            yield

        monkeypatch.setattr(worker, "source_index_lock", converted_while_waiting)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "wiki"
        assert quiet_reingest["events"][-1][1]["reason"] == "wiki"
        quiet_reingest["storage"].is_directory.assert_not_called()
