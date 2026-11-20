"""Smoke test for ``docsgpt.worker.reingest_source_worker``.

The task reads a source row, diffs its stored ``directory_structure``
against what's currently in storage, updates the vector store, then
writes the refreshed ``directory_structure`` / ``date`` / ``tokens``
back to the ``sources`` row. We assert that last PG update actually
lands on the row for our ephemeral DB.
"""

from __future__ import annotations

import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from docsgpt import worker
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
        assert calls[0]["chunk_overlap"] == 0


def _local_source(pg_conn):
    return SourcesRepository(pg_conn).create(
        "doc-set", user_id="alice", type="local", retriever="classic",
        file_path="inputs/alice/doc-set", directory_structure={},
    )


@pytest.fixture
def quiet_reingest(monkeypatch, published):
    """A reingest over an empty directory, with its events recorded."""
    storage = MagicMock(name="storage")
    storage.is_directory.return_value = True
    storage.list_files.return_value = []
    monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
    reader = MagicMock(name="reader")
    reader.load_data.return_value = []
    reader.directory_structure = {}
    reader.file_token_counts = {}
    monkeypatch.setattr(worker, "SimpleDirectoryReader", lambda *a, **kw: reader)
    return {"storage": storage, "events": published}


@pytest.mark.unit
class TestReingestNeedsStoredFiles:
    """A remote source (Website, crawler, connector...) keeps no files; reingest can't read them back."""

    @pytest.mark.parametrize("type_", ["website", "crawler", "connector:file"])
    def test_refused_without_raising(self, pg_conn, patch_worker_db, task_self, quiet_reingest, type_):
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
    def test_reingests_holding_the_lock(self, pg_conn, patch_worker_db, task_self, quiet_reingest, held_lock):
        src = _local_source(pg_conn)
        quiet_reingest["storage"].is_directory.side_effect = lambda path: held_lock.append("read") or True

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "no_changes"
        assert held_lock[0] == str(src["id"]) and held_lock[-1] == "released" and "read" in held_lock[1:-1]

    def test_a_busy_source_is_skipped(self, pg_conn, patch_worker_db, task_self, quiet_reingest, busy_lock):
        src = _local_source(pg_conn)
        busy_lock()

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "busy"
        assert quiet_reingest["events"][-1][0] == "source.ingest.failed"
        assert quiet_reingest["events"][-1][1]["reason"] == "busy"
        quiet_reingest["storage"].is_directory.assert_not_called()

    def test_a_source_deleted_while_waiting_is_skipped(
        self, pg_conn, patch_worker_db, task_self, quiet_reingest, held_lock,
    ):
        src = _local_source(pg_conn)
        held_lock.while_waiting.append(lambda: SourcesRepository(pg_conn).delete(str(src["id"]), "alice"))

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
        self, pg_conn, patch_worker_db, task_self, quiet_reingest, held_lock,
    ):
        src = _local_source(pg_conn)
        held_lock.while_waiting.append(
            lambda: SourcesRepository(pg_conn).update(str(src["id"]), "alice", {"config": {"kind": "wiki"}})
        )

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "skipped" and result["reason"] == "wiki"
        assert quiet_reingest["events"][-1][1]["reason"] == "wiki"
        quiet_reingest["storage"].is_directory.assert_not_called()


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def stored_files(monkeypatch):
    """Storage holding ``files`` (relative path → bytes) under ``inputs/alice/doc-set``, read by the real reader."""
    root = "inputs/alice/doc-set"
    files: dict[str, bytes] = {}
    storage = MagicMock(name="storage")
    storage.is_directory.side_effect = lambda path: path == root
    storage.list_files.side_effect = lambda path: [f"{root}/{rel}" for rel in files]
    storage.get_file.side_effect = lambda path: BytesIO(files[path[len(root) + 1:]])
    monkeypatch.setattr(worker.StorageCreator, "get_storage", lambda: storage)
    return files


@pytest.fixture
def chunk_store(monkeypatch):
    """A vector store whose chunks are a list of ``{"doc_id", "text", "metadata"}``."""
    chunks: list[dict] = []
    store = MagicMock(name="vector_store")
    store.get_chunks.side_effect = lambda: list(chunks)

    def add_chunk(text, metadata=None):
        chunks.append({"doc_id": f"c{len(chunks)}-{metadata.get('source')}", "text": text, "metadata": metadata})

    store.add_chunk.side_effect = add_chunk
    store.delete_chunk.side_effect = lambda cid: chunks.remove(next(c for c in chunks if c["doc_id"] == cid))
    monkeypatch.setattr(
        "docsgpt.vectorstore.vector_creator.VectorCreator.create_vectorstore", lambda *a, **kw: store,
    )
    return chunks


def _hashed_source(pg_conn, files: dict[str, bytes], **structure_overrides):
    structure = {
        name: {"type": "text/markdown", "size_bytes": len(data), "token_count": 1, "sha256": _sha(data)}
        for name, data in files.items()
    }
    for name, entry in structure_overrides.items():
        structure[name] = entry
    return SourcesRepository(pg_conn).create(
        "doc-set", user_id="alice", type="local", retriever="classic",
        file_path="inputs/alice/doc-set", directory_structure=structure,
    )


@pytest.mark.unit
class TestReingestDetectsEditedFiles:
    """An edited file keeps its path; only its content hash says it changed."""

    def test_unchanged_files_embed_nothing(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        stored_files.update({"a.md": b"alpha", "b.md": b"beta"})
        src = _hashed_source(pg_conn, dict(stored_files))
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-b", "text": "beta", "metadata": {"source": "b.md"}},
        ])

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "no_changes"
        assert [c["doc_id"] for c in chunk_store] == ["old-a", "old-b"]

    def test_an_edited_file_is_re_embedded_alone(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        src = _hashed_source(pg_conn, {"a.md": b"alpha", "b.md": b"beta"})
        stored_files.update({"a.md": b"alpha, edited", "b.md": b"beta"})
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-b", "text": "beta", "metadata": {"source": "b.md"}},
        ])

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed"
        assert result["modified_files"] == ["a.md"]
        assert result["added_files"] == [] and result["removed_files"] == []
        assert result["chunks_deleted"] == 1 and result["chunks_added"] >= 1
        assert "old-a" not in [c["doc_id"] for c in chunk_store]
        assert "old-b" in [c["doc_id"] for c in chunk_store]
        assert {c["metadata"]["source"] for c in chunk_store} == {"a.md", "b.md"}
        assert any("edited" in c["text"] for c in chunk_store if c["metadata"]["source"] == "a.md")
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        assert row["directory_structure"]["a.md"]["sha256"] == _sha(b"alpha, edited")

    def test_a_file_stored_without_a_hash_counts_as_edited_once(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        stored_files.update({"a.md": b"alpha"})
        src = _hashed_source(pg_conn, {}, **{"a.md": {"type": "text/markdown", "size_bytes": 5, "token_count": 1}})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})

        first = worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert first["status"] == "completed" and first["modified_files"] == ["a.md"]
        assert "old-a" not in [c["doc_id"] for c in chunk_store]
        assert second["status"] == "no_changes"

    def test_added_removed_and_edited_together(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        src = _hashed_source(pg_conn, {"keep.md": b"same", "edit.md": b"v1", "gone.md": b"bye"})
        stored_files.update({"keep.md": b"same", "edit.md": b"v2", "new.md": b"hello"})
        chunk_store.extend([
            {"doc_id": "k", "text": "same", "metadata": {"source": "keep.md"}},
            {"doc_id": "e", "text": "v1", "metadata": {"source": "edit.md"}},
            {"doc_id": "g", "text": "bye", "metadata": {"source": "gone.md"}},
        ])

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert (result["added_files"], result["removed_files"], result["modified_files"]) == (
            ["new.md"], ["gone.md"], ["edit.md"],
        )
        assert result["chunks_deleted"] == 2
        assert sorted({c["metadata"]["source"] for c in chunk_store}) == ["edit.md", "keep.md", "new.md"]
        assert "k" in [c["doc_id"] for c in chunk_store]
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        assert sorted(row["directory_structure"]) == ["edit.md", "keep.md", "new.md"]

    def test_a_chunking_change_re_chunks_every_file_once(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        stored_files.update({"a.md": b"alpha", "b.md": b"beta"})
        src = _hashed_source(pg_conn, dict(stored_files))
        SourcesRepository(pg_conn).set_metadata_key(str(src["id"]), "alice", "rechunk_pending", True)
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-b", "text": "beta", "metadata": {"source": "b.md"}},
        ])

        first = worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert first["status"] == "completed" and first["modified_files"] == ["a.md", "b.md"]
        assert not {"old-a", "old-b"} & {c["doc_id"] for c in chunk_store}
        assert second["status"] == "no_changes"
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        assert "rechunk_pending" not in (row["metadata"] or {})

    def test_a_file_whose_embedding_failed_is_retried_next_time(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store, monkeypatch,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})
        from docsgpt.vectorstore.vector_creator import VectorCreator

        store = VectorCreator.create_vectorstore("faiss", "source")
        real_add = store.add_chunk.side_effect
        store.add_chunk.side_effect = RuntimeError("embedding service down")
        first = worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        store.add_chunk.side_effect = real_add
        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert first["modified_files"] == ["a.md"]
        assert second["status"] == "completed" and second["modified_files"] == ["a.md"]
        assert any("edited" in c["text"] for c in chunk_store if c["metadata"]["source"] == "a.md")

    def test_a_file_that_failed_to_parse_is_retried_next_time(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store, monkeypatch,
    ):
        from docsgpt.parser.file.base_parser import DocumentParseError
        from docsgpt.parser.file.markdown_parser import MarkdownParser

        src = _hashed_source(pg_conn, {"a.md": b"alpha", "b.md": b"beta"})
        # b.md is edited too, so the batch still parses and only a.md fails.
        stored_files.update({"a.md": b"alpha, broken", "b.md": b"beta, edited"})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})
        real_parse = MarkdownParser.parse_file

        def parse(self, file, errors="ignore"):
            if b"broken" in file.read_bytes():
                raise DocumentParseError("cannot read it")
            return real_parse(self, file, errors=errors)

        monkeypatch.setattr(MarkdownParser, "parse_file", parse)
        first = worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        stored_files["a.md"] = b"alpha, fixed"
        monkeypatch.setattr(MarkdownParser, "parse_file", real_parse)
        row = SourcesRepository(pg_conn).get(str(src["id"]), "alice")
        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert first["modified_files"] == ["a.md", "b.md"]
        assert "sha256" not in row["directory_structure"]["a.md"]
        assert row["directory_structure"]["b.md"]["sha256"] == _sha(b"beta, edited")
        assert second["modified_files"] == ["a.md"]
        assert any("fixed" in c["text"] for c in chunk_store if c["metadata"]["source"] == "a.md")

    def test_an_edited_file_is_re_embedded_again_after_a_failed_chunk_deletion(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        from docsgpt.vectorstore.vector_creator import VectorCreator

        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})
        store = VectorCreator.create_vectorstore("faiss", "source")
        real_get = store.get_chunks.side_effect
        store.get_chunks.side_effect = RuntimeError("vector store down")

        worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        store.get_chunks.side_effect = real_get
        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert second["modified_files"] == ["a.md"]
        assert "old-a" not in [c["doc_id"] for c in chunk_store]


def _with_manifest(pg_conn, src, generation="g1", indexed=None):
    SourcesRepository(pg_conn).update(str(src["id"]), "alice", {"sync_manifest": {
        "version": 1, "generation": generation, "indexed_generation": indexed, "files": {},
    }})


def _manifest(pg_conn, src):
    return SourcesRepository(pg_conn).get(str(src["id"]), "alice")["sync_manifest"]


@pytest.mark.unit
class TestReingestMarksTheIndexCurrent:
    """A clean reingest records the ``sync_manifest`` generation it read the files at."""

    def test_no_changes_marks_the_index_current(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        stored_files.update({"a.md": b"alpha"})
        src = _hashed_source(pg_conn, dict(stored_files))
        _with_manifest(pg_conn, src)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "no_changes"
        assert _manifest(pg_conn, src)["indexed_generation"] == "g1"

    def test_a_completed_run_marks_the_index_current(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed"
        manifest = _manifest(pg_conn, src)
        assert manifest["indexed_generation"] == "g1" and manifest["generation"] == "g1"

    def test_files_changed_during_the_run_keep_the_index_stale(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store, monkeypatch,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)
        real_download = worker._download_source_files_to_dir

        def download_then_sync(*args, **kwargs):
            complete = real_download(*args, **kwargs)
            # A sync stores new files while this run is reading the old ones.
            _with_manifest(pg_conn, src, generation="g2")
            return complete

        monkeypatch.setattr(worker, "_download_source_files_to_dir", download_then_sync)

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed"
        manifest = _manifest(pg_conn, src)
        assert manifest["generation"] == "g2" and manifest["indexed_generation"] is None

    def test_a_run_with_a_failed_embedding_keeps_the_index_stale(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)
        from docsgpt.vectorstore.vector_creator import VectorCreator

        VectorCreator.create_vectorstore("faiss", "source").add_chunk.side_effect = RuntimeError("embedding service down")

        worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert _manifest(pg_conn, src)["indexed_generation"] is None

    def test_a_source_no_sync_touched_gets_no_manifest(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        stored_files.update({"a.md": b"alpha"})
        src = _hashed_source(pg_conn, dict(stored_files))

        worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert _manifest(pg_conn, src) is None


    def test_a_run_that_could_not_compare_the_files_keeps_the_index_stale(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store, monkeypatch,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)
        monkeypatch.setattr(worker, "_structure_files", MagicMock(side_effect=RuntimeError("bad structure")))

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "no_changes"
        assert _manifest(pg_conn, src)["indexed_generation"] is None


@pytest.mark.unit
class TestRecordSyncManifest:
    """``ingest_worker`` stores the upload's record only on a source that has none."""

    RECORD = {"version": 1, "generation": "up", "indexed_generation": "up", "files": {
        "a.md": {"path": "a.md", "sha256": _sha(b"alpha")},
    }}

    def test_a_new_source_gets_the_record(self, pg_conn, patch_worker_db):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})

        worker._record_sync_manifest(str(src["id"]), "alice", self.RECORD)

        assert _manifest(pg_conn, src) == self.RECORD

    def test_an_ingest_run_again_does_not_replace_what_a_sync_recorded(self, pg_conn, patch_worker_db):
        """A redelivered ingest must not bring back the hashes of files a sync has since replaced."""
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        _with_manifest(pg_conn, src, generation="g2")

        worker._record_sync_manifest(str(src["id"]), "alice", self.RECORD)

        assert _manifest(pg_conn, src)["generation"] == "g2"


@pytest.mark.unit
class TestIncompleteScanChangesNothing:
    """A stored file that could not be read would look removed: the run stops before the index changes."""

    def test_a_failed_download_fails_the_run_and_keeps_the_chunks(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha", "b.md": b"beta"})
        stored_files.update({"a.md": b"alpha, edited", "b.md": b"beta"})
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-b", "text": "beta", "metadata": {"source": "b.md"}},
        ])
        _with_manifest(pg_conn, src)
        storage = worker.StorageCreator.get_storage()
        real = storage.get_file.side_effect

        def get_file(path):
            if path.endswith("b.md"):
                raise OSError("storage hiccup")
            return real(path)

        storage.get_file.side_effect = get_file

        with pytest.raises(RuntimeError, match="Could not read every stored file"):
            worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert [c["doc_id"] for c in chunk_store] == ["old-a", "old-b"]
        assert _manifest(pg_conn, src)["indexed_generation"] is None

    def test_a_chunk_that_could_not_be_deleted_is_retried_and_keeps_the_index_stale(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha", "gone.md": b"old"})
        stored_files.update({"a.md": b"alpha"})
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-gone", "text": "old", "metadata": {"source": "gone.md"}},
        ])
        _with_manifest(pg_conn, src)
        from docsgpt.vectorstore.vector_creator import VectorCreator

        store = VectorCreator.create_vectorstore("faiss", "source")
        real_delete = store.delete_chunk.side_effect
        store.delete_chunk.side_effect = RuntimeError("vector store down")

        first = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert first["index_current"] is False
        assert _manifest(pg_conn, src)["indexed_generation"] is None
        store.delete_chunk.side_effect = real_delete

        second = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert second["removed_files"] == ["gone.md"]
        assert [c["doc_id"] for c in chunk_store] == ["old-a"]
        assert second["index_current"] is True


@pytest.mark.unit
class TestReingestThatDiesPartWay:
    """A run killed between changing chunks and saving the structure must not leave hashes the index does not match."""

    def test_structure_with_pending_lists_added_and_edited_files_without_a_hash(self):
        old = {"a.md": {"type": "t", "size_bytes": 1, "sha256": "h-a"}, "docs": {"b.md": {
            "type": "t", "size_bytes": 1, "sha256": "h-b",
        }}}
        new = {"a.md": {"type": "t", "size_bytes": 2, "sha256": "h-a2"}, "docs": {
            "b.md": {"type": "t", "size_bytes": 1, "sha256": "h-b"},
            "new": {"c.md": {"type": "t", "size_bytes": 3, "sha256": "h-c"}},
        }}

        pending = worker._structure_with_pending(old, new, [os.path.join("docs", "new", "c.md")], ["a.md"])

        assert pending == {
            "a.md": {"type": "t", "size_bytes": 1},
            "docs": {"b.md": {"type": "t", "size_bytes": 1, "sha256": "h-b"}, "new": {"c.md": {
                "type": "t", "size_bytes": 3,
            }}},
        }
        assert old["a.md"]["sha256"] == "h-a" and new["docs"]["new"]["c.md"]["sha256"] == "h-c"

    def test_structure_with_pending_keeps_removed_files_listed_without_a_hash(self):
        old = {"a.md": {"type": "t", "size_bytes": 1, "sha256": "h-a"}, "gone.md": {
            "type": "t", "size_bytes": 1, "sha256": "h-gone",
        }}
        new = {"a.md": {"type": "t", "size_bytes": 1, "sha256": "h-a"}}

        pending = worker._structure_with_pending(old, new, [], ["gone.md"])

        assert pending["gone.md"] == {"type": "t", "size_bytes": 1}
        assert pending["a.md"]["sha256"] == "h-a"

    def test_structure_with_pending_keeps_a_removed_file_a_folder_took_the_place_of(self):
        """``guide`` was a file and is a folder now: the file's entry is the only note of its chunks."""
        old = {"guide": {"type": "t", "size_bytes": 1, "sha256": "h-g"}, "docs": {"a.md": {
            "type": "t", "size_bytes": 1, "sha256": "h-a",
        }}}
        new = {"guide": {"b.md": {"type": "t", "size_bytes": 2, "sha256": "h-b"}}, "docs": {
            "type": "t", "size_bytes": 3, "sha256": "h-d",
        }}

        pending = worker._structure_with_pending(
            old, new, [os.path.join("guide", "b.md"), "docs"], ["guide", os.path.join("docs", "a.md")],
        )

        assert pending == {
            "guide": {"type": "t", "size_bytes": 1},
            "docs": {"a.md": {"type": "t", "size_bytes": 1}},
        }

    def test_a_file_seen_missing_by_a_dead_run_is_embedded_again_when_it_is_there(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        """A run that listed the files mid-change saw ``a.md`` missing, deleted its chunks and died."""
        src = _hashed_source(pg_conn, {"a.md": b"alpha", "b.md": b"beta"})
        chunk_store.extend([
            {"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}},
            {"doc_id": "old-b", "text": "beta", "metadata": {"source": "b.md"}},
        ])
        stored_files.update({"b.md": b"beta"})
        _with_manifest(pg_conn, src)
        with patch.object(worker, "_apply_display_names_to_structure", side_effect=SystemExit("killed")):
            with pytest.raises(SystemExit):
                worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        assert [c["doc_id"] for c in chunk_store] == ["old-b"]
        # The file is stored after all, with the content its saved hash named.
        stored_files.update({"a.md": b"alpha"})

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed" and result["modified_files"] == ["a.md"]
        assert {c["metadata"]["source"] for c in chunk_store} == {"a.md", "b.md"}
        assert result["index_current"] is True

    def test_an_edit_reverted_after_a_dead_run_is_embedded_again(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)
        from docsgpt.vectorstore.vector_creator import VectorCreator

        store = VectorCreator.create_vectorstore("faiss", "source")
        real_add = store.add_chunk.side_effect
        # The run deletes a.md's chunks, then the process is killed.
        store.add_chunk.side_effect = SystemExit("killed")
        with pytest.raises(SystemExit):
            worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        store.add_chunk.side_effect = real_add
        assert not chunk_store
        # The file goes back to what the saved hash said.
        stored_files.update({"a.md": b"alpha"})

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed" and result["modified_files"] == ["a.md"]
        assert [c["text"] for c in chunk_store if c["metadata"]["source"] == "a.md"]
        assert result["index_current"] is True

    def test_a_file_added_by_a_dead_run_and_then_removed_leaves_no_chunks(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        chunk_store.append({"doc_id": "old-a", "text": "alpha", "metadata": {"source": "a.md"}})
        stored_files.update({"a.md": b"alpha", "b.md": b"beta"})
        # The run embeds b.md, then dies before saving the final structure.
        with patch.object(worker, "_apply_display_names_to_structure", side_effect=SystemExit("killed")):
            with pytest.raises(SystemExit):
                worker.reingest_source_worker(task_self, str(src["id"]), "alice")
        assert any(c["metadata"]["source"] == "b.md" for c in chunk_store)
        del stored_files["b.md"]

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["removed_files"] == ["b.md"]
        assert {c["metadata"]["source"] for c in chunk_store} == {"a.md"}


@pytest.mark.unit
class TestReingestSaysWhetherTheIndexIsCurrent:
    def test_true_only_when_the_mark_was_set(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        stored_files.update({"a.md": b"alpha"})
        src = _hashed_source(pg_conn, dict(stored_files))

        assert worker.reingest_source_worker(task_self, str(src["id"]), "alice")["index_current"] is False

        _with_manifest(pg_conn, src)
        assert worker.reingest_source_worker(task_self, str(src["id"]), "alice")["index_current"] is True

    def test_false_while_the_files_are_being_written(
        self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store,
    ):
        stored_files.update({"a.md": b"alpha"})
        src = _hashed_source(pg_conn, dict(stored_files))
        SourcesRepository(pg_conn).update(str(src["id"]), "alice", {"sync_manifest": {
            "version": 1, "generation": "g1", "indexed_generation": None, "writing": True, "files": {},
        }})

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["index_current"] is False
        assert _manifest(pg_conn, src)["indexed_generation"] is None

    def test_false_when_an_embedding_failed(self, pg_conn, patch_worker_db, task_self, stored_files, chunk_store):
        src = _hashed_source(pg_conn, {"a.md": b"alpha"})
        stored_files.update({"a.md": b"alpha, edited"})
        _with_manifest(pg_conn, src)
        from docsgpt.vectorstore.vector_creator import VectorCreator

        VectorCreator.create_vectorstore("faiss", "source").add_chunk.side_effect = RuntimeError("embedding service down")

        result = worker.reingest_source_worker(task_self, str(src["id"]), "alice")

        assert result["status"] == "completed" and result["index_current"] is False
