"""Query embedding runs on the worker so the API holds no model."""

from unittest.mock import MagicMock, patch

import pytest

from application.vectorstore import base
from application.vectorstore.embeddings_delegated import EMBED_TASK, DelegatedEmbeddings


@pytest.fixture(autouse=True)
def _clear_singleton():
    base.EmbeddingsSingleton._instances.clear()
    yield
    base.EmbeddingsSingleton._instances.clear()


@pytest.fixture
def not_in_worker():
    with patch("application.vectorstore.embeddings_delegated._in_worker", return_value=False):
        yield


class TestDispatch:
    def test_query_is_embedded_on_the_worker(self, not_in_worker):
        celery = MagicMock()
        celery.send_task.return_value.get.return_value = [[0.1, 0.2, 0.3]]
        with patch("application.celery_init.celery", celery):
            vector = DelegatedEmbeddings("some/model").embed_query("hello")
        assert vector == [0.1, 0.2, 0.3]
        assert celery.send_task.call_args.args[0] == EMBED_TASK
        assert celery.send_task.call_args.kwargs["args"] == [["hello"], "some/model"]

    def test_routed_to_the_embeddings_queue(self, not_in_worker):
        celery = MagicMock()
        celery.send_task.return_value.get.return_value = [[0.0]]
        with patch("application.celery_init.celery", celery):
            with patch.object(base.settings, "EMBEDDINGS_QUEUE", "embeddings"):
                DelegatedEmbeddings("some/model").embed_query("hi")
        assert celery.send_task.call_args.kwargs["queue"] == "embeddings"

    def test_no_worker_gives_an_actionable_error(self, not_in_worker):
        celery = MagicMock()
        celery.send_task.return_value.get.side_effect = TimeoutError("no worker")
        with patch("application.celery_init.celery", celery):
            with pytest.raises(RuntimeError) as excinfo:
                DelegatedEmbeddings("some/model").embed_query("hi")
        message = str(excinfo.value)
        assert "EMBEDDINGS_DELEGATE_TO_WORKER=false" in message
        assert "EMBEDDINGS_BASE_URL" in message

    def test_empty_input_never_reaches_the_broker(self, not_in_worker):
        celery = MagicMock()
        with patch("application.celery_init.celery", celery):
            assert DelegatedEmbeddings("some/model").embed_documents([]) == []
        celery.send_task.assert_not_called()


class TestInsideAWorker:
    """Dispatching from inside a task would queue work behind itself."""

    def test_a_running_task_embeds_locally(self):
        local = MagicMock()
        local.embed_documents.return_value = [[1.0, 2.0]]
        celery = MagicMock()
        with patch("application.vectorstore.embeddings_delegated._in_worker", return_value=True):
            with patch("application.vectorstore.base.build_local_embeddings", return_value=local):
                with patch("application.celery_init.celery", celery):
                    vector = DelegatedEmbeddings("some/model").embed_query("hi")
        assert vector == [1.0, 2.0]
        celery.send_task.assert_not_called()

    def test_the_local_model_is_built_once(self):
        local = MagicMock()
        local.embed_documents.return_value = [[1.0]]
        builder = MagicMock(return_value=local)
        client = DelegatedEmbeddings("some/model")
        with patch("application.vectorstore.embeddings_delegated._in_worker", return_value=True):
            with patch("application.vectorstore.base.build_local_embeddings", builder):
                client.embed_query("a")
                client.embed_query("b")
        builder.assert_called_once()


class TestDimension:
    def test_registry_width_costs_no_round_trip(self):
        celery = MagicMock()
        with patch("application.celery_init.celery", celery):
            client = DelegatedEmbeddings("ibm-granite/granite-embedding-311m-multilingual-r2")
            assert client.dimension == 768
        celery.send_task.assert_not_called()

    def test_unknown_width_is_probed_once(self, not_in_worker):
        celery = MagicMock()
        celery.send_task.return_value.get.return_value = [[0.0] * 1024]
        with patch("application.celery_init.celery", celery):
            client = DelegatedEmbeddings("some/unregistered")
            assert client.dimension == 1024
            assert client.dimension == 1024
        celery.send_task.assert_called_once()

    def test_an_unreachable_worker_reports_no_width(self, not_in_worker):
        celery = MagicMock()
        celery.send_task.return_value.get.side_effect = TimeoutError("down")
        with patch("application.celery_init.celery", celery):
            assert DelegatedEmbeddings("some/unregistered").dimension is None


class TestGetEmbeddingsDispatch:
    def test_delegates_when_enabled(self):
        with patch.object(base.settings, "EMBEDDINGS_BASE_URL", None):
            with patch.object(base.settings, "EMBEDDINGS_DELEGATE_TO_WORKER", True):
                assert isinstance(base.get_embeddings("some/model"), DelegatedEmbeddings)

    def test_remote_url_wins_over_delegation(self):
        with patch.object(base.settings, "EMBEDDINGS_BASE_URL", "http://embed.local"):
            with patch.object(base.settings, "EMBEDDINGS_DELEGATE_TO_WORKER", True):
                assert isinstance(base.get_embeddings("some/model"), base.RemoteEmbeddings)

    def test_disabled_loads_in_process(self):
        with patch.object(base.settings, "EMBEDDINGS_BASE_URL", None):
            with patch.object(base.settings, "EMBEDDINGS_DELEGATE_TO_WORKER", False):
                with patch.object(base.EmbeddingsSingleton, "get_instance") as get_instance:
                    base.get_embeddings("some/model")
        get_instance.assert_called_once()

    def test_the_delegating_client_is_shared(self):
        with patch.object(base.settings, "EMBEDDINGS_BASE_URL", None):
            with patch.object(base.settings, "EMBEDDINGS_DELEGATE_TO_WORKER", True):
                assert base.get_embeddings("some/model") is base.get_embeddings("some/model")
