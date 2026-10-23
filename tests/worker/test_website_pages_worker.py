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

    def chunk_ids_by_source_paths(self, paths):
        wanted = set(paths)
        return [cid for cid, c in self.chunks.items() if c["metadata"].get("source") in wanted]

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


@pytest.fixture
def source(pg_conn):
    return SourcesRepository(pg_conn).create(
        "Docs",
        user_id=USER,
        type="website",
        remote_data={"entries": [{"url": "https://docs.x.io/a", "mode": "page"}], "keep_links": True},
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
        # The new copy is stored before the old one goes.
        kinds = [kind for kind, _ in store.log]
        assert kinds == ["add", "add", "delete", "delete"]
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
            remote_data={"entries": [{"url": "https://docs.x.io/", "mode": "site"}]},
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
            remote_data={"entries": [{"url": "https://docs.x.io/docs", "mode": "page"}]},
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

    def test_a_wiki_is_left_alone(self, pg_conn, patch_worker_db, task_self, two_pages, pipeline):
        from docsgpt import worker

        SourcesRepository(pg_conn).update(str(two_pages["id"]), USER, {"config": {"kind": "wiki"}})
        with pytest.raises(ValueError, match="wiki"):
            worker.website_pages_worker(task_self, str(two_pages["id"]), USER, "remove", file_paths=["a.md"])

        assert pipeline["store"].log == []


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
        # No reset: the rest of the graph stays, and only unextracted chunks are billed.
        assert graph["store"].reset == []
        [(args, kwargs)] = graph["queued"]
        assert args == (str(source["id"]), USER)
        assert "task-g1" in kwargs["idempotency_key"]

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
