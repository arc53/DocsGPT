"""Query embedding runs on the worker so the API holds no model."""

import threading
import time
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


class TestFailureCooldown:
    """One dead-worker timeout per retrieval, not one per source.

    ``fanout.embed_questions`` swallows a dispatch failure and lets every store
    embed its own query, so without a latch a single chat request pays
    ``EMBEDDINGS_DELEGATE_TIMEOUT`` once in the fan-out and again per source.
    A missing worker is a property of the deployment, not of the call.
    """

    @staticmethod
    def _celery(side_effect):
        result = MagicMock()
        result.get.side_effect = side_effect
        celery = MagicMock()
        celery.send_task.return_value = result
        return celery, result

    def test_only_the_first_call_waits_out_the_timeout(self, not_in_worker):
        celery, _ = self._celery(TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            for _ in range(4):
                with pytest.raises(RuntimeError):
                    embeddings.embed_query("q")
        assert celery.send_task.call_count == 1

    def test_the_fast_failure_still_names_the_remedy(self, not_in_worker):
        celery, _ = self._celery(TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            with pytest.raises(RuntimeError):
                embeddings.embed_query("q")
            with pytest.raises(RuntimeError, match="EMBEDDINGS_DELEGATE_TO_WORKER=false"):
                embeddings.embed_query("q")

    def test_the_latch_clears_once_the_worker_answers(self, not_in_worker):
        celery, result = self._celery(TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            with pytest.raises(RuntimeError):
                embeddings.embed_query("q")
            embeddings._failed_at = None  # stand in for the cooldown elapsing
            result.get.side_effect = None
            result.get.return_value = [[0.5, 0.5]]
            assert embeddings.embed_query("q") == [0.5, 0.5]
        assert embeddings._cooldown_remaining() == 0.0

    def test_a_healthy_worker_is_never_latched(self, not_in_worker):
        celery, result = self._celery(None)
        result.get.return_value = [[0.1, 0.2]]
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            for _ in range(3):
                assert embeddings.embed_query("q") == [0.1, 0.2]
        assert celery.send_task.call_count == 3


class TestTheConcurrentFirstWave:
    """The latch cannot cover requests already in flight beside the first one.

    Nothing is latched until that first ``get()`` returns, so every thread in
    the opening wave would otherwise block for the full
    ``EMBEDDINGS_DELEGATE_TIMEOUT`` at once -- at the shipped 60s across a 96
    thread WSGI pool, an API that serves nothing at all.
    """

    @staticmethod
    def _blocking_celery(release, outcome):
        """A worker whose ``get`` blocks until ``release`` is set."""
        def get(timeout=None):
            release.wait(5)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        result = MagicMock()
        result.get.side_effect = get
        celery = MagicMock()
        celery.send_task.return_value = result
        return celery

    def _race(self, celery, embeddings, release, threads=8):
        """Start ``threads`` embeds, let them pile up, then unblock the prober."""
        errors, values = [], []
        started = threading.Barrier(threads + 1)

        def call():
            started.wait(5)
            try:
                values.append(embeddings.embed_query("q"))
            except Exception as exc:  # noqa: BLE001 -- recorded for the assertions
                errors.append(exc)

        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            workers = [threading.Thread(target=call) for _ in range(threads)]
            for worker in workers:
                worker.start()
            started.wait(5)
            time.sleep(0.1)  # let the followers reach the probe gate
            release.set()
            for worker in workers:
                worker.join(10)
        return values, errors

    def test_only_one_caller_waits_on_an_unproven_worker(self, not_in_worker):
        release = threading.Event()
        celery = self._blocking_celery(release, TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch(
            "application.vectorstore.embeddings_delegated._PROBE_WAIT", 0.05
        ):
            values, errors = self._race(celery, embeddings, release)

        assert values == []
        assert len(errors) == 8
        # One probe published; the rest gave up without their own round trip.
        assert celery.send_task.call_count == 1
        assert sum("still unanswered" in str(e) for e in errors) == 7

    def test_the_fast_failure_still_names_the_remedy(self, not_in_worker):
        release = threading.Event()
        celery = self._blocking_celery(release, TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch("application.vectorstore.embeddings_delegated._PROBE_WAIT", 0.05):
            _, errors = self._race(celery, embeddings, release, threads=3)
        assert all("EMBEDDINGS_DELEGATE_TO_WORKER=false" in str(e) for e in errors)

    def test_a_healthy_worker_serves_the_whole_wave(self, not_in_worker):
        release = threading.Event()
        celery = self._blocking_celery(release, [[0.1, 0.2]])
        embeddings = DelegatedEmbeddings("granite-311m")
        values, errors = self._race(celery, embeddings, release)

        assert errors == []
        assert values == [[0.1, 0.2]] * 8
        # The probe proves the worker, then every follower dispatches for real.
        assert celery.send_task.call_count == 8
        assert embeddings._verified is True

    def test_a_proven_worker_adds_no_gate(self, not_in_worker):
        """After one success the probe is out of the path entirely."""
        release = threading.Event()
        release.set()
        celery = self._blocking_celery(release, [[0.3]])
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            embeddings.embed_query("warm")
        assert embeddings._verified is True

        with patch.object(embeddings, "_state_lock") as lock:
            with patch.dict(
                "sys.modules", {"application.celery_init": MagicMock(celery=celery)}
            ):
                embeddings.embed_query("q")
            lock.__enter__.assert_not_called()


class TestTheResultIsForgotten:
    """A query vector must not outlive the query that asked for it.

    ``result_expires`` is 7 days and ``embed_texts`` stores its result, but the
    key is ``celery-task-meta-<uuid>`` -- minted per dispatch, never derived
    from the text -- so nothing reads it back and a repeated query mints
    another. Without ``forget()`` every search leaks ~17 KB into the Redis the
    broker shares for a week.
    """

    @staticmethod
    def _celery(side_effect=None, value=None):
        result = MagicMock()
        result.get.side_effect = side_effect
        result.get.return_value = value
        celery = MagicMock()
        celery.send_task.return_value = result
        return celery, result

    def test_a_successful_embed_forgets_its_result(self, not_in_worker):
        celery, result = self._celery(value=[[0.1, 0.2]])
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            assert embeddings.embed_query("q") == [0.1, 0.2]
        result.forget.assert_called_once()

    def test_a_failed_embed_still_forgets(self, not_in_worker):
        celery, result = self._celery(side_effect=TimeoutError("no worker"))
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            with pytest.raises(RuntimeError):
                embeddings.embed_query("q")
        result.forget.assert_called_once()

    def test_a_backend_that_cannot_delete_does_not_fail_the_query(self, not_in_worker):
        celery, result = self._celery(value=[[0.3, 0.4]])
        result.forget.side_effect = ConnectionError("backend down")
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            assert embeddings.embed_query("q") == [0.3, 0.4]

    def test_forgetting_does_not_mask_the_dispatch_failure(self, not_in_worker):
        celery, result = self._celery(side_effect=TimeoutError("no worker"))
        result.forget.side_effect = ConnectionError("backend down")
        embeddings = DelegatedEmbeddings("granite-311m")
        with patch.dict("sys.modules", {"application.celery_init": MagicMock(celery=celery)}):
            with pytest.raises(RuntimeError, match="timed out or failed"):
                embeddings.embed_query("q")
