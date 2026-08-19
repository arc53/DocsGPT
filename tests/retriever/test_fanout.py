"""Unit tests for the shared multi-source fan-out helpers.

``application/retriever/fanout.py`` holds the pieces both ClassicRAG and the
search service reuse: the worker cap, the single query embedding, and the
order-preserving pool runner. These tests pin them directly, independent of
either caller.
"""

import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from application.retriever.fanout import (
    DEFAULT_MAX_PARALLEL_SOURCES,
    embed_questions,
    max_parallel_sources,
    run_source_jobs,
    store_embeddings,
)


@pytest.mark.unit
class TestMaxParallelSources:
    def _cap(self, n_sources, configured=None):
        stub = SimpleNamespace()
        if configured is not None:
            stub.RETRIEVAL_MAX_PARALLEL_SOURCES = configured
        return max_parallel_sources(n_sources, stub)

    def test_default_when_setting_missing(self):
        assert self._cap(10) == DEFAULT_MAX_PARALLEL_SOURCES

    def test_never_more_workers_than_sources(self):
        assert self._cap(2) == 2

    def test_setting_is_honoured(self):
        assert self._cap(10, configured=8) == 8

    def test_floor_is_one(self):
        assert self._cap(10, configured=0) == 1
        assert self._cap(10, configured=-5) == 1

    def test_garbage_setting_falls_back_to_default(self):
        assert self._cap(10, configured="lots") == DEFAULT_MAX_PARALLEL_SOURCES
        assert self._cap(10, configured=None) == DEFAULT_MAX_PARALLEL_SOURCES

    def test_zero_sources_still_returns_one(self):
        assert self._cap(0) == 1

    def test_falls_back_to_module_settings(self, monkeypatch):
        import application.retriever.fanout as fanout

        monkeypatch.setattr(
            fanout, "settings", SimpleNamespace(RETRIEVAL_MAX_PARALLEL_SOURCES=3)
        )
        assert fanout.max_parallel_sources(10) == 3


@pytest.mark.unit
class TestRunSourceJobs:
    def test_empty_jobs_returns_empty(self):
        assert run_source_jobs(Mock(side_effect=AssertionError), []) == []

    def test_preserves_job_order(self):
        import time

        delays = {"a": 0.06, "b": 0.0, "c": 0.0}

        def _fn(job):
            time.sleep(delays[job])
            return job.upper()

        assert run_source_jobs(_fn, ["a", "b", "c"], workers=3) == ["A", "B", "C"]

    def test_jobs_run_concurrently(self):
        """The barrier only clears if three jobs overlap; a serial loop hangs."""
        barrier = threading.Barrier(3, timeout=10)

        def _fn(job):
            barrier.wait()
            return job

        assert run_source_jobs(_fn, [1, 2, 3], workers=3) == [1, 2, 3]

    def test_single_job_runs_inline(self):
        main_thread = threading.current_thread().name
        seen = []

        def _fn(job):
            seen.append(threading.current_thread().name)
            return job

        assert run_source_jobs(_fn, ["only"]) == ["only"]
        assert seen == [main_thread]

    def test_one_worker_runs_inline(self):
        main_thread = threading.current_thread().name
        seen = []

        def _fn(job):
            seen.append(threading.current_thread().name)
            return job

        run_source_jobs(_fn, ["a", "b"], workers=1)
        assert seen == [main_thread, main_thread]

    def test_worker_count_defaults_to_the_cap(self):
        with patch(
            "application.retriever.fanout.max_parallel_sources", return_value=1
        ) as cap:
            run_source_jobs(lambda job: job, ["a", "b", "c"])
        cap.assert_called_once_with(3)

    def test_accepts_any_iterable_of_jobs(self):
        assert run_source_jobs(lambda job: job * 2, iter([1, 2])) == [2, 4]


@pytest.mark.unit
class TestStoreEmbeddings:
    def test_finds_private_embedding_attribute(self):
        embedder = Mock()
        embedder.embed_query = Mock(return_value=[1.0])
        store = SimpleNamespace(_embedding=embedder)
        assert store_embeddings(store) is embedder

    def test_probes_attributes_in_order(self):
        first = Mock()
        first.embed_query = Mock()
        second = Mock()
        second.embed_query = Mock()
        store = SimpleNamespace(_embedding=first, _embeddings=second)
        assert store_embeddings(store) is first

    def test_skips_attributes_without_embed_query(self):
        embedder = Mock(spec=["embed_query"])
        store = SimpleNamespace(_embedding=object(), embeddings=embedder)
        assert store_embeddings(store) is embedder

    def test_falls_back_to_get_embeddings(self):
        embedder = Mock()
        store = SimpleNamespace(
            _embedding=None, _get_embeddings=Mock(return_value=embedder)
        )
        assert store_embeddings(store) is embedder

    def test_returns_none_when_nothing_is_reachable(self):
        store = SimpleNamespace(_embedding=None)
        assert store_embeddings(store) is None

    def test_get_embeddings_failure_returns_none(self):
        store = SimpleNamespace(
            _embedding=None, _get_embeddings=Mock(side_effect=RuntimeError("boom"))
        )
        assert store_embeddings(store) is None


@pytest.mark.unit
class TestEmbedQuestions:
    def test_embeds_each_distinct_question_once(self):
        embedder = Mock()
        embedder.embed_query = Mock(side_effect=lambda q: [len(q)])
        store = SimpleNamespace(_embedding=embedder)

        assert embed_questions(store, ["ab", "cde"]) == {"ab": [2], "cde": [3]}
        assert embedder.embed_query.call_count == 2

    def test_no_embedder_returns_empty_map(self):
        assert embed_questions(SimpleNamespace(_embedding=None), ["q"]) == {}

    def test_embedding_failure_returns_empty_map(self):
        embedder = Mock()
        embedder.embed_query = Mock(side_effect=RuntimeError("model down"))
        store = SimpleNamespace(_embedding=embedder)
        assert embed_questions(store, ["q"]) == {}
