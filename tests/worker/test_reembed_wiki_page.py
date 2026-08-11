"""Tests for the per-page wiki re-embed worker and Celery task.

The worker loads the source row from the ephemeral DB, then re-embeds (or
purges) one wiki page. The vector store, ``ChunkerCreator``, and the page
lookup are mocked so no live embeddings run; the ``sources`` row is real so
``SourcesRepository.get_any`` resolves.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from application.parser.schema.base import Document
from application.storage.db.repositories.sources import SourcesRepository


def _seed_source(pg_conn) -> str:
    src = SourcesRepository(pg_conn).create(
        "wiki-set",
        user_id="alice",
        type="wiki",
        config={"kind": "wiki"},
    )
    return str(src["id"])


def _patch_store(monkeypatch, store):
    monkeypatch.setattr(
        "application.vectorstore.vector_creator.VectorCreator.create_vectorstore",
        lambda *a, **kw: store,
    )


def _patch_repo(monkeypatch, page):
    """Replace ``WikiPagesRepository`` with one returning ``page`` and a stub setter."""
    repo = MagicMock(name="wiki_repo")
    repo.get_by_path.return_value = page
    repo.set_embed_status.return_value = True
    monkeypatch.setattr(
        "application.worker.WikiPagesRepository", lambda conn: repo
    )
    return repo


def _patch_chunker(monkeypatch, chunks):
    calls: list[dict] = []

    def _create_chunker(strategy, **kwargs):
        calls.append({"strategy": strategy, **kwargs})
        chunker = MagicMock(name="chunker")
        chunker.chunk.return_value = chunks
        return chunker

    monkeypatch.setattr(
        "application.worker.ChunkerCreator.create_chunker",
        staticmethod(_create_chunker),
    )
    return calls


@pytest.mark.unit
class TestReembedWikiPageWorker:
    def test_page_exists_reembeds(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)

        store = MagicMock(name="vector_store")
        store.delete_chunks_by_source_path.return_value = 3
        _patch_store(monkeypatch, store)

        repo = _patch_repo(
            monkeypatch,
            {"content": "page body", "title": "Page Title"},
        )
        _patch_chunker(
            monkeypatch,
            [Document(text="c1"), Document(text="c2")],
        )

        result = worker.reembed_wiki_page_worker(
            task_self, source_id, "guide/intro.md", "hash-1", "alice"
        )

        store.delete_chunks_by_source_path.assert_called_once_with(
            "guide/intro.md"
        )
        assert store.add_chunk.call_count == 2
        for call in store.add_chunk.call_args_list:
            assert call.kwargs["metadata"]["source"] == "guide/intro.md"
            assert call.kwargs["metadata"]["title"] == "Page Title"
            assert call.kwargs["metadata"]["filename"] == "guide/intro.md"
        repo.set_embed_status.assert_called_once_with(
            source_id, "guide/intro.md", "embedded"
        )
        assert result == {"status": "embedded", "added": 2, "deleted": 3}

    def test_page_missing_purges(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)

        store = MagicMock(name="vector_store")
        store.delete_chunks_by_source_path.return_value = 4
        _patch_store(monkeypatch, store)

        repo = _patch_repo(monkeypatch, None)

        result = worker.reembed_wiki_page_worker(
            task_self, source_id, "old/page.md", "hash-x", "alice"
        )

        store.delete_chunks_by_source_path.assert_called_once_with("old/page.md")
        store.add_chunk.assert_not_called()
        repo.set_embed_status.assert_not_called()
        assert result == {"status": "deleted", "deleted": 4}

    def test_embed_failure_sets_failed_and_reraises(
        self, pg_conn, patch_worker_db, task_self, monkeypatch
    ):
        from application import worker

        source_id = _seed_source(pg_conn)

        store = MagicMock(name="vector_store")
        store.delete_chunks_by_source_path.return_value = 0
        store.add_chunk.side_effect = RuntimeError("embed boom")
        _patch_store(monkeypatch, store)

        repo = _patch_repo(
            monkeypatch, {"content": "page body", "title": "T"}
        )
        _patch_chunker(monkeypatch, [Document(text="c1")])

        with pytest.raises(RuntimeError, match="embed boom"):
            worker.reembed_wiki_page_worker(
                task_self, source_id, "p.md", "hash-2", "alice"
            )

        repo.set_embed_status.assert_called_once_with(source_id, "p.md", "failed")


@pytest.mark.unit
class TestReembedWikiPageTask:
    def test_idempotency_key_is_content_hash(self, pg_conn, monkeypatch):
        """A redelivery with the same content_hash key short-circuits the worker."""
        from application.api.user import tasks

        @contextmanager
        def _yield():
            yield pg_conn

        monkeypatch.setattr(
            "application.api.user.idempotency.db_session", _yield
        )
        monkeypatch.setattr(
            "application.api.user.idempotency.db_readonly", _yield
        )

        calls: list[str] = []

        def _fake_worker(self, source_id, path, content_hash, user):
            calls.append(content_hash)
            return {"status": "embedded", "added": 1, "deleted": 0}

        monkeypatch.setattr(tasks, "reembed_wiki_page_worker", _fake_worker)

        first = tasks.reembed_wiki_page(
            "src-1", "p.md", "abc123", "alice", idempotency_key="abc123",
        )
        second = tasks.reembed_wiki_page(
            "src-1", "p.md", "abc123", "alice", idempotency_key="abc123",
        )

        assert first == second
        assert len(calls) == 1
