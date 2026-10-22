"""Tests for ``website_pages_worker``: adding pages to and refreshing a page of a Website source."""

from unittest.mock import MagicMock

import pytest

from docsgpt.parser.schema.base import Document
from docsgpt.storage.db.repositories.sources import SourcesRepository

USER = "u-pages"
OLD = "2026-01-01T00:00:00+00:00"


def _leaf(url, tokens, title="Old"):
    return {"type": "text/markdown", "size_bytes": 10, "token_count": tokens, "url": url, "title": title, "fetched_at": OLD}


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

    store = MagicMock(name="store")
    store.add_chunk.side_effect = lambda text, metadata=None: f"chunk-{store.add_chunk.call_count}"
    monkeypatch.setattr(vector_creator.VectorCreator, "create_vectorstore", lambda *a, **k: store)

    pages = {}
    fetch_calls = []

    def fake_load(self, inputs):
        fetch_calls.append((list(inputs), self.keep_links))
        return [
            Document(pages[url], extra_info={"source": url, "title": f"Title {url[-1]}", "file_path": "ignored.md"})
            for url in inputs if url in pages
        ]

    monkeypatch.setattr(web_loader.WebLoader, "load_data", fake_load)
    events = []
    monkeypatch.setattr(worker, "publish_user_event", lambda user, kind, payload, **kw: events.append((kind, payload)))
    return {"store": store, "pages": pages, "fetch_calls": fetch_calls, "events": events}


def _source_row(pg_conn, source):
    return SourcesRepository(pg_conn).get(str(source["id"]), USER)


@pytest.mark.unit
class TestAddPages:
    def test_appends_pages_without_touching_the_others(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/guide/b"] = "# B\nBody of page B with enough words to chunk."
        result = worker.website_pages_worker(
            task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/guide/b"],
        )

        assert result["pages"] == 1
        # The source's keep_links setting reaches the fetch.
        assert pipeline["fetch_calls"] == [(["https://docs.x.io/guide/b"], True)]
        pipeline["store"].delete_index.assert_not_called()
        added = pipeline["store"].add_chunk.call_args_list
        assert added and all(call.kwargs["metadata"]["source"] == "https://docs.x.io/guide/b" for call in added)
        assert added[0].kwargs["metadata"]["file_path"] == "guide/b.md"

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

    def test_adding_a_page_already_there_replaces_it(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "# A\nThe new text of page A."
        worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/a"])

        pipeline["store"].delete_chunks_by_source_path.assert_called_once_with("https://docs.x.io/a")
        tree = _source_row(pg_conn, source)["directory_structure"]
        assert list(tree) == ["a.md"]
        assert tree["a.md"]["fetched_at"] != OLD

    def test_a_page_that_cannot_be_fetched_fails_and_changes_nothing(
        self, pg_conn, patch_worker_db, task_self, source, pipeline,
    ):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "add", urls=["https://docs.x.io/gone"])

        pipeline["store"].add_chunk.assert_not_called()
        assert _source_row(pg_conn, source)["directory_structure"] == {"a.md": _leaf("https://docs.x.io/a", 40)}
        assert pipeline["events"][-1][0] == "source.ingest.failed"


@pytest.mark.unit
class TestRefreshPage:
    def test_refetches_one_page_in_place(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        pipeline["pages"]["https://docs.x.io/a"] = "# A\nRefreshed text for page A."
        result = worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        assert result["pages"] == 1
        pipeline["store"].delete_chunks_by_source_path.assert_called_once_with("https://docs.x.io/a")
        assert all(c.kwargs["metadata"]["file_path"] == "a.md" for c in pipeline["store"].add_chunk.call_args_list)
        leaf = _source_row(pg_conn, source)["directory_structure"]["a.md"]
        assert leaf["title"] == "Title a"
        assert leaf["fetched_at"] != OLD

    def test_a_failed_refresh_keeps_the_old_content(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="a.md")

        pipeline["store"].delete_chunks_by_source_path.assert_not_called()
        assert _source_row(pg_conn, source)["directory_structure"]["a.md"]["fetched_at"] == OLD

    def test_an_unknown_path_is_an_error(self, pg_conn, patch_worker_db, task_self, source, pipeline):
        from docsgpt import worker

        with pytest.raises(ValueError):
            worker.website_pages_worker(task_self, str(source["id"]), USER, "refresh", file_path="nope.md")
