"""Short-lived cache for delegated query embeddings.

A repeated question (retries, polls, shared rephrased queries) should not pay
another broker round trip while the worker is healthy. Only successful embeds
are cached; failures always propagate and never poison the cache.
"""

from unittest.mock import MagicMock, patch

import pytest

from docsgpt.vectorstore import base
from docsgpt.vectorstore.embeddings_delegated import DelegatedEmbeddings


@pytest.fixture(autouse=True)
def _clear_singleton():
    base.EmbeddingsSingleton._instances.clear()
    yield
    base.EmbeddingsSingleton._instances.clear()


@pytest.fixture
def not_in_worker():
    with patch("docsgpt.vectorstore.embeddings_delegated._in_worker", return_value=False):
        yield


def _celery_with(vectors):
    celery = MagicMock()
    celery.send_task.return_value.get.return_value = vectors
    return celery


@pytest.mark.unit
class TestQueryCache:
    def test_repeat_query_dispatches_once(self, not_in_worker):
        celery = _celery_with([[0.1, 0.2]])
        with patch("docsgpt.celery_init.celery", celery):
            client = DelegatedEmbeddings("some/model")
            assert client.embed_query("hello") == [0.1, 0.2]
            assert client.embed_query("hello") == [0.1, 0.2]
        celery.send_task.assert_called_once()

    def test_distinct_queries_each_dispatch(self, not_in_worker):
        celery = _celery_with([[0.1], [0.2]])
        with patch("docsgpt.celery_init.celery", celery):
            client = DelegatedEmbeddings("some/model")
            client.embed_query("a")
            client.embed_query("b")
        assert celery.send_task.call_count == 2

    def test_failures_are_not_cached(self, not_in_worker, monkeypatch):
        import docsgpt.vectorstore.embeddings_delegated as delegated

        # Let the retry dispatch immediately: the 30s fail-fast cooldown would
        # otherwise (by design) reject the second call without dispatching.
        monkeypatch.setattr(delegated, "_FAILURE_COOLDOWN", 0.0)
        celery = MagicMock()
        celery.send_task.return_value.get.side_effect = [
            TimeoutError("no worker"),
            [[0.5]],
        ]
        with patch("docsgpt.celery_init.celery", celery):
            client = DelegatedEmbeddings("some/model")
            with pytest.raises(RuntimeError):
                client.embed_query("hi")
            assert client.embed_query("hi") == [0.5]
        assert celery.send_task.call_count == 2

    def test_cache_is_per_model(self, not_in_worker):
        celery = _celery_with([[0.1], [0.2]])
        with patch("docsgpt.celery_init.celery", celery):
            DelegatedEmbeddings("model/a").embed_query("hi")
            DelegatedEmbeddings("model/b").embed_query("hi")
        assert celery.send_task.call_count == 2

    def test_expired_entry_dispatches_again(self, not_in_worker, monkeypatch):
        import docsgpt.vectorstore.embeddings_delegated as delegated

        monkeypatch.setattr(delegated, "_QUERY_CACHE_TTL", 0.0)
        celery = _celery_with([[0.1], [0.2]])
        with patch("docsgpt.celery_init.celery", celery):
            client = DelegatedEmbeddings("some/model")
            client.embed_query("hi")
            client.embed_query("hi")
        assert celery.send_task.call_count == 2
