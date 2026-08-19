"""Unit tests for application/services/search_service.py.

Tests exercise the service function in isolation — AgentsRepository is
stubbed via a patched ``db_readonly`` context manager, and
``VectorCreator.create_vectorstore`` is patched to return a fake
vectorstore. No Flask app context, no real DB, no real embeddings.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from application.services.search_service import (
    InvalidAPIKey,
    SearchFailed,
    _authorized_source_ids,
    _collect_source_ids,
    search,
)


@contextmanager
def _fake_db_readonly(agent_data):
    """Patch ``db_readonly`` so ``AgentsRepository.find_by_key`` returns ``agent_data``."""
    agents_repo = MagicMock()
    agents_repo.find_by_key.return_value = agent_data

    @contextmanager
    def _yield_conn():
        yield MagicMock()

    with patch(
        "application.api.user.team_sharing.can_access", return_value=True
    ), patch(
        "application.services.search_service.db_readonly", _yield_conn
    ), patch(
        "application.services.search_service.AgentsRepository",
        return_value=agents_repo,
    ):
        yield


@pytest.mark.unit
class TestCollectSourceIds:
    def test_empty_when_no_sources(self):
        assert _collect_source_ids({}) == []

    def test_returns_extra_source_ids(self):
        agent = {"extra_source_ids": ["s1", "s2"], "source_id": "legacy"}
        assert _collect_source_ids(agent) == ["s1", "s2"]

    def test_falls_back_to_single_source_id(self):
        agent = {"extra_source_ids": [], "source_id": "s1"}
        assert _collect_source_ids(agent) == ["s1"]

    def test_skips_empty_entries_in_extra(self):
        agent = {"extra_source_ids": ["", None, "s1"], "source_id": "fallback"}
        assert _collect_source_ids(agent) == ["s1"]


@pytest.mark.unit
class TestSearchInvalidAPIKey:
    def test_raises_when_key_unknown(self):
        with _fake_db_readonly(None):
            with pytest.raises(InvalidAPIKey):
                search("does-not-exist", "hello", 5)

    def test_raises_search_failed_on_db_error(self):
        @contextmanager
        def _yield_conn():
            yield MagicMock()

        agents_repo = MagicMock()
        agents_repo.find_by_key.side_effect = RuntimeError("db down")

        with patch(
            "application.services.search_service.db_readonly", _yield_conn
        ), patch(
            "application.services.search_service.AgentsRepository",
            return_value=agents_repo,
        ):
            with pytest.raises(SearchFailed):
                search("any-key", "hello", 5)


@pytest.mark.unit
class TestSearchEmptyWhenNoSources:
    def test_returns_empty_when_agent_has_no_sources(self):
        with _fake_db_readonly(
            {"extra_source_ids": [], "source_id": None, "user_id": "owner"}
        ):
            assert search("k", "q", 5) == []

    def test_returns_empty_for_zero_chunks_without_db_lookup(self):
        with patch("application.services.search_service.db_readonly") as mock_db:
            assert search("k", "q", 0) == []
        mock_db.assert_not_called()

    def test_returns_empty_for_negative_chunks_without_db_lookup(self):
        with patch("application.services.search_service.db_readonly") as mock_db:
            assert search("k", "q", -1) == []
        mock_db.assert_not_called()


@pytest.mark.unit
class TestSearchResults:
    def test_returns_hit_shape(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {
                "text": "Test content",
                "metadata": {"title": "Test Title", "source": "/path/to/doc"},
            }
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results == [
            {"text": "Test content", "title": "Test Title", "source": "/path/to/doc"}
        ]

    def test_handles_langchain_document_format(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        lc_doc = MagicMock()
        lc_doc.page_content = "Langchain content"
        lc_doc.metadata = {"title": "LC Title", "source": "/lc/path"}

        fake_vs = MagicMock()
        fake_vs.search.return_value = [lc_doc]

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 1
        assert results[0]["text"] == "Langchain content"
        assert results[0]["title"] == "LC Title"

    def test_respects_chunks_cap(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        docs = [
            {"text": f"Content {i}", "metadata": {"title": f"T{i}"}}
            for i in range(10)
        ]
        fake_vs = MagicMock()
        fake_vs.search.return_value = docs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 3)
        assert len(results) == 3

    def test_deduplicates_results_by_content_prefix(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        dup_text = "Duplicate content " * 20
        docs = [
            {"text": dup_text, "metadata": {"title": "T1"}},
            {"text": dup_text, "metadata": {"title": "T2"}},
            {"text": "Unique content", "metadata": {"title": "T3"}},
        ]
        fake_vs = MagicMock()
        fake_vs.search.return_value = docs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 2

    def test_skips_broken_source_and_returns_from_healthy_ones(self):
        # Two sources — the first raises, the second returns a doc. The
        # caller should still get the healthy source's result.
        agent = {
            "extra_source_ids": ["broken", "ok"],
            "source_id": None,
            "user_id": "owner",
        }
        healthy_vs = MagicMock()
        healthy_vs.search.return_value = [
            {"text": "ok content", "metadata": {"title": "Ok"}}
        ]

        def create_vs(store, source_id, key):
            if source_id == "broken":
                raise RuntimeError("vector index missing")
            return healthy_vs

        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            side_effect=create_vs,
        ):
            results = search("k", "q", 5)
        assert len(results) == 1
        assert results[0]["text"] == "ok content"

    def test_uses_filename_when_title_missing(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "body", "metadata": {"filename": "document.pdf"}}
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results[0]["title"] == "document.pdf"

    def test_uses_content_snippet_as_title_last_resort(self):
        agent = {"source_id": "src-1", "extra_source_ids": [], "user_id": "owner"}
        fake_vs = MagicMock()
        fake_vs.search.return_value = [
            {"text": "Content without any title metadata at all", "metadata": {}}
        ]
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            return_value=fake_vs,
        ):
            results = search("k", "q", 5)
        assert results[0]["title"].endswith("...")
        assert "Content without any title" in results[0]["title"]

    def test_skips_empty_source_ids(self):
        # ``source_id=" "`` only — after strip() this leaves no real source.
        agent = {"extra_source_ids": ["  ", ""], "source_id": None}
        with _fake_db_readonly(agent), patch(
            "application.services.search_service.VectorCreator.create_vectorstore"
        ) as mock_create:
            results = search("k", "q", 5)
        mock_create.assert_not_called()
        assert results == []


@pytest.mark.unit
class TestSourceAuthorization:
    """Source ids stored on an agent row are re-resolved, not trusted.

    ``/api/share`` used to resolve a client-supplied source with no ownership
    predicate and bake it into the agent it created; this service then searched
    it and returned another tenant's documents. The share route is fixed, but a
    row written before that — or by any future write path with the same gap —
    would still be live here.
    """

    def _agent(self, **kw):
        return {"id": "agent-1", "user_id": "owner", "extra_source_ids": [], **kw}

    def test_readable_sources_pass_through(self, monkeypatch):
        import application.api.user.team_sharing as ts

        monkeypatch.setattr(ts, "can_access", lambda *a, **k: True)
        agent = self._agent(extra_source_ids=["s1", "s2"])
        assert _authorized_source_ids(None, agent, ["s1", "s2"]) == ["s1", "s2"]

    def test_foreign_source_is_dropped(self, monkeypatch):
        import application.api.user.team_sharing as ts

        monkeypatch.setattr(ts, "can_access", lambda conn, k, sid, u: sid == "mine")
        agent = self._agent()
        assert _authorized_source_ids(None, agent, ["mine", "theirs"]) == ["mine"]

    def test_team_shared_source_is_kept(self, monkeypatch):
        """A grant is legitimate access; only unreadable ids are dropped."""
        import application.api.user.team_sharing as ts

        monkeypatch.setattr(ts, "can_access", lambda *a, **k: True)
        agent = self._agent(user_id="grantee")
        assert _authorized_source_ids(None, agent, ["shared"]) == ["shared"]

    def test_agent_without_owner_searches_nothing(self):
        agent = {"id": "agent-1", "extra_source_ids": ["s1"]}
        assert _authorized_source_ids(None, agent, ["s1"]) == []

    def test_check_failure_fails_closed(self, monkeypatch):
        import application.api.user.team_sharing as ts

        def _boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(ts, "can_access", _boom)
        assert _authorized_source_ids(None, self._agent(), ["s1"]) == []


def _serial_search_sources(query, source_ids, chunks):
    """The pre-fan-out ``_search_sources``, kept as a parity oracle."""
    from application.services.search_service import VectorCreator, settings

    if chunks <= 0 or not source_ids:
        return []

    results = []
    chunks_per_source = max(1, chunks // len(source_ids))
    seen_texts = set()

    for source_id in source_ids:
        if not source_id or not source_id.strip():
            continue
        try:
            docsearch = VectorCreator.create_vectorstore(
                settings.VECTOR_STORE, source_id, settings.EMBEDDINGS_KEY
            )
            docs = docsearch.search(query, k=chunks_per_source * 2)
            for doc in docs:
                if len(results) >= chunks:
                    break
                if hasattr(doc, "page_content") and hasattr(doc, "metadata"):
                    page_content = doc.page_content
                    metadata = doc.metadata
                else:
                    page_content = doc.get("text", doc.get("page_content", ""))
                    metadata = doc.get("metadata", {})
                text_hash = hash(page_content[:200])
                if text_hash in seen_texts:
                    continue
                seen_texts.add(text_hash)
                title = metadata.get("title", metadata.get("post_title", ""))
                if not isinstance(title, str):
                    title = str(title) if title else ""
                if title:
                    title = title.split("/")[-1]
                else:
                    title = metadata.get("filename", page_content[:50] + "...")
                source = metadata.get("source", source_id)
                results.append(
                    {"text": page_content, "title": title, "source": source}
                )
            if len(results) >= chunks:
                break
        except Exception:
            continue

    return results[:chunks]


def _make_embedder(vector=(0.1, 0.2, 0.3)):
    embedder = MagicMock()
    embedder.embed_query = MagicMock(return_value=list(vector))
    return embedder


def _make_store(embedder, docs=None):
    store = MagicMock()
    store._embedding = embedder
    store.search.return_value = list(docs or [])
    return store


def _no_embedder_store(docs=None):
    """A store exposing no reachable embeddings object."""
    store = MagicMock()
    store._embedding = None
    store._embeddings = None
    store.embeddings = None
    store._get_embeddings = MagicMock(side_effect=AttributeError("nope"))
    store.search.return_value = list(docs or [])
    return store


def _run_search_sources(query, source_ids, chunks, stores, serial=False):
    """Run ``_search_sources`` (or its serial oracle) against ``stores``."""
    from application.services import search_service

    impl = _serial_search_sources if serial else search_service._search_sources
    with patch(
        "application.services.search_service.VectorCreator.create_vectorstore",
        side_effect=lambda _type, source_id, _key: stores[source_id],
    ):
        return impl(query, source_ids, chunks)


@pytest.mark.unit
class TestSearchSourcesFanOut:
    """Multi-source search: one query embedding, one bounded fan-out."""

    def test_query_is_embedded_once_across_three_sources(self):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b", "c")
        }

        results = _run_search_sources("q", ["a", "b", "c"], 5, stores)

        assert len(results) == 3
        embedder.embed_query.assert_called_once_with("q")

    def test_every_store_receives_the_same_vector(self):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b", "c")
        }

        _run_search_sources("q", ["a", "b", "c"], 5, stores)

        vectors = [
            store.search.call_args.kwargs["query_vector"] for store in stores.values()
        ]
        assert vectors == [[0.1, 0.2, 0.3]] * 3

    def test_k_per_source_is_unchanged(self):
        embedder = _make_embedder()
        stores = {src: _make_store(embedder) for src in ("a", "b", "c")}

        _run_search_sources("q", ["a", "b", "c"], 6, stores)

        for store in stores.values():
            assert store.search.call_args.kwargs["k"] == 4

    def test_output_matches_the_serial_implementation(self):
        """Parity: order, dedupe and the ``chunks`` cap are byte-identical."""
        duplicate = "shared chunk " * 30

        def _stores():
            embedder = _make_embedder()
            return {
                "a": _make_store(
                    embedder,
                    [
                        {"text": "a-0", "metadata": {"title": "A0", "source": "/a0"}},
                        {"text": duplicate, "metadata": {"title": "dup"}},
                        {"text": "a-2", "metadata": {"filename": "a2.pdf"}},
                    ],
                ),
                "b": _make_store(
                    embedder,
                    [
                        {"text": duplicate, "metadata": {"title": "dup again"}},
                        {"text": "b-1", "metadata": {}},
                    ],
                ),
                "c": _make_store(
                    embedder,
                    [
                        {"text": "c-0", "metadata": {"post_title": "x/y/C0"}},
                        {"text": "c-1", "metadata": {"title": 42}},
                    ],
                ),
            }

        for chunks in (1, 3, 5, 6, 12):
            serial = _run_search_sources("q", ["a", "b", "c"], chunks, _stores(), serial=True)
            parallel = _run_search_sources("q", ["a", "b", "c"], chunks, _stores())
            assert parallel == serial, f"mismatch at chunks={chunks}"

    def test_langchain_documents_match_the_serial_implementation(self):
        def _stores():
            embedder = _make_embedder()
            stores = {}
            for src in ("a", "b"):
                doc = MagicMock()
                doc.page_content = f"content {src}"
                doc.metadata = {"title": f"path/to/{src}", "source": f"/{src}"}
                stores[src] = _make_store(embedder, [doc])
            return stores

        serial = _run_search_sources("q", ["a", "b"], 4, _stores(), serial=True)
        parallel = _run_search_sources("q", ["a", "b"], 4, _stores())
        assert parallel == serial
        assert [r["title"] for r in parallel] == ["a", "b"]

    def test_results_keep_source_order_when_a_slow_source_is_first(self):
        import time

        embedder = _make_embedder()
        delays = {"a": 0.06, "b": 0.0, "c": 0.0}

        def _factory(src):
            def _search(*_args, **_kwargs):
                time.sleep(delays[src])
                return [{"text": f"hit {src}", "metadata": {}}]

            return _search

        stores = {}
        for src in ("a", "b", "c"):
            store = _make_store(embedder)
            store.search.side_effect = _factory(src)
            stores[src] = store

        results = _run_search_sources("q", ["a", "b", "c"], 6, stores)

        assert [r["text"] for r in results] == ["hit a", "hit b", "hit c"]

    def test_sources_are_searched_concurrently(self):
        """The barrier only clears if three searches overlap."""
        import threading

        barrier = threading.Barrier(3, timeout=10)
        embedder = _make_embedder()

        def _factory(src):
            def _search(*_args, **_kwargs):
                barrier.wait()
                return [{"text": f"hit {src}", "metadata": {}}]

            return _search

        stores = {}
        for src in ("a", "b", "c"):
            store = _make_store(embedder)
            store.search.side_effect = _factory(src)
            stores[src] = store

        results = _run_search_sources("q", ["a", "b", "c"], 6, stores)

        assert [r["text"] for r in results] == ["hit a", "hit b", "hit c"]

    def test_single_source_skips_the_pool(self):
        import threading

        main_thread = threading.current_thread().name
        seen = []
        embedder = _make_embedder()
        store = _make_store(embedder)
        store.search.side_effect = lambda *_a, **_k: (
            seen.append(threading.current_thread().name),
            [{"text": "only", "metadata": {}}],
        )[1]

        results = _run_search_sources("q", ["a"], 5, {"a": store})

        assert [r["text"] for r in results] == ["only"]
        assert seen == [main_thread]

    def test_one_failing_search_does_not_kill_the_others(self):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b", "c")
        }
        stores["b"].search.side_effect = RuntimeError("index missing")

        results = _run_search_sources("q", ["a", "b", "c"], 6, stores)

        assert [r["text"] for r in results] == ["hit a", "hit c"]

    def test_failing_first_store_does_not_kill_the_others(self):
        embedder = _make_embedder()
        stores = {
            src: _make_store(embedder, [{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b", "c")
        }

        def _create(_type, source_id, _key):
            if source_id == "a":
                raise RuntimeError("connection failed")
            return stores[source_id]

        from application.services import search_service

        with patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            side_effect=_create,
        ):
            results = search_service._search_sources("q", ["a", "b", "c"], 6)

        assert [r["text"] for r in results] == ["hit b", "hit c"]

    def test_no_embedder_means_no_query_vector_kwarg(self):
        stores = {
            src: _no_embedder_store([{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b")
        }

        results = _run_search_sources("q", ["a", "b"], 6, stores)

        assert [r["text"] for r in results] == ["hit a", "hit b"]
        for store in stores.values():
            assert "query_vector" not in store.search.call_args.kwargs

    def test_embedding_failure_falls_back_to_per_store_embedding(self):
        embedder = MagicMock()
        embedder.embed_query = MagicMock(side_effect=RuntimeError("model down"))
        stores = {
            src: _make_store(embedder, [{"text": f"hit {src}", "metadata": {}}])
            for src in ("a", "b")
        }

        results = _run_search_sources("q", ["a", "b"], 6, stores)

        assert [r["text"] for r in results] == ["hit a", "hit b"]
        for store in stores.values():
            assert "query_vector" not in store.search.call_args.kwargs

    def test_blank_source_ids_are_skipped_but_still_split_the_budget(self):
        """Blank ids build no store, yet ``chunks_per_source`` counts them."""
        embedder = _make_embedder()
        stores = {"a": _make_store(embedder, [{"text": "hit a", "metadata": {}}])}

        from application.services import search_service

        with patch(
            "application.services.search_service.VectorCreator.create_vectorstore",
            side_effect=lambda _t, source_id, _k: stores[source_id],
        ):
            results = search_service._search_sources("q", ["  ", "a", ""], 6)

        assert [r["text"] for r in results] == ["hit a"]
        assert stores["a"].search.call_args.kwargs["k"] == 4

    def test_all_blank_source_ids_build_no_store(self):
        from application.services import search_service

        with patch(
            "application.services.search_service.VectorCreator.create_vectorstore"
        ) as mock_create:
            assert search_service._search_sources("q", ["  ", ""], 5) == []
        mock_create.assert_not_called()

    def test_zero_chunks_short_circuits(self):
        from application.services import search_service

        with patch(
            "application.services.search_service.VectorCreator.create_vectorstore"
        ) as mock_create:
            assert search_service._search_sources("q", ["a"], 0) == []
        mock_create.assert_not_called()
