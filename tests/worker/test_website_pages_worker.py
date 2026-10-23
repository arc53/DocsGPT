"""Tests for ``website_pages_worker``: adding pages to and refreshing a page of a Website source."""

from contextlib import contextmanager

import pytest

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "u-pages"
OLD = "2026-01-01T00:00:00+00:00"


def _leaf(url, tokens, title="Old"):
    return {
        "type": "text/markdown", "size_bytes": 10, "token_count": tokens, "url": url, "title": title, "fetched_at": OLD,
    }


class FakeStore:
    """A chunk store that records every add and delete and can be made to fail.

    ``fail_on`` is a predicate over ``(text, metadata)``; when it holds, ``add_chunk``
    raises as an embedding provider would.
    """

    def __init__(self):
        self.chunks = {}
        self.log = []
        self.fail_on = None
        self._next = 0

    def seed(self, text, source, file_path):
        self._next += 1
        chunk_id = f"old-{self._next}"
        self.chunks[chunk_id] = {"text": text, "metadata": {"source": source, "file_path": file_path}}
        return chunk_id

    def add_chunk(self, text, metadata=None):
        if self.fail_on and self.fail_on(text, metadata or {}):
            raise RuntimeError("embedding provider unavailable")
        self._next += 1
        chunk_id = f"new-{self._next}"
        self.chunks[chunk_id] = {"text": text, "metadata": dict(metadata or {})}
        self.log.append(("add", chunk_id))
        return chunk_id

    def add_chunks(self, texts, metadatas=None):
        # The base store's all-or-none loop over add_chunk; each call is one batch (one FAISS save).
        from docsgpt.vectorstore.base import BaseVectorStore

        self.log.append(("batch", len(texts)))
        return BaseVectorStore.add_chunks(self, texts, metadatas)

    def chunk_ids_by_source_paths(self, paths):
        wanted = set(paths)
        return [cid for cid, c in self.chunks.items() if c["metadata"].get("source") in wanted]

    def chunk_ids_by_file_paths(self, paths):
        wanted = set(paths)
        return [cid for cid, c in self.chunks.items() if c["metadata"].get("file_path") in wanted]

    def delete_chunks(self, chunk_ids):
        deleted = 0
        for chunk_id in list(chunk_ids):
            if self.chunks.pop(chunk_id, None) is not None:
                deleted += 1
                self.log.append(("delete", chunk_id))
        return deleted

    def texts_for(self, source):
        return [c["text"] for c in self.chunks.values() if c["metadata"].get("source") == source]


class ParagraphChunker:
    """One chunk per paragraph, so a page can fail half-way through."""

    def chunk(self, documents):
        out = []
        for doc in documents:
            for part in doc.text.split("\n\n"):
                out.append(Document(part, extra_info=dict(doc.extra_info or {})))
        return out


# The page entries the tests add: an add fetches only addresses its source's config lists.
LISTED = ["a", "b", "c", "guide/b", "gone", "old"]


@pytest.fixture
def source(pg_conn):
    return SourcesRepository(pg_conn).create(
        "Docs",
        user_id=USER,
        type="website",
        remote_data={
            "entries": [{"url": f"https://docs.x.io/{page}", "mode": "page"} for page in LISTED], "keep_links": True,
        },
        directory_structure={"a.md": _leaf("https://docs.x.io/a", 40)},
        tokens="40",
    )


@pytest.fixture
def pipeline(monkeypatch):
    """A fake store, a fake web fetch and captured events."""
    from docsgpt import worker
    from docsgpt.parser.remote import web_loader
    from docsgpt.vectorstore import vector_creator

    store = FakeStore()
    store.seed("old A one", "https://docs.x.io/a", "a.md")
    store.seed("old A two", "https://docs.x.io/a", "a.md")
    monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)
    monkeypatch.setattr(worker.ChunkerCreator, "create_chunker", lambda *a, **k: ParagraphChunker())

    pages = {}
    fetch_calls = []
    # Run while the pages are being fetched: another change landing mid-task.
    during_fetch = []

    def fake_load(self, inputs):
        fetch_calls.append((list(inputs), self.keep_links))
        for hook in during_fetch:
            hook()
        return [
            Document(pages[url], extra_info={"source": url, "title": f"Title {url[-1]}", "file_path": "ignored.md"})
            for url in inputs if url in pages
        ]

    monkeypatch.setattr(web_loader.WebLoader, "load_data", fake_load)
    events = []
    monkeypatch.setattr(worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((kind, payload)))
    return {"store": store, "pages": pages, "fetch_calls": fetch_calls, "events": events, "during_fetch": during_fetch}


def _source_row(pg_conn, source):
    return SourcesRepository(pg_conn).get(str(source["id"]), USER)


def _tree(pg_conn, source):
    return _source_row(pg_conn, source)["directory_structure"]


@pytest.mark.unit
class TestAddPages:
    def test_appends_pages_without_touching_the_others(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/guide/b"] = "# B\n\nBody of page B."
        result = worker.website_pages_worker(
            task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/guide/b"],
        )

        assert result["pages"] == 1
        # The source's keep_links setting reaches the fetch.
        assert pipeline["fetch_calls"] == [(["https://docs.x.io/guide/b"], True)]
        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/guide/b") == ["# B", "Body of page B."]
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        added = [c for c in store.chunks.values() if c["metadata"]["source"] == "https://docs.x.io/guide/b"]
        assert all(c["metadata"]["file_path"] == "guide/b.md" for c in added)

        row = _source_row(pg_conn, source)
        tree = row["directory_structure"]
        assert tree["a.md"]["token_count"] == 40
        new_leaf = tree["guide"]["b.md"]
        assert new_leaf["url"] == "https://docs.x.io/guide/b"
        assert new_leaf["title"] == "Title b"
        assert new_leaf["fetched_at"] != OLD
        assert int(row["tokens"]) == 40 + new_leaf["token_count"]

        kinds = [kind for kind, _ in pipeline["events"]]
        assert kinds == ["source.ingest.queued", "source.ingest.completed"]
        assert pipeline["events"][-1][1]["operation"] == "add_pages"

    def test_events_carry_the_task_id(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        # The UI matches the events to the request that queued the task.
        from docsgpt import worker

        task_self.request.id = "task-9"
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])
        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/gone"])

        kinds = [kind for kind, _ in pipeline["events"]]
        assert kinds[-1] == "source.ingest.failed" and "source.ingest.completed" in kinds
        assert all(payload["task_id"] == "task-9" for _, payload in pipeline["events"])

    def test_adding_a_page_already_there_replaces_it(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "# A\n\nThe new text of page A."
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/a"])

        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == ["# A", "The new text of page A."]
        # The new copy is stored (in one batch) before the old one goes.
        kinds = [kind for kind, _ in store.log]
        assert kinds == ["batch", "add", "add", "delete", "delete"]
        tree = _tree(pg_conn, source)
        assert list(tree) == ["a.md"]
        assert tree["a.md"]["fetched_at"] != OLD

    def test_a_page_that_cannot_be_fetched_fails_and_changes_nothing(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/gone"])

        assert pipeline["store"].log == []
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_an_address_variant_of_a_page_replaces_it_and_its_chunks(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # ``/docs/`` and ``/docs`` are one page: adding the second must not
        # leave the first's chunks searchable with no tree entry to remove.
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [
                {"url": "https://docs.x.io/", "mode": "site"}, {"url": "https://docs.x.io/docs#intro", "mode": "page"},
            ]},
            directory_structure={"docs.md": _leaf("https://docs.x.io/docs/", 10)},
            tokens="10",
        )
        store = pipeline["store"]
        store.seed("old docs", "https://docs.x.io/docs/", "docs.md")
        pipeline["pages"]["https://docs.x.io/docs#intro"] = "New docs"
        worker.website_pages_worker(task_self, str(src["id"]), USER, "add", urls=["https://docs.x.io/docs#intro"])

        assert store.texts_for("https://docs.x.io/docs/") == []
        assert store.texts_for("https://docs.x.io/docs#intro") == ["New docs"]
        tree = _tree(pg_conn, src)
        assert list(tree) == ["docs.md"]
        assert tree["docs.md"]["url"] == "https://docs.x.io/docs#intro"

    def test_a_different_page_on_a_taken_path_gets_its_own_path(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # ``/docs`` and ``/docs.html`` are different pages that both map to ``docs.md``.
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [
                {"url": "https://docs.x.io/docs", "mode": "page"}, {"url": "https://docs.x.io/docs.html", "mode": "page"},
            ]},
            directory_structure={
                "docs.md": _leaf("https://docs.x.io/docs", 10), "docs-2.md": _leaf("https://docs.x.io/d2", 1),
            },
            tokens="11",
        )
        store = pipeline["store"]
        store.seed("old docs", "https://docs.x.io/docs", "docs.md")
        pipeline["pages"]["https://docs.x.io/docs.html"] = "HTML docs"
        worker.website_pages_worker(task_self, str(src["id"]), USER, "add", urls=["https://docs.x.io/docs.html"])

        tree = _tree(pg_conn, src)
        assert tree["docs.md"] == _leaf("https://docs.x.io/docs", 10)
        assert tree["docs-3.md"]["url"] == "https://docs.x.io/docs.html"
        assert store.texts_for("https://docs.x.io/docs") == ["old docs"]
        [new] = [c for c in store.chunks.values() if c["metadata"]["source"] == "https://docs.x.io/docs.html"]
        assert new["metadata"]["file_path"] == "docs-3.md"

    def test_pages_done_before_a_failing_page_are_kept(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        # Rule: a page is stored whole or not at all. The ones finished
        # before a failure stay (tree and chunks); the failing one leaves
        # nothing behind, and the task fails.
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B one\n\nB two"
        pipeline["pages"]["https://docs.x.io/c"] = "C one\n\nC two"
        store = pipeline["store"]
        store.fail_on = lambda text, metadata: text == "C two"

        with pytest.raises(RuntimeError):
            worker.website_pages_worker(
                task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b", "https://docs.x.io/c"],
            )

        assert store.texts_for("https://docs.x.io/b") == ["B one", "B two"]
        assert store.texts_for("https://docs.x.io/c") == []
        tree = _tree(pg_conn, source)
        assert sorted(tree) == ["a.md", "b.md"]
        assert int(_source_row(pg_conn, source)["tokens"]) == 40 + tree["b.md"]["token_count"]
        assert pipeline["events"][-1][0] == "source.ingest.failed"


@pytest.mark.unit
class TestRefreshPage:
    def test_refetches_one_page_in_place(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "# A\n\nRefreshed text for page A."
        result = worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert result["pages"] == 1
        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == ["# A", "Refreshed text for page A."]
        assert all(c["metadata"]["file_path"] == "a.md" for c in store.chunks.values())
        leaf = _tree(pg_conn, source)["a.md"]
        assert leaf["title"] == "Title a"
        assert leaf["fetched_at"] != OLD

    def test_a_failed_fetch_keeps_the_old_content(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert pipeline["store"].texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert _tree(pg_conn, source)["a.md"]["fetched_at"] == OLD

    def test_an_embedding_failure_half_way_keeps_the_old_content(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "New one\n\nNew two"
        store = pipeline["store"]
        store.fail_on = lambda text, metadata: text == "New two"

        with pytest.raises(RuntimeError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        # The half-stored new copy is taken out again; the old one was never touched.
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_an_unknown_path_is_an_error(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="nope.md")

    def test_the_page_is_found_by_its_address_wherever_a_sync_moved_it(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        # The route saw /a at a.md; a sync queued before re-derived the tree, so a.md holds /b now.
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"directory_structure": {
            "a.md": _leaf("https://docs.x.io/b", 5), "a-2.md": _leaf("https://docs.x.io/a", 40),
        }})
        pipeline["pages"]["https://docs.x.io/a"] = "fresh A"
        pipeline["pages"]["https://docs.x.io/b"] = "fresh B"
        worker.website_pages_worker(
            task_self, str(source["id"]), USER, "refresh", file_path="a.md", url="https://docs.x.io/a",
        )

        assert pipeline["fetch_calls"][0][0] == ["https://docs.x.io/a"]
        tree = _tree(pg_conn, source)
        assert tree["a.md"] == _leaf("https://docs.x.io/b", 5)
        assert tree["a-2.md"]["fetched_at"] != OLD

    def test_a_page_that_left_the_tree_is_an_error_not_another_page(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "fresh A"
        with pytest.raises(ValueError, match="no longer"):
            worker.website_pages_worker(
                task_self, str(source["id"]), USER, "refresh", file_path="a.md", url="https://docs.x.io/gone",
            )

        assert pipeline["fetch_calls"] == []

    def test_the_task_passes_the_address_through(self, monkeypatch):
        from docsgpt import worker
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(worker, "website_pages_worker", lambda *a, **k: seen.append(k) or {"status": "ok"})
        tasks.website_pages.run("src", USER, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert seen[0]["file_path"] == "a.md" and seen[0]["url"] == "https://docs.x.io/a"


@pytest.fixture
def two_pages(pg_conn, pipeline):
    """A source with pages ``a.md`` and ``guide/b.md``, each with its chunks."""
    pipeline["store"].seed("B one", "https://docs.x.io/guide/b", "guide/b.md")
    return SourcesRepository(pg_conn).create(
        "Docs",
        user_id=USER,
        type="website",
        remote_data={"entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
        directory_structure={
            "a.md": _leaf("https://docs.x.io/a", 40), "guide": {"b.md": _leaf("https://docs.x.io/guide/b", 9)},
        },
        tokens="49",
    )


@pytest.mark.unit
class TestRemovePages:
    def test_deletes_the_pages_chunks_then_their_entries(
        self, pg_conn, patch_worker_db, task_self, two_pages, pipeline,
    ):
        from docsgpt import worker

        task_self.request.id = "remove-1"
        store = pipeline["store"]
        trees_at_delete = []
        real_delete = store.delete_chunks

        def delete_and_look(chunk_ids):
            # The page is still listed while its chunks go: the list changes last.
            trees_at_delete.append(_tree(pg_conn, two_pages))
            return real_delete(chunk_ids)

        store.delete_chunks = delete_and_look
        result = worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["guide/b.md"])

        assert result == {"status": "ok", "pages": 1}
        assert store.texts_for("https://docs.x.io/guide/b") == []
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert "b.md" in trees_at_delete[0]["guide"]
        row = _source_row(pg_conn, two_pages)
        assert row["directory_structure"] == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert row["tokens"] == "40"
        assert [kind for kind, _ in pipeline["events"]] == ["source.ingest.queued", "source.ingest.completed"]
        assert all(payload["task_id"] == "remove-1" for _, payload in pipeline["events"])
        assert pipeline["events"][-1][1]["operation"] == "remove_pages"
        assert pipeline["fetch_calls"] == []

    def test_a_folder_goes_in_one_delete(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        store = pipeline["store"]
        calls = []
        real_delete = store.delete_chunks
        store.delete_chunks = lambda ids: calls.append(list(ids)) or real_delete(ids)
        worker.website_pages_worker(
            task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md", "guide/b.md"],
        )

        assert len(calls) == 1 and len(calls[0]) == 3
        assert store.chunks == {}
        assert _tree(pg_conn, two_pages) == {}

    def test_pages_already_gone_are_ignored(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # A retried task, or a sync that rebuilt the tree meanwhile.
        from docsgpt import worker

        result = worker.website_pages_worker(
            task_self, str(two_pages["id"]), USER, "remove", file_paths=["gone.md"],
        )

        assert result["pages"] == 0
        assert pipeline["store"].log == []
        assert sorted(_tree(pg_conn, two_pages)) == ["a.md", "guide"]
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    def test_a_failed_delete_leaves_the_page_listed(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        def fail(chunk_ids):
            raise RuntimeError("index unavailable")

        pipeline["store"].delete_chunks = fail
        with pytest.raises(RuntimeError):
            worker.website_pages_worker(
                task_self, str(two_pages["id"]), USER, "remove", file_paths=["guide/b.md"],
            )

        assert pipeline["store"].texts_for("https://docs.x.io/guide/b") == ["B one"]
        row = _source_row(pg_conn, two_pages)
        assert "b.md" in row["directory_structure"]["guide"]
        assert row["tokens"] == "49"
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_a_page_added_meanwhile_is_kept(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # The tree is written on the row as it is when the chunks are gone.
        from docsgpt import worker

        store = pipeline["store"]
        real_delete = store.delete_chunks

        def delete_then_add(chunk_ids):
            deleted = real_delete(chunk_ids)
            tree = dict(_tree(pg_conn, two_pages))
            tree["c.md"] = _leaf("https://docs.x.io/c", 3)
            SourcesRepository(pg_conn).update(str(two_pages["id"]), USER, {"directory_structure": tree})
            return deleted

        store.delete_chunks = delete_then_add
        worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["guide/b.md"])

        row = _source_row(pg_conn, two_pages)
        assert sorted(row["directory_structure"]) == ["a.md", "c.md"]
        assert row["tokens"] == "43"

    def test_runs_holding_the_source_index_lock(
        self, pg_conn, patch_worker_db, task_self, two_pages, pipeline, monkeypatch,
    ):
        from docsgpt import worker

        held = []

        @contextmanager
        def fake_lock(source_id, **kwargs):
            held.append("locked")
            yield
            held.append("released")

        store = pipeline["store"]
        real_delete = store.delete_chunks
        store.delete_chunks = lambda ids: held.append("delete") or real_delete(ids)
        monkeypatch.setattr(worker, "source_index_lock", fake_lock)
        worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["guide/b.md"])

        assert held == ["locked", "delete", "released"]

    def test_a_busy_source_says_so_in_the_failed_event(
        self, pg_conn, patch_worker_db, task_self, two_pages, pipeline, monkeypatch,
    ):
        from docsgpt import worker
        from docsgpt.vectorstore.index_lock import SourceBusy

        @contextmanager
        def busy_lock(source_id, **kwargs):
            raise SourceBusy("busy")
            yield

        monkeypatch.setattr(worker, "source_index_lock", busy_lock)
        with pytest.raises(SourceBusy):
            worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md"])

        failed = [payload for kind, payload in pipeline["events"] if kind == "source.ingest.failed"]
        assert [payload.get("reason") for payload in failed] == ["busy"]
        assert pipeline["store"].log == []

    def test_a_wiki_is_left_alone(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(two_pages["id"]), USER, {"config": {"kind": "wiki"}})
        with pytest.raises(ValueError, match="wiki"):
            worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md"])

        assert pipeline["store"].log == []


@pytest.mark.unit
class TestRemoveByAddress:
    """A removal names each page by its address too, so a path a sync re-sorted can't remove another page."""

    def test_the_page_is_found_wherever_its_path_moved(self, pg_conn, patch_worker_db, task_self, pipeline):
        from docsgpt import worker

        store = pipeline["store"]
        store.seed("A html", "https://docs.x.io/a.html", "a-2.md")
        # The route saw /a.html at a.md; a sync then gave a.md to /a and moved /a.html to a-2.md.
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
            directory_structure={"a.md": _leaf("https://docs.x.io/a", 40), "a-2.md": _leaf("https://docs.x.io/a.html", 5)},
        )

        result = worker.website_pages_worker(
            task_self, str(src["id"]), USER, "remove", pages=[{"path": "a.md", "url": "https://docs.x.io/a.html"}],
        )

        assert result["pages"] == 1
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert store.texts_for("https://docs.x.io/a.html") == []
        assert _tree(pg_conn, src) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_a_page_no_longer_in_the_tree_removes_nothing(self, pg_conn, patch_worker_db, task_self, pipeline):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/a", "mode": "page"}]},
            directory_structure={"a.md": _leaf("https://docs.x.io/a", 40)},
        )

        result = worker.website_pages_worker(
            task_self, str(src["id"]), USER, "remove", pages=[{"path": "a.md", "url": "https://docs.x.io/a.html"}],
        )

        assert result["pages"] == 0
        assert pipeline["store"].log == []
        assert _tree(pg_conn, src) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_an_address_variant_finds_the_page(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        worker.website_pages_worker(
            task_self, str(two_pages["id"]), USER, "remove",
            pages=[{"path": "guide/b.md", "url": "https://docs.x.io/guide/b#intro"}],
        )

        assert pipeline["store"].texts_for("https://docs.x.io/guide/b") == []
        assert _tree(pg_conn, two_pages) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_a_legacy_leaf_without_an_address_is_removed_by_path(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        from docsgpt import worker

        store = pipeline["store"]
        store.chunks.clear()
        store.seed("legacy page", "https://docs.x.io/old.html", "old.md")
        store.seed("other page", "https://docs.x.io/keep.html", "keep.md")
        legacy = {"type": "text/markdown", "size_bytes": 10, "token_count": 4}
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="crawler", remote_data="https://docs.x.io/",
            directory_structure={"old.md": dict(legacy), "keep.md": dict(legacy)},
        )

        result = worker.website_pages_worker(
            task_self, str(src["id"]), USER, "remove", pages=[{"path": "old.md", "url": ""}],
        )

        assert result["pages"] == 1
        assert store.texts_for("https://docs.x.io/old.html") == []
        assert store.texts_for("https://docs.x.io/keep.html") == ["other page"]
        assert list(_tree(pg_conn, src)) == ["keep.md"]

    def test_a_pgvector_outage_while_listing_a_legacy_leaf_keeps_the_leaf(
        self, pg_conn, patch_worker_db, monkeypatch,
    ):
        """An outage must not read as "no chunks": the leaf would go while its chunks stay."""
        from unittest.mock import MagicMock

        from docsgpt import worker
        from docsgpt.core.settings import settings
        from docsgpt.vectorstore import vector_creator
        from docsgpt.vectorstore.pgvector import PGVectorStore

        legacy = {"type": "text/markdown", "size_bytes": 10, "token_count": 5}
        src = SourcesRepository(pg_conn).create(
            "site", user_id=USER, type="crawler", remote_data="https://x/",
            directory_structure={"guide.md": dict(legacy), "intro.md": dict(legacy)},
        )
        store = PGVectorStore.__new__(PGVectorStore)
        store._source_id, store._table_name = str(src["id"]), "documents"
        store._text_column, store._metadata_column = "text", "metadata"
        conn = MagicMock(closed=False)
        conn.cursor.return_value.execute.side_effect = ConnectionError("server closed the connection")
        store._get_connection = lambda: conn
        store._connection = None
        deletes = []
        store.delete_chunks = lambda ids: deletes.append(list(ids)) or 0
        monkeypatch.setattr(settings, "VECTOR_STORE", "pgvector")
        monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)

        with pytest.raises(ConnectionError):
            worker._remove_web_pages(str(src["id"]), USER, None, pages=[{"path": "guide.md", "url": ""}])

        assert deletes == []
        assert sorted(_tree(pg_conn, src)) == ["guide.md", "intro.md"]

    def test_the_task_passes_pages_through(self, monkeypatch):
        from docsgpt import worker
        from docsgpt.api.user import tasks

        seen = []
        monkeypatch.setattr(worker, "website_pages_worker", lambda *a, **k: seen.append(k) or {"status": "ok"})
        pages = [{"path": "a.md", "url": "https://docs.x.io/a"}]

        tasks.website_pages.run("src", USER, "remove", pages=pages)
        tasks.website_pages.run("src", USER, "remove", file_paths=["a.md"])

        assert seen[0]["pages"] == pages and seen[1]["file_paths"] == ["a.md"]


class SwallowingStore(FakeStore):
    """A store whose ``delete_chunk`` logs and returns False on an error, as MongoDB, Qdrant and Milvus do."""

    def __init__(self, fail_ids=()):
        super().__init__()
        self.fail_ids = set(fail_ids)

    def delete_chunks(self, chunk_ids):
        deleted = 0
        for chunk_id in list(chunk_ids):
            if chunk_id in self.fail_ids:
                continue
            if self.chunks.pop(chunk_id, None) is not None:
                deleted += 1
                self.log.append(("delete", chunk_id))
        return deleted


@pytest.mark.unit
class TestADeleteThatFailsQuietly:
    """A store that reports a failed delete with a count, not an error, still fails the change."""

    def _use(self, monkeypatch, store):
        from docsgpt.vectorstore import vector_creator

        monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)

    def test_a_removal_fails_and_writes_nothing(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline,
                                                monkeypatch):
        from docsgpt import worker

        store = SwallowingStore()
        store.seed("B one", "https://docs.x.io/guide/b", "guide/b.md")
        store.fail_ids = set(store.chunks)
        self._use(monkeypatch, store)

        with pytest.raises(RuntimeError, match="could not be deleted"):
            worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["guide/b.md"])

        assert store.texts_for("https://docs.x.io/guide/b") == ["B one"]
        assert "b.md" in _tree(pg_conn, two_pages)["guide"]
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_ids_already_gone_are_not_a_failure(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # FAISS and pgvector skip an id that isn't there; one deleted meanwhile is as good as deleted.
        from docsgpt import worker

        store = pipeline["store"]
        real_delete = store.delete_chunks

        def one_went_meanwhile(chunk_ids):
            ids = list(chunk_ids)
            store.chunks.pop(ids[0])
            return real_delete(ids)

        store.delete_chunks = one_went_meanwhile
        worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md"])

        assert "a.md" not in _tree(pg_conn, two_pages)

    def test_a_failed_rollback_still_reports_the_original_error(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch, caplog,
    ):
        from docsgpt import worker

        store = SwallowingStore()
        store.seed("old A", "https://docs.x.io/a", "a.md")
        store.fail_on = lambda text, metadata: text == "boom"
        real_add = store.add_chunk

        def add_and_mark(text, metadata=None):
            chunk_id = real_add(text, metadata)
            store.fail_ids.add(chunk_id)  # the rollback can't delete it
            return chunk_id

        store.add_chunk = add_and_mark
        self._use(monkeypatch, store)
        pipeline["pages"]["https://docs.x.io/a"] = "first\n\nboom"

        with pytest.raises(RuntimeError, match="embedding provider unavailable"):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert "roll back" in caplog.text
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}


@pytest.mark.unit
class TestAddOnALegacyTree:
    def test_a_new_page_never_takes_a_legacy_leafs_path(self, pg_conn, patch_worker_db, task_self, pipeline):
        from docsgpt import worker

        store = pipeline["store"]
        store.chunks.clear()
        store.seed("legacy html page", "https://docs.x.io/a.html", "a.md")
        legacy_leaf = {"type": "text/markdown", "size_bytes": 10, "token_count": 40}  # before leaves had a url
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="url", remote_data=["https://docs.x.io/a.html", "https://docs.x.io/a"],
            directory_structure={"a.md": legacy_leaf},
        )
        pipeline["pages"]["https://docs.x.io/a"] = "New page A"

        worker.website_pages_worker(task_self, str(src["id"]), USER, "add", urls=["https://docs.x.io/a"])

        tree = _tree(pg_conn, src)
        assert tree["a.md"] == legacy_leaf
        assert tree["a-2.md"]["url"] == "https://docs.x.io/a"
        assert store.texts_for("https://docs.x.io/a.html") == ["legacy html page"]


@pytest.mark.unit
class TestTheTreeAndTheChunksAgree:
    """New chunks, then the tree, then the old chunks: no page loses its content and no chunk is unlisted."""

    def test_the_old_copy_goes_only_once_the_tree_lists_the_new_one(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        store = pipeline["store"]
        real_delete = store.delete_chunks
        fetched_at_delete = []

        def delete_and_look(chunk_ids):
            fetched_at_delete.append(_tree(pg_conn, source)["a.md"]["fetched_at"])
            return real_delete(chunk_ids)

        store.delete_chunks = delete_and_look
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert fetched_at_delete and OLD not in fetched_at_delete
        assert store.texts_for("https://docs.x.io/a") == ["New A"]

    @pytest.mark.parametrize("operation", ["refresh", "add"])
    def test_a_failed_tree_write_takes_the_new_chunks_out_and_keeps_the_old(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch, operation,
    ):
        from docsgpt import worker

        def db_down(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(worker.SourcesRepository, "get_for_update", db_down)
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        pipeline["pages"]["https://docs.x.io/b"] = "New B"
        store = pipeline["store"]

        with pytest.raises(RuntimeError, match="database unavailable"):
            if operation == "refresh":
                worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")
            else:
                worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert store.texts_for("https://docs.x.io/b") == []
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_a_page_is_added_in_one_batch(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B one\n\nB two\n\nB three"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert [entry for entry in pipeline["store"].log if entry[0] == "batch"] == [("batch", 3)]

    def test_a_redirected_refresh_replaces_the_page_it_was_asked_for(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        # Pages are stored under the address they redirect to.
        from docsgpt import worker
        from docsgpt.parser.remote import web_loader

        def redirected(self, inputs):
            return [Document("Moved A", extra_info={"source": "https://docs.x.io/new-a", "title": "A"})]

        monkeypatch.setattr(web_loader.WebLoader, "load_data", redirected)
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        tree = _tree(pg_conn, source)
        assert list(tree) == ["a.md"] and tree["a.md"]["url"] == "https://docs.x.io/new-a"
        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == [] and store.texts_for("https://docs.x.io/new-a") == ["Moved A"]


def _redirecting_loader(monkeypatch, pipeline, redirects, requested_key=True):
    """``WebLoader.load_data`` following ``redirects`` (asked address to final one).

    With ``requested_key``, a redirected page carries ``extra_info["requested_url"]``
    as the parser sets it; without, it carries only its final address (an older parser).
    """
    from docsgpt.parser.remote import web_loader

    def load(self, inputs):
        pipeline["fetch_calls"].append((list(inputs), self.keep_links))
        docs = []
        for url in inputs:
            final = redirects.get(url, url)
            extra = {"source": final, "title": "T"}
            if final != url and requested_key:
                extra["requested_url"] = url
            docs.append(Document(f"text of {final}", extra_info=extra))
        return docs

    monkeypatch.setattr(web_loader.WebLoader, "load_data", load)


@pytest.mark.unit
class TestRedirectedPages:
    """A redirected page's leaf keeps the address it was asked for (``requested_url``)."""

    @pytest.mark.parametrize("parser_sets_it", [True, False])
    def test_an_added_page_that_redirects_keeps_its_requested_address(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch, parser_sets_it,
    ):
        from docsgpt import worker

        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"}, parser_sets_it)
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/old"])

        leaf = _tree(pg_conn, source)["new.md"]
        assert leaf["url"] == "https://docs.x.io/new" and leaf["requested_url"] == "https://docs.x.io/old"

    def test_a_page_that_does_not_redirect_has_no_requested_address(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert "requested_url" not in _tree(pg_conn, source)["b.md"]

    def test_a_refresh_fetches_the_requested_address_and_keeps_it(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        # As a sync does: the entry is /old, so /old is what is fetched.
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/old", "mode": "page"}]},
            directory_structure={"new.md": {**_leaf("https://docs.x.io/new", 4), "requested_url": "https://docs.x.io/old"}},
        )
        pipeline["store"].seed("old new", "https://docs.x.io/new", "new.md")
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"}, False)
        worker.website_pages_worker(
            task_self, str(src["id"]), USER, "refresh", file_path="new.md", url="https://docs.x.io/old",
        )

        assert pipeline["fetch_calls"][-1][0] == ["https://docs.x.io/old"]
        tree = _tree(pg_conn, src)
        assert list(tree) == ["new.md"]
        assert tree["new.md"]["requested_url"] == "https://docs.x.io/old" and tree["new.md"]["fetched_at"] != OLD
        assert pipeline["store"].texts_for("https://docs.x.io/new") == ["text of https://docs.x.io/new"]

    def test_re_adding_the_requested_address_replaces_the_page_in_place(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        from docsgpt import worker

        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/old", "mode": "page"}]},
            directory_structure={"moved.md": {**_leaf("https://docs.x.io/new", 4), "requested_url": "https://docs.x.io/old"}},
        )
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"})
        worker.website_pages_worker(task_self, str(src["id"]), USER, "add", urls=["https://docs.x.io/old"])

        tree = _tree(pg_conn, src)
        assert list(tree) == ["moved.md"] and tree["moved.md"]["fetched_at"] != OLD

    def test_a_removal_finds_the_page_by_its_requested_address(self, pg_conn, patch_worker_db, task_self, pipeline):
        # A sync since the route ran stored the page as fetched from /old, which no longer redirects.
        from docsgpt import worker

        store = pipeline["store"]
        store.seed("old page", "https://docs.x.io/old", "old.md")
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
            directory_structure={"old.md": _leaf("https://docs.x.io/old", 4), "a.md": _leaf("https://docs.x.io/a", 40)},
        )

        result = worker.website_pages_worker(task_self, str(src["id"]), USER, "remove", pages=[
            {"path": "new.md", "url": "https://docs.x.io/new", "requested_url": "https://docs.x.io/old"},
        ])

        assert result["pages"] == 1
        assert list(_tree(pg_conn, src)) == ["a.md"]
        assert store.texts_for("https://docs.x.io/old") == []

    def test_a_removal_by_the_requested_address_finds_the_redirected_leaf(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        from docsgpt import worker

        store = pipeline["store"]
        store.seed("new page", "https://docs.x.io/new", "new.md")
        src = SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={"entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
            directory_structure={
                "new.md": {**_leaf("https://docs.x.io/new", 4), "requested_url": "https://docs.x.io/old"},
                "a.md": _leaf("https://docs.x.io/a", 40),
            },
        )

        worker.website_pages_worker(
            task_self, str(src["id"]), USER, "remove", pages=[{"path": "x.md", "url": "https://docs.x.io/old"}],
        )

        assert list(_tree(pg_conn, src)) == ["a.md"]
        assert store.texts_for("https://docs.x.io/new") == []


@pytest.mark.unit
class TestARefreshStaysInScope:
    """A crawled page that now leads outside its site's scope, or to a skipped address, leaves as a sync drops it."""

    @pytest.fixture
    def crawled(self, pg_conn, pipeline):
        pipeline["store"].seed("old docs a", "https://docs.x.io/docs/a", "docs/a.md")
        return SourcesRepository(pg_conn).create(
            "Docs", user_id=USER, type="website",
            remote_data={
                "entries": [{"url": "https://docs.x.io/docs/", "mode": "site", "path_prefix": "/docs/"}],
                "skip": ["https://docs.x.io/docs/private/*"],
            },
            directory_structure={"docs": {
                "a.md": _leaf("https://docs.x.io/docs/a", 4), "b.md": _leaf("https://docs.x.io/docs/b", 2),
            }},
        )

    @pytest.mark.parametrize("destination", ["https://docs.x.io/blog/a", "https://docs.x.io/docs/private/a"])
    def test_a_page_redirected_out_of_scope_is_removed_not_stored(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch, destination,
    ):
        from docsgpt import worker

        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": destination})
        with pytest.raises(ValueError, match="outside"):
            worker.website_pages_worker(
                task_self, str(crawled["id"]), USER, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a",
            )

        store = pipeline["store"]
        assert store.texts_for(destination) == [] and store.texts_for("https://docs.x.io/docs/a") == []
        assert _tree(pg_conn, crawled) == {"docs": {"b.md": _leaf("https://docs.x.io/docs/b", 2)}}
        kind, payload = pipeline["events"][-1]
        assert kind == "source.ingest.failed" and payload["reason"] == "out_of_scope"

    def test_a_page_redirected_within_scope_is_stored(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch,
    ):
        from docsgpt import worker

        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": "https://docs.x.io/docs/a2"})
        worker.website_pages_worker(
            task_self, str(crawled["id"]), USER, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a",
        )

        assert _tree(pg_conn, crawled)["docs"]["a.md"]["url"] == "https://docs.x.io/docs/a2"

    def test_a_page_entry_is_refreshed_wherever_it_leads(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch,
    ):
        # A page listed by address is fetched whatever the sites' scope: a sync keeps it too.
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(crawled["id"]), USER, {"remote_data": {
            "entries": [
                {"url": "https://docs.x.io/docs/", "mode": "site", "path_prefix": "/docs/"},
                {"url": "https://docs.x.io/docs/a", "mode": "page"},
            ],
        }})
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": "https://docs.x.io/blog/a"})
        worker.website_pages_worker(
            task_self, str(crawled["id"]), USER, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a",
        )

        assert _tree(pg_conn, crawled)["docs"]["a.md"]["url"] == "https://docs.x.io/blog/a"


@pytest.mark.unit
class TestThePageCount:
    """Settings show ``metadata.website.pages``; page changes keep it to the tree."""

    def _with_report(self, pg_conn, src):
        SourcesRepository(pg_conn).set_metadata_key(
            str(src["id"]), USER, "website", {"pages": 99, "sites": [], "fetched_at": OLD},
        )

    def test_an_add_counts_the_new_page(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        self._with_report(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        report = _source_row(pg_conn, source)["metadata"]["website"]
        assert report["pages"] == 2 and report["fetched_at"] == OLD

    def test_a_removal_counts_the_pages_left(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        self._with_report(pg_conn, two_pages)
        worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md"])

        assert _source_row(pg_conn, two_pages)["metadata"]["website"]["pages"] == 1

    def test_a_source_without_a_report_gets_none(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert "website" not in (_source_row(pg_conn, source)["metadata"] or {})


@pytest.mark.unit
class TestAStoreWithoutChunkEdits:
    def test_fails_clearly_instead_of_reporting_success(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        from docsgpt import worker

        monkeypatch.setattr("docsgpt.worker.settings.VECTOR_STORE", "elasticsearch")
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="sync"):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert pipeline["fetch_calls"] == []
        assert pipeline["events"][-1][0] == "source.ingest.failed"


@pytest.mark.unit
class TestConcurrentChanges:
    """Another change lands while the pages are fetched; neither is lost."""

    def test_a_tree_and_config_change_mid_task_survive(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        repo = SourcesRepository(pg_conn)
        changed_config = {"entries": [{"url": "https://docs.x.io/a", "mode": "page"}], "skip": ["https://docs.x.io/z"]}

        def other_change():
            tree = dict(_tree(pg_conn, source))
            tree["z.md"] = _leaf("https://docs.x.io/z", 3)
            repo.update(str(source["id"]), USER, {"directory_structure": tree, "remote_data": changed_config})

        pipeline["during_fetch"].append(other_change)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        row = _source_row(pg_conn, source)
        assert sorted(row["directory_structure"]) == ["a.md", "b.md", "z.md"]
        assert row["remote_data"]["skip"] == ["https://docs.x.io/z"]
        assert int(row["tokens"]) == 40 + 3 + row["directory_structure"]["b.md"]["token_count"]

    def test_an_add_queued_before_a_removal_does_not_bring_the_page_back(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        # The removal took the lock first: /b left the config before the add ran.
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"remote_data": {
            "entries": [{"url": "https://docs.x.io/a", "mode": "page"}, {"url": "https://docs.x.io/c", "mode": "page"}],
        }})
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        pipeline["pages"]["https://docs.x.io/c#top"] = "C"
        result = worker.website_pages_worker(
            task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b", "https://docs.x.io/c#top"],
        )

        assert result["pages"] == 1
        assert pipeline["fetch_calls"][0][0] == ["https://docs.x.io/c#top"]
        assert sorted(_tree(pg_conn, source)) == ["a.md", "c.md"]

    def test_an_add_whose_pages_all_left_the_config_changes_nothing(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"remote_data": {
            "entries": [{"url": "https://docs.x.io/a", "mode": "page"}],
        }})
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        result = worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert result["pages"] == 0
        assert pipeline["fetch_calls"] == []
        assert list(_tree(pg_conn, source)) == ["a.md"]
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    def test_a_page_removed_mid_refresh_is_not_brought_back(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        repo = SourcesRepository(pg_conn)
        pipeline["during_fetch"].append(
            lambda: repo.update(str(source["id"]), USER, {"directory_structure": {}, "tokens": "0"})
        )
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert _tree(pg_conn, source) == {}
        assert pipeline["store"].texts_for("https://docs.x.io/a") == []

    def test_a_source_converted_to_a_wiki_is_left_alone(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"config": {"kind": "wiki"}})
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="wiki"):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert pipeline["fetch_calls"] == []
        assert pipeline["store"].log == []

    def test_a_wiki_conversion_mid_task_drops_the_new_chunks(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        repo = SourcesRepository(pg_conn)
        pipeline["during_fetch"].append(lambda: repo.update(str(source["id"]), USER, {"config": {"kind": "wiki"}}))
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="wiki"):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert pipeline["store"].texts_for("https://docs.x.io/b") == []
        assert "b.md" not in _tree(pg_conn, source)

    def test_runs_holding_the_source_index_lock(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        from docsgpt import worker

        held = []

        @contextmanager
        def fake_lock(source_id, **kwargs):
            held.append(source_id)
            yield
            held.append("released")

        monkeypatch.setattr(worker, "source_index_lock", fake_lock)
        pipeline["during_fetch"].append(lambda: held.append("fetching"))
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert held == [str(source["id"]), "fetching", "released"]


class FakeGraph:
    """Records ``GraphStore.delete_chunks`` calls; ``fail`` makes them raise."""

    def __init__(self):
        self.deleted = []
        self.reset = []
        self.fail = False

    def delete_chunks(self, source_id, chunk_ids):
        if self.fail:
            raise RuntimeError("graph database unavailable")
        self.deleted.append((source_id, list(chunk_ids)))
        return {"nodes": 0, "edges": 0}

    def delete_by_source(self, source_id):
        self.reset.append(source_id)


@pytest.fixture
def graph(monkeypatch):
    """A graphrag deployment: GraphRAG available, the graph store and extraction task faked."""
    from docsgpt.api.user import tasks
    from docsgpt.graphrag import store as graph_store

    fake = FakeGraph()
    queued = []
    monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
    monkeypatch.setattr(graph_store, "GraphStore", lambda *a, **k: fake)
    monkeypatch.setattr(tasks.extract_graph, "delay", lambda *a, **k: queued.append((a, k)))
    return {"store": fake, "queued": queued}


def _make_graph(pg_conn, source):
    SourcesRepository(pg_conn).update(str(source["id"]), USER, {"config": {"kind": "graphrag"}})


@pytest.mark.unit
class TestAGraphSource:
    """A page change updates the graph by chunk instead of rebuilding it."""

    def test_a_refresh_drops_the_old_chunks_and_extracts_only_the_new(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        from docsgpt import worker

        _make_graph(pg_conn, source)
        task_self.request.id = "task-g1"
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        # No reset: the rest of the graph stays, and only the page's new chunks are billed.
        assert graph["store"].reset == []
        [(args, kwargs)] = graph["queued"]
        assert args == (str(source["id"]), USER)
        assert "task-g1" in kwargs["idempotency_key"]
        new_ids = [cid for cid, c in pipeline["store"].chunks.items() if c["metadata"]["source"] == "https://docs.x.io/a"]
        assert kwargs["chunk_ids"] == new_ids

    def test_an_added_page_is_extracted(self, pg_conn, patch_worker_db, task_self, source, pipeline, graph):
        from docsgpt import worker

        _make_graph(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/b"])

        assert graph["store"].deleted == []
        assert len(graph["queued"]) == 1

    def test_a_removal_drops_the_pages_chunks_without_extracting(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        from docsgpt import worker

        _make_graph(pg_conn, source)
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"directory_structure": {
            "a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 1),
        }})
        worker.website_pages_worker(task_self, str(source["id"]), USER, "remove", file_paths=["a.md"])

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        assert graph["queued"] == []

    def test_a_graph_failure_leaves_the_page_change_done(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        from docsgpt import worker

        _make_graph(pg_conn, source)
        graph["store"].fail = True
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        result = worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert result["pages"] == 1
        assert pipeline["store"].texts_for("https://docs.x.io/a") == ["New A"]
        # The graph is left as it was: nothing extracted on top of stale entries.
        assert graph["queued"] == []
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    def test_a_classic_source_has_no_graph_to_update(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert graph["store"].deleted == [] and graph["queued"] == []

    def test_nothing_happens_when_graphrag_is_unavailable(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch,
    ):
        from docsgpt import worker

        monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: False)
        _make_graph(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert graph["store"].deleted == [] and graph["queued"] == []

    def test_a_removal_whose_tree_write_fails_still_drops_the_graph_entries(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch,
    ):
        # The chunks are gone once the delete succeeds, so a retry finds none
        # to name: the graph must drop them before the tree write can fail.
        from docsgpt import worker

        _make_graph(pg_conn, source)
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"directory_structure": {
            "a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 1),
        }})
        real_update = SourcesRepository.update
        calls = {"n": 0}

        def flaky_update(self, sid, user, fields):
            if "directory_structure" in fields and calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("tree write failed")
            return real_update(self, sid, user, fields)

        monkeypatch.setattr(SourcesRepository, "update", flaky_update)
        pages = [{"path": "a.md", "url": "https://docs.x.io/a"}]
        with pytest.raises(RuntimeError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "remove", pages=pages)
        worker.website_pages_worker(task_self, str(source["id"]), USER, "remove", pages=pages)

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        assert list(_tree(pg_conn, source)) == ["b.md"]

    def test_a_removal_whose_delete_fails_part_way_drops_the_deleted_chunks_from_the_graph(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        from docsgpt import worker

        _make_graph(pg_conn, source)
        store = pipeline["store"]
        real_delete = store.delete_chunks

        def delete_one(chunk_ids):
            real_delete(list(chunk_ids)[:1])
            return 1

        store.delete_chunks = delete_one
        with pytest.raises(RuntimeError, match="could not be deleted"):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "remove", file_paths=["a.md"])

        assert graph["store"].deleted == [(str(source["id"]), ["old-1"])]
        assert "a.md" in _tree(pg_conn, source)

    def test_a_faiss_removal_whose_save_fails_keeps_the_graph(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch,
    ):
        # The loaded FAISS index dropped the chunks before its save failed; storage
        # still holds them, so the graph must not be told they are gone.
        from unittest.mock import MagicMock

        import faiss
        import numpy as np

        from docsgpt import worker
        from docsgpt.core.settings import settings
        from docsgpt.vectorstore import vector_creator
        from docsgpt.vectorstore.faiss import FaissStore

        _make_graph(pg_conn, source)
        url = "https://docs.x.io/a"
        store = FaissStore.__new__(FaissStore)
        store.source_id, store.path = str(source["id"]), f"indexes/{source['id']}"
        store.index = faiss.IndexFlatL2(4)
        store.index.add(np.eye(3, 4, dtype=np.float32))
        store.documents = {
            "c1": {"page_content": "a", "metadata": {"source": url}},
            "c2": {"page_content": "b", "metadata": {"source": url}},
            "c3": {"page_content": "c", "metadata": {"source": "https://docs.x.io/other"}},
        }
        store.index_to_docstore_id = {0: "c1", 1: "c2", 2: "c3"}
        store.storage = MagicMock()
        store.storage.save_file.side_effect = OSError("S3 PutObject failed")
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)

        with pytest.raises(OSError):
            worker.website_pages_worker(
                task_self, str(source["id"]), USER, "remove", pages=[{"path": "a.md", "url": url}],
            )

        assert graph["store"].deleted == []
        assert sorted(store.chunk_ids_by_source_paths([url])) == ["c1", "c2"]
        assert "a.md" in _tree(pg_conn, source)


@pytest.mark.unit
class TestAFailureBeforeTheRun:
    def test_a_failed_first_lookup_still_sends_a_terminal_event(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        # The UI waits on the task id from the route; it must hear that the task ended.
        from docsgpt import worker

        task_self.request.id = "task-r5"

        class Boom:
            def __enter__(self):
                raise RuntimeError("database unavailable")

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(worker, "db_readonly", lambda: Boom())
        source_id = "8c3c8d1e-7a39-4c3f-9d0e-2f1f6f0f9a11"
        with pytest.raises(RuntimeError):
            worker.website_pages_worker(task_self, source_id, USER, "add", urls=["https://x/y"])

        [(kind, payload)] = pipeline["events"]
        assert kind == "source.ingest.failed"
        assert payload["source_id"] == source_id and payload["task_id"] == "task-r5"
        assert payload["operation"] == "add_pages" and "database unavailable" in payload["error"]

    def test_a_source_deleted_before_the_run_sends_a_terminal_event(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        from docsgpt import worker

        with pytest.raises(ValueError, match="not found"):
            worker.website_pages_worker(
                task_self, "8c3c8d1e-7a39-4c3f-9d0e-2f1f6f0f9a11", USER, "remove", pages=[{"path": "a.md"}],
            )

        assert [kind for kind, _ in pipeline["events"]] == ["source.ingest.failed"]
        assert pipeline["events"][0][1]["operation"] == "remove_pages"
