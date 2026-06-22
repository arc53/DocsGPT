"""Tests for ``application.worker.convert_source_to_wiki_worker``.

The worker reassembles wiki pages from a source's existing vector-store
chunks (grouped by ``metadata.source``) and enqueues a per-page re-embed.
``VectorCreator.create_vectorstore`` and the re-embed task are mocked so no
real store access or embeddings run; the ``sources`` / ``wiki_pages`` rows
are real so the assertions read them back.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.storage.db.repositories.sources import SourcesRepository
from application.storage.db.repositories.wiki_pages import WikiPagesRepository


def _seed_source(pg_conn, config=None, file_path=""):
    src = SourcesRepository(pg_conn).create(
        "doc-set",
        user_id="alice",
        type="crawler",
        retriever="classic",
        file_path=file_path,
        config=config or {},
        directory_structure={"a.md": {"type": "text/markdown", "size_bytes": 1}},
    )
    return str(src["id"])


def _chunk(text, source=None, doc_id="d", **extra_meta):
    metadata = dict(extra_meta)
    if source is not None:
        metadata["source"] = source
    return {"doc_id": doc_id, "text": text, "metadata": metadata}


def _patch_store(monkeypatch, chunks):
    store = MagicMock(name="vectorstore")
    store.get_chunks.return_value = chunks
    monkeypatch.setattr(
        "application.vectorstore.vector_creator.VectorCreator.create_vectorstore",
        lambda *a, **kw: store,
    )
    return store


def _patch_reembed(monkeypatch):
    delay = MagicMock(name="reembed_delay")
    monkeypatch.setattr("application.api.user.tasks.reembed_wiki_page.delay", delay)
    return delay


@pytest.mark.unit
class TestConvertSourceToWikiWorker:
    def test_two_pages_reassembled_from_chunks(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("guide part one.", source="guide.md", doc_id="g1"),
                _chunk("guide part two.", source="guide.md", doc_id="g2"),
                _chunk("intro body.", source="notes/intro.md", doc_id="i1"),
            ],
        )
        delay = _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "converted"
        assert result["pages_created"] == 2

        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        by_path = {p["path"]: p for p in pages}
        assert set(by_path) == {"/guide.md", "/notes/intro.md"}
        assert by_path["/guide.md"]["content"] == "guide part one.\n\nguide part two."
        assert by_path["/guide.md"]["title"] == "guide.md"
        assert by_path["/notes/intro.md"]["content"] == "intro body."
        assert by_path["/notes/intro.md"]["title"] == "intro.md"

        assert delay.call_count == 2
        paths = {c.args[1] for c in delay.call_args_list}
        assert paths == {"/guide.md", "/notes/intro.md"}
        for call in delay.call_args_list:
            assert call.args[0] == source_id
            assert call.kwargs["user"] == "alice"
            assert call.kwargs["idempotency_key"].startswith(
                f"reembed-wiki:{source_id}:"
            )

    def test_original_chunks_deleted_after_convert(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        store = _patch_store(
            monkeypatch,
            [
                _chunk("guide part one.", source="guide.md", doc_id="g1"),
                _chunk("guide part two.", source="guide.md", doc_id="g2"),
                _chunk("intro body.", source="notes/intro.md", doc_id="i1"),
            ],
        )
        delay = _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "converted"
        deleted = {c.args[0] for c in store.delete_chunk.call_args_list}
        assert deleted == {"g1", "g2", "i1"}
        assert delay.call_count == 2

    def test_chunk_without_doc_id_not_deleted(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        chunk = {"text": "body", "metadata": {"source": "a.md"}}
        store = _patch_store(monkeypatch, [chunk])
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "converted"
        store.delete_chunk.assert_not_called()

    def test_skipped_chunk_with_doc_id_still_deleted(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        # A chunk skipped for an invalid path must still have its original
        # vector chunk purged, not left orphaned after the source flips to wiki.
        from application import worker

        source_id = _seed_source(pg_conn)
        store = _patch_store(
            monkeypatch,
            [
                _chunk("good", source="ok.md", doc_id="ok"),
                _chunk("bad", source="../evil.md", doc_id="evil"),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["pages_created"] == 1
        deleted = {c.args[0] for c in store.delete_chunk.call_args_list}
        assert deleted == {"ok", "evil"}

    def test_no_pages_path_deletes_nothing(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        store = _patch_store(monkeypatch, [])
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "no_pages"
        store.delete_chunk.assert_not_called()

    def test_kind_flipped_and_exposure_defaulted(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [_chunk("body", source="a.md")])
        _patch_reembed(monkeypatch)

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        cfg = SourceConfig.parse(refreshed.get("config"))
        assert cfg.kind == "wiki"
        assert cfg.retrieval.exposure == "agentic_tool"

    def test_preserves_non_default_exposure(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        source_id = _seed_source(
            pg_conn, config={"retrieval": {"exposure": "agentic_tool"}}
        )
        _patch_store(monkeypatch, [_chunk("body", source="a.md")])
        _patch_reembed(monkeypatch)

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        cfg = SourceConfig.parse(refreshed.get("config"))
        assert cfg.kind == "wiki"
        assert cfg.retrieval.exposure == "agentic_tool"

    def test_chunk_order_hint_respected(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("second", source="a.md", doc_id="a2", chunk_index=1),
                _chunk("first", source="a.md", doc_id="a1", chunk_index=0),
            ],
        )
        _patch_reembed(monkeypatch)

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        by_path = {p["path"]: p for p in pages}
        assert by_path["/a.md"]["content"] == "first\n\nsecond"

    def test_short_overlap_not_trimmed(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("The end.", source="a.md", doc_id="a1"),
                _chunk("The end. More", source="a.md", doc_id="a2"),
            ],
        )
        _patch_reembed(monkeypatch)

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        by_path = {p["path"]: p for p in pages}
        assert by_path["/a.md"]["content"] == "The end.\n\nThe end. More"

    def test_long_overlap_trimmed_between_chunks(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        overlap = "x" * 40
        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("head " + overlap, source="a.md", doc_id="a1"),
                _chunk(overlap + " tail", source="a.md", doc_id="a2"),
            ],
        )
        _patch_reembed(monkeypatch)

        worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        by_path = {p["path"]: p for p in pages}
        assert by_path["/a.md"]["content"] == "head " + overlap + "\n\n tail"

    def test_no_chunks_leaves_kind_and_structure(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker
        from application.storage.db.source_config import SourceConfig

        original_structure = {"a.md": {"type": "text/markdown", "size_bytes": 1}}
        source_id = _seed_source(pg_conn)
        _patch_store(monkeypatch, [])
        rebuild = MagicMock(name="rebuild")
        monkeypatch.setattr(worker, "rebuild_wiki_directory_structure", rebuild)
        delay = _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "no_pages"
        assert result["pages_created"] == 0
        rebuild.assert_not_called()
        delay.assert_not_called()

        refreshed = SourcesRepository(pg_conn).get_any(source_id, "alice")
        assert SourceConfig.parse(refreshed.get("config")).kind != "wiki"
        assert refreshed.get("directory_structure") == original_structure

    def test_missing_path_chunk_skipped(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("good", source="ok.md"),
                _chunk("orphan", source=None),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["pages_created"] == 1
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/ok.md"}
        assert any(s["reason"] == "missing path" for s in result["skipped"])

    def test_invalid_path_chunk_skipped(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("good", source="ok.md"),
                _chunk("bad", source="../evil.md"),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["pages_created"] == 1
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/ok.md"}
        skipped = {(s["file"], s["reason"]) for s in result["skipped"]}
        assert ("../evil.md", "invalid path") in skipped

    def test_path_falls_back_to_filename_then_title(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("from filename", source=None, filename="byname.md"),
                _chunk("from title", source=None, title="bytitle.md"),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["pages_created"] == 2
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/byname.md", "/bytitle.md"}

    def test_crawler_chunk_uses_file_path_not_url(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk(
                    "setup body",
                    source="https://docs.x.com/guides/setup",
                    file_path="guides/setup.md",
                ),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "converted"
        assert result["skipped"] == []
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/guides/setup.md"}

    def test_connector_chunks_kept_separate_by_file_name(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [
                _chunk("page a", source="confluence", file_name="Page A", doc_id="a"),
                _chunk("page b", source="confluence", file_name="Page B", doc_id="b"),
            ],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["pages_created"] == 2
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/Page A", "/Page B"}

    def test_url_only_chunk_normalized_not_skipped(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)
        _patch_store(
            monkeypatch,
            [_chunk("body", source="https://x.com/a/b")],
        )
        _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "converted"
        assert result["skipped"] == []
        pages = WikiPagesRepository(pg_conn).list_for_source(source_id)
        assert {p["path"] for p in pages} == {"/a/b"}

    def test_already_wiki_returns_early(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn, config={"kind": "wiki"})
        store = _patch_store(monkeypatch, [_chunk("body", source="a.md")])
        delay = _patch_reembed(monkeypatch)

        result = worker.convert_source_to_wiki_worker(task_self, source_id, "alice")

        assert result["status"] == "already_wiki"
        store.get_chunks.assert_not_called()
        delay.assert_not_called()
