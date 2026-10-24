"""Tests for ``website_pages_worker``: adding, refreshing and removing pages of a Website source."""

from unittest.mock import MagicMock

import pytest

from docsgpt import worker
from docsgpt.api.user import tasks
from docsgpt.core.settings import settings
from docsgpt.parser.remote import web_loader
from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository
from docsgpt.vectorstore import vector_creator
from docsgpt.vectorstore.index_lock import SourceBusy

USER = "u-pages"
EDITOR = "editor-1"
OLD = "2026-01-01T00:00:00+00:00"
# A Website crawling one site.
SITE = {"entries": [{"url": "https://docs.x.io/", "mode": "site"}]}
# Leaves from before leaves carried their address (main's crawler trees).
LEGACY = {"type": "text/markdown", "size_bytes": 10, "token_count": 4}


def _leaf(url, tokens, title="Old"):
    return {
        "type": "text/markdown", "size_bytes": 10, "token_count": tokens, "url": url, "title": title, "fetched_at": OLD,
    }


def _listing(*urls):
    """A Website config listing ``urls`` as page entries."""
    return {"entries": [{"url": url, "mode": "page"} for url in urls]}


def _website(pg_conn, tree, remote_data=None, **fields):
    """A source owned by ``USER``: a Website crawling docs.x.io, unless ``remote_data`` and ``type`` say otherwise."""
    fields.setdefault("type", "website")
    return SourcesRepository(pg_conn).create(
        "Docs", user_id=USER, remote_data=SITE if remote_data is None else remote_data, directory_structure=tree,
        **fields,
    )


def run(task_self, source, operation, **kwargs):
    return worker.website_pages_worker(task_self, str(source["id"]), USER, operation, **kwargs)


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

    def get_chunks(self):
        return [{"doc_id": cid, "text": c["text"], "metadata": dict(c["metadata"])} for cid, c in self.chunks.items()]

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
    return _website(
        pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40)},
        {**_listing(*(f"https://docs.x.io/{page}" for page in LISTED)), "keep_links": True}, tokens="40",
    )


@pytest.fixture
def pipeline(monkeypatch, published):
    """A fake store, a fake web fetch and captured events."""
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
    return {"store": store, "pages": pages, "fetch_calls": fetch_calls, "events": published, "during_fetch": during_fetch}


@pytest.fixture
def two_pages(pg_conn, pipeline):
    """A source with pages ``a.md`` and ``guide/b.md``, each with its chunks."""
    pipeline["store"].seed("B one", "https://docs.x.io/guide/b", "guide/b.md")
    return _website(
        pg_conn,
        {"a.md": _leaf("https://docs.x.io/a", 40), "guide": {"b.md": _leaf("https://docs.x.io/guide/b", 9)}},
        tokens="49",
    )


A = {"path": "a.md", "url": "https://docs.x.io/a"}
B = {"path": "guide/b.md", "url": "https://docs.x.io/guide/b"}


def _source_row(pg_conn, source):
    return SourcesRepository(pg_conn).get(str(source["id"]), USER)


def _tree(pg_conn, source):
    return _source_row(pg_conn, source)["directory_structure"]


def _unlist(pg_conn, source, *urls):
    """Drop page entries from the config, as the removal route does before it queues the task."""
    config = dict(_source_row(pg_conn, source)["remote_data"])
    config["entries"] = [e for e in config["entries"] if e["url"] not in urls]
    SourcesRepository(pg_conn).update(str(source["id"]), USER, {"remote_data": config})


def _redirecting_loader(monkeypatch, pipeline, redirects):
    """``WebLoader.load_data`` following ``redirects`` (asked address to final one), as the loader notes them."""

    def load(self, inputs):
        pipeline["fetch_calls"].append((list(inputs), self.keep_links))
        docs = []
        for url in inputs:
            final = redirects.get(url, url)
            extra = {"source": final, "title": "T", **({"requested_urls": [url]} if final != url else {})}
            docs.append(Document(f"text of {final}", extra_info=extra))
        return docs

    monkeypatch.setattr(web_loader.WebLoader, "load_data", load)


@pytest.mark.unit
class TestAddPages:
    def test_appends_pages_without_touching_the_others(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/guide/b"] = "# B\n\nBody of page B."
        result = run(task_self, source, "add", urls=["https://docs.x.io/guide/b"])

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

        assert pipeline["events"].kinds() == ["source.ingest.queued", "source.ingest.completed"]
        assert pipeline["events"][-1][1]["operation"] == "add_pages"

    def test_pages_are_chunked_with_the_sources_settings(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        chunking = {"strategy": "recursive", "max_tokens": 700, "min_tokens": 30, "chunk_overlap": 120}
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"config": {"chunking": chunking}})
        made = []
        monkeypatch.setattr(
            worker.ChunkerCreator, "create_chunker", lambda *a, **k: made.append(k) or ParagraphChunker(),
        )
        pipeline["pages"]["https://docs.x.io/guide/b"] = "# B\n\nBody of page B."

        run(task_self, source, "add", urls=["https://docs.x.io/guide/b"])

        [kwargs] = made
        assert {key: kwargs[key] for key in ("max_tokens", "min_tokens", "chunk_overlap")} == {
            "max_tokens": 700, "min_tokens": 30, "chunk_overlap": 120,
        }

    def test_pages_that_could_not_be_fetched_are_named_in_the_result(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        pipeline["pages"]["https://docs.x.io/b"] = "B one\n\nB two"
        # /c is listed in the config but its fetch yields nothing (404, timeout, refused, empty).
        result = run(task_self, source, "add", urls=["https://docs.x.io/b", "https://docs.x.io/c"])

        assert result == {"status": "ok", "pages": 1, "paths": ["b.md"], "failed_pages": ["https://docs.x.io/c"]}
        kind, payload = pipeline["events"][-1]
        assert kind == "source.ingest.completed" and payload["failed_pages"] == ["https://docs.x.io/c"]
        assert "c.md" not in _tree(pg_conn, source)

    def test_a_full_add_names_no_failed_pages(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        result = run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert result == {"status": "ok", "pages": 1, "paths": ["b.md"]}
        assert "failed_pages" not in pipeline["events"][-1][1]

    def test_a_redirected_page_counts_as_fetched(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"})
        result = run(task_self, source, "add", urls=["https://docs.x.io/old", "https://docs.x.io/b"])

        assert "failed_pages" not in result and result["pages"] == 2

    def test_events_carry_the_task_id(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        # The UI matches the events to the request that queued the task.
        task_self.request.id = "task-9"
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])
        with pytest.raises(ValueError):
            run(task_self, source, "add", urls=["https://docs.x.io/gone"])

        kinds = pipeline["events"].kinds()
        assert kinds[-1] == "source.ingest.failed" and "source.ingest.completed" in kinds
        assert all(payload["task_id"] == "task-9" for _, payload in pipeline["events"])

    def test_adding_a_page_already_there_replaces_it(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/a"] = "# A\n\nThe new text of page A."
        run(task_self, source, "add", urls=["https://docs.x.io/a"])

        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == ["# A", "The new text of page A."]
        # The new copy is stored (in one batch) before the old one goes.
        assert [kind for kind, _ in store.log] == ["batch", "add", "add", "delete", "delete"]
        tree = _tree(pg_conn, source)
        assert list(tree) == ["a.md"]
        assert tree["a.md"]["fetched_at"] != OLD

    def test_a_page_that_cannot_be_fetched_fails_and_changes_nothing(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        with pytest.raises(ValueError):
            run(task_self, source, "add", urls=["https://docs.x.io/gone"])

        assert pipeline["store"].log == []
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_an_address_variant_of_a_page_replaces_it_and_its_chunks(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # ``/docs/`` and ``/docs`` are one page: adding the second must not
        # leave the first's chunks searchable with no tree entry to remove.
        src = _website(
            pg_conn, {"docs.md": _leaf("https://docs.x.io/docs/", 10)},
            {"entries": [*SITE["entries"], {"url": "https://docs.x.io/docs#intro", "mode": "page"}]}, tokens="10",
        )
        store = pipeline["store"]
        store.seed("old docs", "https://docs.x.io/docs/", "docs.md")
        pipeline["pages"]["https://docs.x.io/docs#intro"] = "New docs"
        run(task_self, src, "add", urls=["https://docs.x.io/docs#intro"])

        assert store.texts_for("https://docs.x.io/docs/") == []
        assert store.texts_for("https://docs.x.io/docs#intro") == ["New docs"]
        tree = _tree(pg_conn, src)
        assert list(tree) == ["docs.md"]
        assert tree["docs.md"]["url"] == "https://docs.x.io/docs#intro"

    def test_a_different_page_on_a_taken_path_gets_its_own_path(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # ``/docs`` and ``/docs.html`` are different pages that both map to ``docs.md``.
        src = _website(
            pg_conn, {"docs.md": _leaf("https://docs.x.io/docs", 10), "docs-2.md": _leaf("https://docs.x.io/d2", 1)},
            _listing("https://docs.x.io/docs", "https://docs.x.io/docs.html"), tokens="11",
        )
        store = pipeline["store"]
        store.seed("old docs", "https://docs.x.io/docs", "docs.md")
        pipeline["pages"]["https://docs.x.io/docs.html"] = "HTML docs"
        run(task_self, src, "add", urls=["https://docs.x.io/docs.html"])

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
        pipeline["pages"]["https://docs.x.io/b"] = "B one\n\nB two"
        pipeline["pages"]["https://docs.x.io/c"] = "C one\n\nC two"
        store = pipeline["store"]
        store.fail_on = lambda text, metadata: text == "C two"

        with pytest.raises(RuntimeError):
            run(task_self, source, "add", urls=["https://docs.x.io/b", "https://docs.x.io/c"])

        assert store.texts_for("https://docs.x.io/b") == ["B one", "B two"]
        assert store.texts_for("https://docs.x.io/c") == []
        tree = _tree(pg_conn, source)
        assert sorted(tree) == ["a.md", "b.md"]
        assert int(_source_row(pg_conn, source)["tokens"]) == 40 + tree["b.md"]["token_count"]
        assert pipeline["events"][-1][0] == "source.ingest.failed"


@pytest.mark.unit
class TestRefreshPage:
    def test_refetches_one_page_in_place(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/a"] = "# A\n\nRefreshed text for page A."
        result = run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert result["pages"] == 1
        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == ["# A", "Refreshed text for page A."]
        assert all(c["metadata"]["file_path"] == "a.md" for c in store.chunks.values())
        leaf = _tree(pg_conn, source)["a.md"]
        assert leaf["title"] == "Title a"
        assert leaf["fetched_at"] != OLD

    def test_a_failed_fetch_keeps_the_old_content(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        with pytest.raises(ValueError):
            run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert pipeline["store"].texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert _tree(pg_conn, source)["a.md"]["fetched_at"] == OLD

    def test_an_embedding_failure_half_way_keeps_the_old_content(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        pipeline["pages"]["https://docs.x.io/a"] = "New one\n\nNew two"
        store = pipeline["store"]
        store.fail_on = lambda text, metadata: text == "New two"

        with pytest.raises(RuntimeError):
            run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        # The half-stored new copy is taken out again; the old one was never touched.
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_the_page_is_found_by_its_address_wherever_a_sync_moved_it(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        # The route saw /a at a.md; a sync queued before re-derived the tree, so a.md holds /b now.
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"directory_structure": {
            "a.md": _leaf("https://docs.x.io/b", 5), "a-2.md": _leaf("https://docs.x.io/a", 40),
        }})
        pipeline["pages"]["https://docs.x.io/a"] = "fresh A"
        pipeline["pages"]["https://docs.x.io/b"] = "fresh B"
        run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert pipeline["fetch_calls"][0][0] == ["https://docs.x.io/a"]
        tree = _tree(pg_conn, source)
        assert tree["a.md"] == _leaf("https://docs.x.io/b", 5)
        assert tree["a-2.md"]["fetched_at"] != OLD

    @pytest.mark.parametrize("url", ["https://docs.x.io/gone", None])
    def test_a_page_that_left_the_tree_is_an_error_not_another_page(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, url,
    ):
        pipeline["pages"]["https://docs.x.io/a"] = "fresh A"
        with pytest.raises(ValueError, match="no longer"):
            run(task_self, source, "refresh", file_path="a.md", url=url)

        assert pipeline["fetch_calls"] == []


@pytest.mark.unit
class TestRemovePages:
    def test_deletes_the_pages_chunks_then_their_entries(
        self, pg_conn, patch_worker_db, task_self, two_pages, pipeline,
    ):
        task_self.request.id = "remove-1"
        store = pipeline["store"]
        trees_at_delete = []
        real_delete = store.delete_chunks

        def delete_and_look(chunk_ids):
            # The page is still listed while its chunks go: the list changes last.
            trees_at_delete.append(_tree(pg_conn, two_pages))
            return real_delete(chunk_ids)

        store.delete_chunks = delete_and_look
        result = run(task_self, two_pages, "remove", pages=[B])

        assert result == {"status": "ok", "pages": 1, "paths": ["guide/b.md"]}
        assert store.texts_for("https://docs.x.io/guide/b") == []
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert "b.md" in trees_at_delete[0]["guide"]
        row = _source_row(pg_conn, two_pages)
        assert row["directory_structure"] == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert row["tokens"] == "40"
        assert pipeline["events"].kinds() == ["source.ingest.queued", "source.ingest.completed"]
        assert all(payload["task_id"] == "remove-1" for _, payload in pipeline["events"])
        assert pipeline["events"][-1][1]["operation"] == "remove_pages"
        assert pipeline["fetch_calls"] == []

    def test_a_folder_goes_in_one_delete(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        store = pipeline["store"]
        calls = []
        real_delete = store.delete_chunks
        store.delete_chunks = lambda ids: calls.append(list(ids)) or real_delete(ids)
        run(task_self, two_pages, "remove", pages=[A, B])

        assert len(calls) == 1 and len(calls[0]) == 3
        assert store.chunks == {}
        assert _tree(pg_conn, two_pages) == {}

    def test_pages_already_gone_are_ignored(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # A retried task, or a sync that rebuilt the tree meanwhile.
        result = run(task_self, two_pages, "remove", pages=[{"path": "gone.md", "url": "https://docs.x.io/gone"}])

        assert result["pages"] == 0
        assert pipeline["store"].log == []
        assert sorted(_tree(pg_conn, two_pages)) == ["a.md", "guide"]
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    def test_a_failed_delete_leaves_the_page_listed(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        def fail(chunk_ids):
            raise RuntimeError("index unavailable")

        pipeline["store"].delete_chunks = fail
        with pytest.raises(RuntimeError):
            run(task_self, two_pages, "remove", pages=[B])

        assert pipeline["store"].texts_for("https://docs.x.io/guide/b") == ["B one"]
        row = _source_row(pg_conn, two_pages)
        assert "b.md" in row["directory_structure"]["guide"]
        assert row["tokens"] == "49"
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_a_page_added_meanwhile_is_kept(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # The tree is written on the row as it is when the chunks are gone.
        store = pipeline["store"]
        real_delete = store.delete_chunks

        def delete_then_add(chunk_ids):
            deleted = real_delete(chunk_ids)
            tree = dict(_tree(pg_conn, two_pages))
            tree["c.md"] = _leaf("https://docs.x.io/c", 3)
            SourcesRepository(pg_conn).update(str(two_pages["id"]), USER, {"directory_structure": tree})
            return deleted

        store.delete_chunks = delete_then_add
        run(task_self, two_pages, "remove", pages=[B])

        row = _source_row(pg_conn, two_pages)
        assert sorted(row["directory_structure"]) == ["a.md", "c.md"]
        assert row["tokens"] == "43"

    def test_a_busy_source_says_so_in_the_failed_event(
        self, pg_conn, patch_worker_db, task_self, two_pages, pipeline, busy_lock,
    ):
        busy_lock()
        with pytest.raises(SourceBusy):
            run(task_self, two_pages, "remove", pages=[A])

        failed = [payload for kind, payload in pipeline["events"] if kind == "source.ingest.failed"]
        assert [payload.get("reason") for payload in failed] == ["busy"]
        assert pipeline["store"].log == []


@pytest.mark.unit
class TestRemoveByAddress:
    """A removal names each page by its address too, so a path a sync re-sorted can't remove another page."""

    def test_the_page_is_found_wherever_its_path_moved(self, pg_conn, patch_worker_db, task_self, pipeline):
        store = pipeline["store"]
        store.seed("A html", "https://docs.x.io/a.html", "a-2.md")
        # The route saw /a.html at a.md; a sync then gave a.md to /a and moved /a.html to a-2.md.
        src = _website(
            pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40), "a-2.md": _leaf("https://docs.x.io/a.html", 5)},
        )

        result = run(task_self, src, "remove", pages=[{"path": "a.md", "url": "https://docs.x.io/a.html"}])

        assert result["pages"] == 1
        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert store.texts_for("https://docs.x.io/a.html") == []
        assert _tree(pg_conn, src) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_a_page_no_longer_in_the_tree_removes_nothing(self, pg_conn, patch_worker_db, task_self, pipeline):
        src = _website(pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40)}, _listing("https://docs.x.io/a"))

        result = run(task_self, src, "remove", pages=[{"path": "a.md", "url": "https://docs.x.io/a.html"}])

        assert result["pages"] == 0
        assert pipeline["store"].log == []
        assert _tree(pg_conn, src) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_an_address_variant_finds_the_page(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        run(task_self, two_pages, "remove", pages=[{"path": "guide/b.md", "url": "https://docs.x.io/guide/b#intro"}])

        assert pipeline["store"].texts_for("https://docs.x.io/guide/b") == []
        assert _tree(pg_conn, two_pages) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    @pytest.mark.parametrize("resolved", ["", "https://docs.x.io/old.html"])
    def test_a_legacy_leaf_without_an_address_is_removed_by_path(
        self, pg_conn, patch_worker_db, task_self, pipeline, resolved,
    ):
        # The route reads a legacy leaf's address from its chunks, when it can; the leaf itself has none.
        store = pipeline["store"]
        store.chunks.clear()
        store.seed("legacy page", "https://docs.x.io/old.html", "old.md")
        if resolved:
            # A chunk stored without a file_path (an older ingest) is found by that address.
            store.chunks["bare"] = {"text": "legacy page two", "metadata": {"source": resolved}}
        store.seed("other page", "https://docs.x.io/keep.html", "keep.md")
        src = _website(
            pg_conn, {"old.md": dict(LEGACY), "keep.md": dict(LEGACY)}, "https://docs.x.io/", type="crawler",
        )

        result = run(task_self, src, "remove", pages=[{"path": "old.md", "url": resolved, "requested_urls": []}])

        assert result["pages"] == 1
        assert store.texts_for("https://docs.x.io/old.html") == []
        assert store.texts_for("https://docs.x.io/keep.html") == ["other page"]
        assert list(_tree(pg_conn, src)) == ["keep.md"]

    def test_a_resolved_address_never_takes_a_leaf_that_has_one(self, pg_conn, patch_worker_db, task_self, pipeline):
        # Only a leaf without an address falls back to its path.
        src = _website(pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40)}, {"entries": []})

        result = run(task_self, src, "remove", pages=[{"path": "a.md", "url": "https://docs.x.io/zzz"}])

        assert result["pages"] == 0
        assert list(_tree(pg_conn, src)) == ["a.md"]

    def test_a_pgvector_outage_while_listing_a_legacy_leaf_keeps_the_leaf(
        self, pg_conn, patch_worker_db, monkeypatch,
    ):
        """An outage must not read as "no chunks": the leaf would go while its chunks stay."""
        from docsgpt.vectorstore.pgvector import PGVectorStore

        legacy = {"type": "text/markdown", "size_bytes": 10, "token_count": 5}
        src = _website(pg_conn, {"guide.md": dict(legacy), "intro.md": dict(legacy)}, "https://x/", type="crawler")
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
            worker._remove_web_pages(src, USER, None, [{"path": "guide.md", "url": ""}])

        assert deletes == []
        assert sorted(_tree(pg_conn, src)) == ["guide.md", "intro.md"]


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
        monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)

    def test_a_removal_fails_and_writes_nothing(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline,
                                                monkeypatch):
        store = SwallowingStore()
        store.seed("B one", "https://docs.x.io/guide/b", "guide/b.md")
        store.fail_ids = set(store.chunks)
        self._use(monkeypatch, store)

        with pytest.raises(RuntimeError, match="could not be deleted"):
            run(task_self, two_pages, "remove", pages=[B])

        assert store.texts_for("https://docs.x.io/guide/b") == ["B one"]
        assert "b.md" in _tree(pg_conn, two_pages)["guide"]
        assert pipeline["events"][-1][0] == "source.ingest.failed"

    def test_ids_already_gone_are_not_a_failure(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        # FAISS and pgvector skip an id that isn't there; one deleted meanwhile is as good as deleted.
        store = pipeline["store"]
        real_delete = store.delete_chunks

        def one_went_meanwhile(chunk_ids):
            ids = list(chunk_ids)
            store.chunks.pop(ids[0])
            return real_delete(ids)

        store.delete_chunks = one_went_meanwhile
        run(task_self, two_pages, "remove", pages=[A])

        assert "a.md" not in _tree(pg_conn, two_pages)

    def test_a_failed_rollback_still_reports_the_original_error(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch, caplog,
    ):
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
            run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert "roll back" in caplog.text
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}


@pytest.mark.unit
class TestAddOnALegacyTree:
    def test_a_new_page_never_takes_a_legacy_leafs_path(self, pg_conn, patch_worker_db, task_self, pipeline):
        store = pipeline["store"]
        store.chunks.clear()
        store.seed("legacy html page", "https://docs.x.io/a.html", "a.md")
        legacy_leaf = {"type": "text/markdown", "size_bytes": 10, "token_count": 40}
        src = _website(
            pg_conn, {"a.md": legacy_leaf}, ["https://docs.x.io/a.html", "https://docs.x.io/a"], type="url",
        )
        pipeline["pages"]["https://docs.x.io/a"] = "New page A"

        run(task_self, src, "add", urls=["https://docs.x.io/a"])

        tree = _tree(pg_conn, src)
        assert tree["a.md"] == legacy_leaf
        assert tree["a-2.md"]["url"] == "https://docs.x.io/a"
        assert store.texts_for("https://docs.x.io/a.html") == ["legacy html page"]

    def test_re_adding_a_page_a_legacy_leaf_holds_replaces_that_leaf(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # The legacy leaf has no address, but its chunks do: the page goes back on its path.
        store = pipeline["store"]
        store.chunks.clear()
        store.seed("legacy A one", "https://docs.x.io/a", "a.md")
        store.seed("legacy A two", "https://docs.x.io/a", "a.md")
        store.seed("legacy B", "https://docs.x.io/b", "b.md")
        legacy_leaf = {"type": "text/markdown", "size_bytes": 10, "token_count": 40}
        src = _website(
            pg_conn, {"a.md": dict(legacy_leaf), "b.md": dict(legacy_leaf)},
            ["https://docs.x.io/a", "https://docs.x.io/b"], type="url",
        )
        pipeline["pages"]["https://docs.x.io/a"] = "New page A"

        run(task_self, src, "add", urls=["https://docs.x.io/a"])

        tree = _tree(pg_conn, src)
        assert sorted(tree) == ["a.md", "b.md"]
        assert tree["a.md"]["url"] == "https://docs.x.io/a" and tree["b.md"] == legacy_leaf
        assert store.texts_for("https://docs.x.io/a") == ["New page A"]
        assert {c["metadata"]["file_path"] for c in store.chunks.values()} == {"a.md", "b.md"}


@pytest.mark.unit
class TestTheTreeAndTheChunksAgree:
    """New chunks, then the tree, then the old chunks: no page loses its content and no chunk is unlisted."""

    def test_the_old_copy_goes_only_once_the_tree_lists_the_new_one(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        store = pipeline["store"]
        real_delete = store.delete_chunks
        fetched_at_delete = []

        def delete_and_look(chunk_ids):
            fetched_at_delete.append(_tree(pg_conn, source)["a.md"]["fetched_at"])
            return real_delete(chunk_ids)

        store.delete_chunks = delete_and_look
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert fetched_at_delete and OLD not in fetched_at_delete
        assert store.texts_for("https://docs.x.io/a") == ["New A"]

    @pytest.mark.parametrize("operation, kwargs", [
        ("refresh", {"file_path": "a.md", "url": "https://docs.x.io/a"}),
        ("add", {"urls": ["https://docs.x.io/b"]}),
    ])
    def test_a_failed_tree_write_takes_the_new_chunks_out_and_keeps_the_old(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch, operation, kwargs,
    ):
        def db_down(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(worker.SourcesRepository, "get_for_update", db_down)
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        pipeline["pages"]["https://docs.x.io/b"] = "New B"
        store = pipeline["store"]

        with pytest.raises(RuntimeError, match="database unavailable"):
            run(task_self, source, operation, **kwargs)

        assert store.texts_for("https://docs.x.io/a") == ["old A one", "old A two"]
        assert store.texts_for("https://docs.x.io/b") == []
        assert _tree(pg_conn, source) == {"a.md": _leaf("https://docs.x.io/a", 40)}

    def test_a_redirected_refresh_replaces_the_page_it_was_asked_for(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        # Pages are stored under the address they redirect to.
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/a": "https://docs.x.io/new-a"})
        run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        tree = _tree(pg_conn, source)
        assert list(tree) == ["a.md"] and tree["a.md"]["url"] == "https://docs.x.io/new-a"
        store = pipeline["store"]
        assert store.texts_for("https://docs.x.io/a") == []
        assert store.texts_for("https://docs.x.io/new-a") == ["text of https://docs.x.io/new-a"]


@pytest.mark.unit
class TestRedirectedPages:
    """A redirected page's leaf keeps the addresses it was asked for (``requested_urls``)."""

    def test_an_added_page_that_redirects_keeps_its_requested_address(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"})
        run(task_self, source, "add", urls=["https://docs.x.io/old"])

        leaf = _tree(pg_conn, source)["new.md"]
        assert leaf["url"] == "https://docs.x.io/new" and leaf["requested_urls"] == ["https://docs.x.io/old"]
        assert "requested_url" not in leaf

    def test_a_page_that_does_not_redirect_has_no_requested_address(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert "requested_urls" not in _tree(pg_conn, source)["b.md"]

    def test_a_refresh_fetches_the_requested_address_and_keeps_it(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        # As a sync does: the entry is /old, so /old is what is fetched.
        src = _website(
            pg_conn, {"new.md": {**_leaf("https://docs.x.io/new", 4), "requested_urls": ["https://docs.x.io/old"]}},
            _listing("https://docs.x.io/old"),
        )
        pipeline["store"].seed("old new", "https://docs.x.io/new", "new.md")
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"})
        run(task_self, src, "refresh", file_path="new.md", url="https://docs.x.io/old")

        assert pipeline["fetch_calls"][-1][0] == ["https://docs.x.io/old"]
        tree = _tree(pg_conn, src)
        assert list(tree) == ["new.md"]
        assert tree["new.md"]["requested_urls"] == ["https://docs.x.io/old"] and tree["new.md"]["fetched_at"] != OLD
        assert pipeline["store"].texts_for("https://docs.x.io/new") == ["text of https://docs.x.io/new"]

    def test_re_adding_the_requested_address_replaces_the_page_in_place(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        src = _website(
            pg_conn, {"moved.md": {**_leaf("https://docs.x.io/new", 4), "requested_urls": ["https://docs.x.io/old"]}},
            _listing("https://docs.x.io/old"),
        )
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/old": "https://docs.x.io/new"})
        run(task_self, src, "add", urls=["https://docs.x.io/old"])

        tree = _tree(pg_conn, src)
        assert list(tree) == ["moved.md"] and tree["moved.md"]["fetched_at"] != OLD

    def test_a_removal_finds_the_page_by_its_requested_address(self, pg_conn, patch_worker_db, task_self, pipeline):
        # A sync since the route ran stored the page as fetched from /old, which no longer redirects.
        store = pipeline["store"]
        store.seed("old page", "https://docs.x.io/old", "old.md")
        src = _website(
            pg_conn, {"old.md": _leaf("https://docs.x.io/old", 4), "a.md": _leaf("https://docs.x.io/a", 40)},
        )

        result = run(task_self, src, "remove", pages=[
            {"path": "new.md", "url": "https://docs.x.io/new", "requested_urls": ["https://docs.x.io/old"]},
        ])

        assert result["pages"] == 1
        assert list(_tree(pg_conn, src)) == ["a.md"]
        assert store.texts_for("https://docs.x.io/old") == []

    def test_a_removal_by_the_requested_address_finds_the_redirected_leaf(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        store = pipeline["store"]
        store.seed("new page", "https://docs.x.io/new", "new.md")
        src = _website(pg_conn, {
            "new.md": {**_leaf("https://docs.x.io/new", 4), "requested_urls": ["https://docs.x.io/old"]},
            "a.md": _leaf("https://docs.x.io/a", 40),
        })

        run(task_self, src, "remove", pages=[{"path": "x.md", "url": "https://docs.x.io/old"}])

        assert list(_tree(pg_conn, src)) == ["a.md"]
        assert store.texts_for("https://docs.x.io/new") == []


ALIASED_LEAF = {
    **_leaf("https://docs.x.io/new", 4), "requested_urls": ["https://docs.x.io/old-a", "https://docs.x.io/old-b"],
}


@pytest.mark.unit
class TestAPageSeveralAddressesLeadTo:
    """Two page entries that redirect to one page: the leaf keeps both addresses (``requested_urls``)."""

    @pytest.fixture
    def aliased(self, pg_conn):
        return _website(
            pg_conn, {"other.md": _leaf("https://docs.x.io/other", 1)},
            _listing(*(f"https://docs.x.io/{p}" for p in ("other", "old-a", "old-b"))),
        )

    def _loader(self, monkeypatch, pipeline):
        def load(self, inputs):
            pipeline["fetch_calls"].append((list(inputs), self.keep_links))
            extra = {"source": "https://docs.x.io/new", "title": "T", "requested_urls": list(inputs)}
            return [Document("text new", extra_info=extra)]

        monkeypatch.setattr(web_loader.WebLoader, "load_data", load)

    def test_adding_the_second_address_merges_it_into_the_leaf(
        self, pg_conn, patch_worker_db, task_self, aliased, pipeline, monkeypatch,
    ):
        self._loader(monkeypatch, pipeline)
        run(task_self, aliased, "add", urls=["https://docs.x.io/old-a"])
        run(task_self, aliased, "add", urls=["https://docs.x.io/old-b"])

        tree = _tree(pg_conn, aliased)
        assert sorted(tree) == ["new.md", "other.md"]
        assert tree["new.md"]["requested_urls"] == ["https://docs.x.io/old-a", "https://docs.x.io/old-b"]
        assert pipeline["store"].texts_for("https://docs.x.io/new") == ["text new"]

    @pytest.mark.parametrize("alias", ["https://docs.x.io/old-a", "https://docs.x.io/old-b"])
    def test_a_removal_by_any_address_finds_the_page(
        self, pg_conn, patch_worker_db, task_self, aliased, pipeline, alias,
    ):
        SourcesRepository(pg_conn).update(str(aliased["id"]), USER, {"directory_structure": {
            "other.md": _leaf("https://docs.x.io/other", 1), "new.md": ALIASED_LEAF,
        }})
        pipeline["store"].seed("new page", "https://docs.x.io/new", "new.md")
        _unlist(pg_conn, aliased, "https://docs.x.io/old-a", "https://docs.x.io/old-b")

        result = run(task_self, aliased, "remove", pages=[{"path": "gone.md", "url": alias}])

        assert result["pages"] == 1
        assert list(_tree(pg_conn, aliased)) == ["other.md"]
        assert pipeline["store"].texts_for("https://docs.x.io/new") == []

    def test_a_removal_item_carrying_every_alias_finds_a_page_stored_under_any(
        self, pg_conn, patch_worker_db, task_self, aliased, pipeline,
    ):
        # A sync since the route ran stored the page as fetched from /old-b, which no longer redirects.
        SourcesRepository(pg_conn).update(str(aliased["id"]), USER, {"directory_structure": {
            "other.md": _leaf("https://docs.x.io/other", 1), "old-b.md": _leaf("https://docs.x.io/old-b", 4),
        }})
        pipeline["store"].seed("old b", "https://docs.x.io/old-b", "old-b.md")
        _unlist(pg_conn, aliased, "https://docs.x.io/old-a", "https://docs.x.io/old-b")

        run(task_self, aliased, "remove", pages=[{
            "path": "new.md", "url": "https://docs.x.io/new",
            "requested_urls": ["https://docs.x.io/old-a", "https://docs.x.io/old-b"],
        }])

        assert list(_tree(pg_conn, aliased)) == ["other.md"]
        assert pipeline["store"].texts_for("https://docs.x.io/old-b") == []

    def test_a_refresh_of_a_page_with_several_addresses_keeps_them(
        self, pg_conn, patch_worker_db, task_self, aliased, pipeline, monkeypatch,
    ):
        SourcesRepository(pg_conn).update(str(aliased["id"]), USER, {"directory_structure": {"new.md": ALIASED_LEAF}})
        self._loader(monkeypatch, pipeline)

        run(task_self, aliased, "refresh", file_path="new.md", url="https://docs.x.io/old-b")

        assert pipeline["fetch_calls"][-1][0] == ["https://docs.x.io/old-a"]
        leaf = _tree(pg_conn, aliased)["new.md"]
        assert leaf["requested_urls"] == ["https://docs.x.io/old-a", "https://docs.x.io/old-b"]
        assert leaf["fetched_at"] != OLD


@pytest.mark.unit
class TestARefreshStaysInScope:
    """A crawled page that now leads outside its site's scope, or to a skipped address, leaves as a sync drops it."""

    SCOPE = {"url": "https://docs.x.io/docs/", "mode": "site", "path_prefix": "/docs/"}

    @pytest.fixture
    def crawled(self, pg_conn, pipeline):
        pipeline["store"].seed("old docs a", "https://docs.x.io/docs/a", "docs/a.md")
        return _website(
            pg_conn,
            {"docs": {"a.md": _leaf("https://docs.x.io/docs/a", 4), "b.md": _leaf("https://docs.x.io/docs/b", 2)}},
            {"entries": [self.SCOPE], "skip": ["https://docs.x.io/docs/private/*"]},
        )

    @pytest.mark.parametrize("destination", ["https://docs.x.io/blog/a", "https://docs.x.io/docs/private/a"])
    def test_a_page_redirected_out_of_scope_is_removed_not_stored(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch, destination,
    ):
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": destination})
        with pytest.raises(ValueError, match="outside"):
            run(task_self, crawled, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a")

        store = pipeline["store"]
        assert store.texts_for(destination) == [] and store.texts_for("https://docs.x.io/docs/a") == []
        assert _tree(pg_conn, crawled) == {"docs": {"b.md": _leaf("https://docs.x.io/docs/b", 2)}}
        kind, payload = pipeline["events"][-1]
        assert kind == "source.ingest.failed" and payload["reason"] == "out_of_scope"

    def test_a_page_redirected_within_scope_is_stored(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch,
    ):
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": "https://docs.x.io/docs/a2"})
        run(task_self, crawled, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a")

        assert _tree(pg_conn, crawled)["docs"]["a.md"]["url"] == "https://docs.x.io/docs/a2"

    def test_a_page_entry_is_refreshed_wherever_it_leads(
        self, pg_conn, patch_worker_db, task_self, crawled, pipeline, monkeypatch,
    ):
        # A page listed by address is fetched whatever the sites' scope: a sync keeps it too.
        SourcesRepository(pg_conn).update(str(crawled["id"]), USER, {"remote_data": {
            "entries": [self.SCOPE, {"url": "https://docs.x.io/docs/a", "mode": "page"}],
        }})
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/docs/a": "https://docs.x.io/blog/a"})
        run(task_self, crawled, "refresh", file_path="docs/a.md", url="https://docs.x.io/docs/a")

        assert _tree(pg_conn, crawled)["docs"]["a.md"]["url"] == "https://docs.x.io/blog/a"

    @pytest.mark.parametrize("host, kept", [("docs.x.io", True), ("other.org", False)])
    def test_a_legacy_sitemap_page_is_judged_by_its_converted_scope(
        self, pg_conn, patch_worker_db, task_self, pipeline, host, kept,
    ):
        # A legacy sitemap row syncs as its converted Website config (the
        # sitemap's host and its subdomains), so a refresh keeps what that
        # sync keeps and removes a page on another host.
        url = f"https://{host}/p"
        pipeline["store"].seed("old p", url, f"{host}/p.md")
        src = SourcesRepository(pg_conn).create(
            "Legacy sitemap", user_id=USER, type="sitemap", remote_data="https://x.io/sitemap.xml",
            directory_structure={host: {"p.md": _leaf(url, 3)}},
        )
        pipeline["pages"][url] = "new p"

        def refresh():
            worker.website_pages_worker(task_self, str(src["id"]), USER, "refresh", file_path=f"{host}/p.md", url=url)

        if kept:
            refresh()
            assert pipeline["store"].texts_for(url) == ["new p"]
            assert _tree(pg_conn, src)[host]["p.md"]["fetched_at"] != OLD
        else:
            with pytest.raises(ValueError, match="outside"):
                refresh()
            assert pipeline["store"].texts_for(url) == []
            assert _tree(pg_conn, src) == {}


@pytest.mark.unit
class TestNulBytes:
    """pgvector refuses a NUL in a chunk's text, and JSONB one in its metadata or the tree."""

    def test_an_added_page_is_stored_without_nul(self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch):
        def load(self, inputs):
            return [Document("hello\x00world", extra_info={"source": u, "title": "Ti\x00tle"}) for u in inputs]

        monkeypatch.setattr(web_loader.WebLoader, "load_data", load)
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        [chunk] = [c for c in pipeline["store"].chunks.values() if c["metadata"]["source"] == "https://docs.x.io/b"]
        assert chunk["text"] == "helloworld"
        assert chunk["metadata"]["title"] == "Title"
        assert _tree(pg_conn, source)["b.md"]["title"] == "Title"


@pytest.mark.unit
class TestTheCapHolds:
    """A queued add whose pages no longer fit (a sync filled the tree meanwhile) syncs instead of appending."""

    SITE = {"url": "https://docs.x.io/", "mode": "site", "max_pages": 50}

    @pytest.fixture
    def queued_sync(self, monkeypatch):
        task = MagicMock(name="sync_source")
        task.delay.return_value = MagicMock(id="sync-1")
        monkeypatch.setattr(tasks, "sync_source", task)
        return task

    def _full(self, pg_conn, monkeypatch, cap, pages):
        monkeypatch.setattr(settings, "WEB_MAX_PAGES", cap)
        # The sync filled the tree from a config read before the pages were listed.
        return _website(
            pg_conn, {f"s{i}.md": _leaf(f"https://docs.x.io/s{i}", 5) for i in range(cap)},
            {"entries": [self.SITE, *_listing(*pages)["entries"]]}, sync_frequency="weekly",
        )

    def test_an_add_past_the_cap_queues_a_sync(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch, queued_sync,
    ):
        src = self._full(pg_conn, monkeypatch, 2, ["https://docs.x.io/p0"])
        pipeline["pages"]["https://docs.x.io/p0"] = "P0"

        result = run(task_self, src, "add", urls=["https://docs.x.io/p0"], actor_id=EDITOR)

        assert result == {"status": "ok", "pages": 0, "mode": "sync", "sync_task_id": "sync-1"}
        assert pipeline["fetch_calls"] == []
        assert sorted(_tree(pg_conn, src)) == ["s0.md", "s1.md"]
        kwargs = queued_sync.delay.call_args.kwargs
        assert kwargs["doc_id"] == str(src["id"]) and kwargs["loader"] == "website"
        assert kwargs["user"] == USER and kwargs["actor_id"] == EDITOR
        assert kwargs["sync_frequency"] == "weekly"
        assert [e["url"] for e in kwargs["source_data"]["entries"]] == ["https://docs.x.io/", "https://docs.x.io/p0"]
        kind, payload = pipeline["events"][-1]
        assert kind == "source.ingest.completed"
        assert payload["mode"] == "sync" and payload["sync_task_id"] == "sync-1" and payload["pages"] == 0
        # The open page can't know what the sync will change: no paths, so it reloads.
        assert "paths" not in payload

    def test_an_add_that_fits_is_appended(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch, queued_sync,
    ):
        src = self._full(pg_conn, monkeypatch, 2, ["https://docs.x.io/p0"])
        monkeypatch.setattr(settings, "WEB_MAX_PAGES", 3)
        pipeline["pages"]["https://docs.x.io/p0"] = "P0"

        result = run(task_self, src, "add", urls=["https://docs.x.io/p0"])

        assert result == {"status": "ok", "pages": 1, "paths": ["p0.md"]}
        assert "p0.md" in _tree(pg_conn, src)
        queued_sync.delay.assert_not_called()

    def test_a_page_the_tree_holds_already_is_replaced_in_place(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch, queued_sync,
    ):
        # It adds no page: the sync that filled the tree fetched it too.
        src = self._full(pg_conn, monkeypatch, 2, ["https://docs.x.io/s1"])
        pipeline["pages"]["https://docs.x.io/s1"] = "S1"

        result = run(task_self, src, "add", urls=["https://docs.x.io/s1"])

        assert result == {"status": "ok", "pages": 1, "paths": ["s1.md"]}
        queued_sync.delay.assert_not_called()

    @pytest.mark.parametrize("structure, count, extra_keys", [
        ({}, 3, set()),
        # A leaf without a url counts but has no key.
        ({"a.md": _leaf("https://docs.x.io/a", 1), "legacy.md": {"type": "t", "size_bytes": 1, "token_count": 1}}, 4, set()),
        # Two leaves for one page (a fragment) count once.
        ({"d": {"e": {"a.md": _leaf("https://docs.x.io/a", 1)}}, "a-2.md": _leaf("https://docs.x.io/a#x", 1)}, 3, set()),
        # The entry for an address that redirects to a leaf counts with the leaf.
        ({"new.md": {
            **_leaf("https://docs.x.io/new", 1),
            "requested_urls": ["https://docs.x.io/old-a", "https://docs.x.io/old-b", "https://docs.x.io/new/"],
        }}, 3, {"docs.x.io/new", "docs.x.io/old-a"}),
    ])
    def test_pages_are_counted_once_each(self, structure, count, extra_keys):
        from docsgpt.parser.remote.website_tree import held_pages

        config = {"entries": [
            self.SITE, {"url": "https://docs.x.io/a", "mode": "page"}, {"url": "https://docs.x.io/old-b", "mode": "page"},
            {"url": "https://docs.x.io/c", "mode": "page"},
        ]}

        held = held_pages(config, structure)
        assert held["count"] == count
        assert held["keys"] == {"docs.x.io/a", "docs.x.io/c", "docs.x.io/old-b"} | extra_keys

    def test_a_deep_tree_is_counted_without_recursion(self):
        from docsgpt.parser.remote.website_tree import held_pages

        tree = node = {}
        for depth in range(5000):
            node[f"d{depth}"] = {}
            node = node[f"d{depth}"]
        node["p.md"] = _leaf("https://docs.x.io/p", 1)

        assert held_pages({"entries": []}, tree)["count"] == 1


@pytest.mark.unit
class TestThePageCount:
    """Settings show ``metadata.website.pages``; page changes keep it to the tree."""

    def _with_report(self, pg_conn, src):
        SourcesRepository(pg_conn).set_metadata_key(
            str(src["id"]), USER, "website", {"pages": 99, "sites": [], "fetched_at": OLD},
        )

    def test_an_add_counts_the_new_page(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        self._with_report(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        report = _source_row(pg_conn, source)["metadata"]["website"]
        assert report["pages"] == 2 and report["fetched_at"] == OLD

    def test_a_removal_counts_the_pages_left(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        self._with_report(pg_conn, two_pages)
        run(task_self, two_pages, "remove", pages=[A])

        assert _source_row(pg_conn, two_pages)["metadata"]["website"]["pages"] == 1

    def test_a_source_without_a_report_gets_none(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert "website" not in (_source_row(pg_conn, source)["metadata"] or {})


@pytest.mark.unit
class TestAStoreWithoutChunkEdits:
    def test_fails_clearly_instead_of_reporting_success(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, monkeypatch,
    ):
        monkeypatch.setattr("docsgpt.worker.settings.VECTOR_STORE", "elasticsearch")
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="sync"):
            run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert pipeline["fetch_calls"] == []
        assert pipeline["events"][-1][0] == "source.ingest.failed"


@pytest.mark.unit
class TestConcurrentChanges:
    """Another change lands while the pages are fetched; neither is lost."""

    def test_a_tree_and_config_change_mid_task_survive(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        repo = SourcesRepository(pg_conn)
        changed_config = {**_listing("https://docs.x.io/a"), "skip": ["https://docs.x.io/z"]}

        def other_change():
            tree = dict(_tree(pg_conn, source))
            tree["z.md"] = _leaf("https://docs.x.io/z", 3)
            repo.update(str(source["id"]), USER, {"directory_structure": tree, "remote_data": changed_config})

        pipeline["during_fetch"].append(other_change)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        row = _source_row(pg_conn, source)
        assert sorted(row["directory_structure"]) == ["a.md", "b.md", "z.md"]
        assert row["remote_data"]["skip"] == ["https://docs.x.io/z"]
        assert int(row["tokens"]) == 40 + 3 + row["directory_structure"]["b.md"]["token_count"]

    def test_an_add_queued_before_a_removal_does_not_bring_the_page_back(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        # The removal took the lock first: /b left the config before the add ran.
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {
            "remote_data": _listing("https://docs.x.io/a", "https://docs.x.io/c"),
        })
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        pipeline["pages"]["https://docs.x.io/c#top"] = "C"
        result = run(task_self, source, "add", urls=["https://docs.x.io/b", "https://docs.x.io/c#top"])

        assert result["pages"] == 1
        assert pipeline["fetch_calls"][0][0] == ["https://docs.x.io/c#top"]
        assert sorted(_tree(pg_conn, source)) == ["a.md", "c.md"]

    def test_an_add_whose_pages_all_left_the_config_changes_nothing(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"remote_data": _listing("https://docs.x.io/a")})
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        result = run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert result["pages"] == 0
        assert pipeline["fetch_calls"] == []
        assert list(_tree(pg_conn, source)) == ["a.md"]
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    def test_a_removal_queued_before_a_re_add_leaves_the_page_listed_again(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        # Remove /a (entry dropped, task R queued), then add it back (entry
        # listed, task A queued); A takes the lock first. R must not take out
        # the page the config lists again.
        repo = SourcesRepository(pg_conn)
        src = _website(
            pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 5)},
            _listing("https://docs.x.io/a", "https://docs.x.io/b"),
        )
        repo.update(str(src["id"]), USER, {"remote_data": _listing("https://docs.x.io/b")})
        repo.update(str(src["id"]), USER, {"remote_data": _listing("https://docs.x.io/b", "https://docs.x.io/a")})
        pipeline["pages"]["https://docs.x.io/a"] = "fresh A"
        run(task_self, src, "add", urls=["https://docs.x.io/a"])

        result = run(task_self, src, "remove", pages=[{**A, "requested_urls": []}])

        assert result["pages"] == 0
        assert sorted(_tree(pg_conn, src)) == ["a.md", "b.md"]
        assert pipeline["store"].texts_for("https://docs.x.io/a") == ["fresh A"]

    def test_a_removal_takes_only_the_pages_the_config_no_longer_lists(
        self, pg_conn, patch_worker_db, task_self, pipeline,
    ):
        src = _website(
            pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 5)},
            _listing("https://docs.x.io/b"),
        )
        result = run(task_self, src, "remove", pages=[A, {"path": "b.md", "url": "https://docs.x.io/b"}])

        assert result["pages"] == 1
        assert sorted(_tree(pg_conn, src)) == ["b.md"]
        assert pipeline["store"].texts_for("https://docs.x.io/a") == []

    def test_a_page_removed_mid_refresh_is_not_brought_back(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        repo = SourcesRepository(pg_conn)
        pipeline["during_fetch"].append(
            lambda: repo.update(str(source["id"]), USER, {"directory_structure": {}, "tokens": "0"})
        )
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert _tree(pg_conn, source) == {}
        assert pipeline["store"].texts_for("https://docs.x.io/a") == []

    @pytest.mark.parametrize("operation, kwargs", [("add", {"urls": ["https://docs.x.io/b"]}), ("remove", {"pages": [A]})])
    def test_a_source_converted_to_a_wiki_is_left_alone(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, operation, kwargs,
    ):
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"config": {"kind": "wiki"}})
        _unlist(pg_conn, source, "https://docs.x.io/a")
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="wiki"):
            run(task_self, source, operation, **kwargs)

        assert pipeline["fetch_calls"] == []
        assert pipeline["store"].log == []

    def test_a_wiki_conversion_mid_task_drops_the_new_chunks(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        repo = SourcesRepository(pg_conn)
        pipeline["during_fetch"].append(lambda: repo.update(str(source["id"]), USER, {"config": {"kind": "wiki"}}))
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        with pytest.raises(ValueError, match="wiki"):
            run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert pipeline["store"].texts_for("https://docs.x.io/b") == []
        assert "b.md" not in _tree(pg_conn, source)

    @pytest.mark.parametrize("operation, kwargs, work", [
        ("add", {"urls": ["https://docs.x.io/b"]}, "fetching"),
        ("remove", {"pages": [A]}, "deleting"),
    ])
    def test_runs_holding_the_source_index_lock(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, held_lock, operation, kwargs, work,
    ):
        store = pipeline["store"]
        real_delete = store.delete_chunks
        store.delete_chunks = lambda ids: held_lock.append("deleting") or real_delete(ids)
        pipeline["during_fetch"].append(lambda: held_lock.append("fetching"))
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        _unlist(pg_conn, source, "https://docs.x.io/a")
        run(task_self, source, operation, **kwargs)

        assert held_lock == [str(source["id"]), work, "released"]


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
    from docsgpt.graphrag import store as graph_store

    fake = FakeGraph()
    queued = []
    monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: True)
    monkeypatch.setattr(graph_store, "GraphStore", lambda *a, **k: fake)
    monkeypatch.setattr(tasks.extract_graph, "delay", lambda *a, **k: queued.append((a, k)))
    return {"store": fake, "queued": queued}


def _make_graph(pg_conn, source):
    SourcesRepository(pg_conn).update(str(source["id"]), USER, {"config": {"kind": "graphrag"}})


def _refresh_a(task_self, source):
    return run(task_self, source, "refresh", file_path="a.md", url="https://docs.x.io/a")


@pytest.mark.unit
class TestAGraphSource:
    """A page change updates the graph by chunk instead of rebuilding it."""

    def test_a_refresh_drops_the_old_chunks_and_extracts_only_the_new(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        _make_graph(pg_conn, source)
        task_self.request.id = "task-g1"
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        _refresh_a(task_self, source)

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        # No reset: the rest of the graph stays, and only the page's new chunks are billed.
        assert graph["store"].reset == []
        [(args, kwargs)] = graph["queued"]
        assert args == (str(source["id"]), USER)
        assert "task-g1" in kwargs["idempotency_key"]
        new_ids = [cid for cid, c in pipeline["store"].chunks.items() if c["metadata"]["source"] == "https://docs.x.io/a"]
        assert kwargs["chunk_ids"] == new_ids

    def test_an_added_page_is_extracted(self, pg_conn, patch_worker_db, task_self, source, pipeline, graph):
        _make_graph(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"])

        assert graph["store"].deleted == []
        assert len(graph["queued"]) == 1

    def test_a_removal_drops_the_pages_chunks_without_extracting(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        _make_graph(pg_conn, source)
        SourcesRepository(pg_conn).update(str(source["id"]), USER, {"directory_structure": {
            "a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 1),
        }})
        _unlist(pg_conn, source, "https://docs.x.io/a")
        run(task_self, source, "remove", pages=[A])

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        assert graph["queued"] == []

    def test_a_graph_failure_leaves_the_page_change_done(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        _make_graph(pg_conn, source)
        graph["store"].fail = True
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        result = _refresh_a(task_self, source)

        assert result["pages"] == 1
        assert pipeline["store"].texts_for("https://docs.x.io/a") == ["New A"]
        # The graph is left as it was: nothing extracted on top of stale entries.
        assert graph["queued"] == []
        assert pipeline["events"][-1][0] == "source.ingest.completed"

    @pytest.mark.parametrize("graphrag_on", [True, False])
    def test_nothing_happens_without_a_graph(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch, graphrag_on,
    ):
        # A classic source has no graph; GraphRAG switched off leaves a graphrag source's alone.
        if not graphrag_on:
            monkeypatch.setattr("docsgpt.graphrag.graphrag_available", lambda: False)
            _make_graph(pg_conn, source)
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        _refresh_a(task_self, source)

        assert graph["store"].deleted == [] and graph["queued"] == []

    def test_a_removal_whose_tree_write_fails_still_drops_the_graph_entries(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch,
    ):
        # The chunks are gone once the delete succeeds, so a retry finds none
        # to name: the graph must drop them before the tree write can fail.
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

        _unlist(pg_conn, source, "https://docs.x.io/a")
        monkeypatch.setattr(SourcesRepository, "update", flaky_update)
        with pytest.raises(RuntimeError):
            run(task_self, source, "remove", pages=[A])
        run(task_self, source, "remove", pages=[A])

        assert graph["store"].deleted == [(str(source["id"]), ["old-1", "old-2"])]
        assert list(_tree(pg_conn, source)) == ["b.md"]

    def test_a_removal_whose_delete_fails_part_way_drops_the_deleted_chunks_from_the_graph(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph,
    ):
        _make_graph(pg_conn, source)
        store = pipeline["store"]
        real_delete = store.delete_chunks

        def delete_one(chunk_ids):
            real_delete(list(chunk_ids)[:1])
            return 1

        store.delete_chunks = delete_one
        _unlist(pg_conn, source, "https://docs.x.io/a")
        with pytest.raises(RuntimeError, match="could not be deleted"):
            run(task_self, source, "remove", pages=[A])

        assert graph["store"].deleted == [(str(source["id"]), ["old-1"])]
        assert "a.md" in _tree(pg_conn, source)

    def test_a_faiss_removal_whose_save_fails_keeps_the_graph(
        self, pg_conn, patch_worker_db, task_self, source, pipeline, graph, monkeypatch,
    ):
        # The loaded FAISS index dropped the chunks before its save failed; storage
        # still holds them, so the graph must not be told they are gone.
        import faiss
        import numpy as np

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
        store._paired_sidecar = None
        store.storage = MagicMock()
        store.storage.save_file.side_effect = OSError("S3 PutObject failed")
        monkeypatch.setattr(settings, "VECTOR_STORE", "faiss")
        monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)
        _unlist(pg_conn, source, url)

        with pytest.raises(OSError):
            run(task_self, source, "remove", pages=[A])

        assert graph["store"].deleted == []
        assert sorted(store.chunk_ids_by_source_paths([url])) == ["c1", "c2"]
        assert "a.md" in _tree(pg_conn, source)


@pytest.mark.unit
class TestAFailureBeforeTheRun:
    def test_a_failed_first_lookup_still_sends_a_terminal_event(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        # The UI waits on the task id from the route; it must hear that the task ended.
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
        with pytest.raises(ValueError, match="not found"):
            worker.website_pages_worker(
                task_self, "8c3c8d1e-7a39-4c3f-9d0e-2f1f6f0f9a11", USER, "remove", pages=[{"path": "a.md"}],
            )

        assert pipeline["events"].kinds() == ["source.ingest.failed"]
        assert pipeline["events"][0][1]["operation"] == "remove_pages"


@pytest.mark.unit
class TestTheCompletedEventNamesThePaths:
    """The open page reloads iff its path is in the completed event's ``paths``."""

    def _paths(self, pipeline):
        kind, payload = pipeline["events"][-1]
        assert kind == "source.ingest.completed"
        return payload.get("paths")

    def test_an_add_names_the_pages_added_and_replaced(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        pipeline["pages"]["https://docs.x.io/a"] = "New A"
        pipeline["pages"]["https://docs.x.io/guide/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/a", "https://docs.x.io/guide/b"])

        assert sorted(self._paths(pipeline)) == ["a.md", "guide/b.md"]

    def test_a_refresh_names_the_page_and_the_entry_it_replaced(
        self, pg_conn, patch_worker_db, task_self, pipeline, monkeypatch,
    ):
        # /a now redirects to /b, stored at b.md: the refresh replaces a.md's copy and drops b.md.
        src = _website(
            pg_conn, {"a.md": _leaf("https://docs.x.io/a", 40), "b.md": _leaf("https://docs.x.io/b", 2)},
            _listing("https://docs.x.io/a"),
        )
        _redirecting_loader(monkeypatch, pipeline, {"https://docs.x.io/a": "https://docs.x.io/b"})
        run(task_self, src, "refresh", file_path="a.md", url="https://docs.x.io/a")

        assert list(_tree(pg_conn, src)) == ["a.md"]
        assert sorted(self._paths(pipeline)) == ["a.md", "b.md"]

    def test_a_removal_names_the_pages_removed(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        run(task_self, two_pages, "remove", pages=[B])

        assert self._paths(pipeline) == ["guide/b.md"]


@pytest.mark.unit
class TestATeamEditorHearsIt:
    """The route runs the change as the owner; the editor who asked (``actor_id``) gets its events too."""

    def test_every_event_goes_to_the_owner_and_the_editor(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"], actor_id=EDITOR)

        assert pipeline["events"].recipients("source.ingest.queued") == sorted([USER, EDITOR])
        assert pipeline["events"].recipients("source.ingest.completed") == sorted([USER, EDITOR])

    def test_a_failure_goes_to_both(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        with pytest.raises(ValueError):
            run(task_self, source, "add", urls=["https://docs.x.io/b"], actor_id=EDITOR)

        assert pipeline["events"].recipients("source.ingest.failed") == sorted([USER, EDITOR])

    @pytest.mark.parametrize("actor", [None, USER])
    def test_the_owner_alone_hears_it_once(self, pg_conn, patch_worker_db, task_self, source, pipeline, actor):
        pipeline["pages"]["https://docs.x.io/b"] = "B"
        run(task_self, source, "add", urls=["https://docs.x.io/b"], actor_id=actor)

        assert set(pipeline["events"].users) == {USER}
        assert pipeline["events"].recipients("source.ingest.completed") == [USER]
