from unittest.mock import MagicMock, patch

import pytest
from application.celery_init import make_celery
from application.core.settings import settings


@pytest.mark.unit
@patch("application.celery_init.Celery")
def test_make_celery(mock_celery):
    app_name = "test_app_name"

    celery = make_celery(app_name)

    mock_celery.assert_called_once_with(
        app_name,
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
    )
    celery.conf.update.assert_called_once_with(settings)
    assert celery == mock_celery.return_value


@pytest.mark.unit
def test_celeryconfig_durability_defaults():
    from application import celeryconfig

    assert celeryconfig.task_acks_late is True
    assert celeryconfig.task_reject_on_worker_lost is True
    assert celeryconfig.worker_prefetch_multiplier == settings.CELERY_WORKER_PREFETCH_MULTIPLIER
    assert celeryconfig.worker_prefetch_multiplier == 1
    assert celeryconfig.broker_transport_options == {
        "visibility_timeout": settings.CELERY_VISIBILITY_TIMEOUT
    }
    # 1h matches Onyx/Dify defaults; long enough for ingest, short enough
    # that a SIGKILLed task redelivers within the same operator session.
    assert celeryconfig.broker_transport_options["visibility_timeout"] == 3600
    assert celeryconfig.result_expires == 86400 * 7
    assert celeryconfig.task_track_started is True
    # Project-scoped queue prevents a sibling worker on the same broker
    # from grabbing DocsGPT tasks.
    assert celeryconfig.task_default_queue == "docsgpt"


@pytest.mark.unit
def test_durable_task_retry_envelope_spans_a_multi_minute_outage():
    """``retry_backoff`` is a FACTOR, not a boolean toggle.

    Celery's ``add_autoretry_behaviour`` overwrites
    ``retry_kwargs["countdown"]`` whenever ``retry_backoff`` is truthy
    (celery/app/autoretry.py). With ``retry_backoff=True`` the factor is
    ``int(max(1.0, True)) == 1``, so the declared 60 s countdown never reached
    ``task.retry`` and the three waits were jittered 0-1 s, 0-2 s and 0-4 s —
    a whole envelope of at most 7 seconds, which a 3.5-minute network blip
    (2026-08-21) exhausted immediately. On exhaustion these tasks publish a
    terminal ``source.ingest.failed`` / ``attachment.failed``, so the user sees
    a permanent failure caused by a transient one.
    """
    from unittest.mock import MagicMock

    from celery.app.autoretry import add_autoretry_behaviour

    from application.api.user.tasks import DURABLE_TASK

    assert DURABLE_TASK["retry_backoff"] == 60
    # ``retry_kwargs`` must stay absent: celery captures it by reference and
    # writes ``countdown`` into it on every retry, so one dict shared across
    # every decorator would race and would mutate the module constant.
    assert "retry_kwargs" not in DURABLE_TASK
    assert DURABLE_TASK["max_retries"] == 3

    seen: list[dict] = []

    class _Task:
        max_retries = DURABLE_TASK["max_retries"]

        def __init__(self) -> None:
            self.request = MagicMock()

        def run(self):
            raise ConnectionError("Network is unreachable")

        def retry(self, **kwargs):
            seen.append(dict(kwargs))
            return RuntimeError("retry-sentinel")

    task = _Task()
    add_autoretry_behaviour(
        task,
        autoretry_for=DURABLE_TASK["autoretry_for"],
        retry_kwargs={"max_retries": DURABLE_TASK["max_retries"]},
        retry_backoff=DURABLE_TASK["retry_backoff"],
    )

    ceilings = []
    for attempt in range(DURABLE_TASK["max_retries"]):
        task.request.retries = attempt
        with pytest.raises(RuntimeError, match="retry-sentinel"):
            task.run()
        ceilings.append(DURABLE_TASK["retry_backoff"] * 2**attempt)
        # full jitter: the wait is drawn from [0, factor * 2**retries].
        assert 0 <= seen[-1]["countdown"] <= ceilings[-1]

    # 60 / 120 / 240 ceilings, versus the 1 / 2 / 4 the old settings produced.
    assert ceilings == [60, 120, 240]

    # Full jitter means the ceilings are not the waits, so pin the
    # DISTRIBUTION rather than the nominal sum: asserting only
    # ``0 <= countdown <= ceiling`` passes even when every draw is 0.
    import statistics

    from celery.utils.time import get_exponential_backoff_interval

    envelopes = [
        sum(
            get_exponential_backoff_interval(
                factor=DURABLE_TASK["retry_backoff"],
                retries=attempt,
                maximum=600,
                full_jitter=True,
            )
            for attempt in range(DURABLE_TASK["max_retries"])
        )
        for _ in range(2000)
    ]
    # Median envelope is half the 420 s nominal; a wide margin keeps this
    # from flaking while still failing if the factor or jitter regresses.
    assert 150 <= statistics.median(envelopes) <= 270
    # A 60 s outage must be survivable in the large majority of retry runs.
    assert sum(e >= 60 for e in envelopes) / len(envelopes) > 0.9


@pytest.mark.unit
def test_durable_tasks_never_retry_a_deterministic_parse_failure():
    """The widened envelope needs ``dont_autoretry_for`` as its counterweight.

    ``autoretry_for=(Exception,)`` retries EVERYTHING, so raising the backoff
    factor to 60 also stretched permanent failures — an empty, image-only or
    unparseable file — from a ~7 s envelope to a median 3.5 min and up to ~7.
    Anything polling ``/api/task_status`` (the wiki-convert and GraphRAG-enable
    modals) reports "pending" for that whole time, and the work re-runs four
    times to fail identically. ``e2e specs/tier-b/upload.spec.ts`` went red on
    exactly this.
    """
    from unittest.mock import MagicMock

    from celery.app.autoretry import add_autoretry_behaviour

    from application.api.user.tasks import DURABLE_TASK
    from application.parser.file.base_parser import DocumentParseError

    assert DocumentParseError in DURABLE_TASK["dont_autoretry_for"]

    retried: list[dict] = []

    class _Task:
        max_retries = DURABLE_TASK["max_retries"]

        def __init__(self) -> None:
            self.request = MagicMock()
            self.request.retries = 0

        def run(self):
            raise DocumentParseError("No text could be extracted from this file.")

        def retry(self, **kwargs):
            retried.append(dict(kwargs))
            return RuntimeError("retry-sentinel")

    task = _Task()
    add_autoretry_behaviour(
        task,
        autoretry_for=DURABLE_TASK["autoretry_for"],
        dont_autoretry_for=DURABLE_TASK["dont_autoretry_for"],
        retry_kwargs={"max_retries": DURABLE_TASK["max_retries"]},
        retry_backoff=DURABLE_TASK["retry_backoff"],
    )

    # Propagates unchanged to the poison/failure path instead of being
    # swallowed into a retry.
    with pytest.raises(DocumentParseError):
        task.run()
    assert retried == []


@pytest.mark.unit
def test_every_durable_task_carries_the_parse_failure_guard():
    """Registered tasks, not just the shared dict — a decorator can override it.

    ``store_attachment`` passes a wider tuple through ``durable_task()``; the
    point is that no durable task ends up with a NARROWER one, which is how
    seven of the nine came to retry a permanent parse failure four times.
    """
    from application.api.user import tasks as user_tasks
    from application.parser.file.base_parser import DocumentParseError

    durable = (
        "ingest",
        "ingest_remote",
        "reingest_source_task",
        "reembed_wiki_page",
        "convert_source_to_wiki",
        "extract_graph",
        "process_agent_webhook",
        "ingest_connector_task",
        "store_attachment",
    )
    for name in durable:
        task = getattr(user_tasks, name)
        assert DocumentParseError in getattr(task, "dont_autoretry_for", ()), name


@pytest.mark.unit
def test_unparseable_file_raises_the_non_retryable_type():
    """The guard is only reachable if the pipeline raises the right class.

    This used to be a bare ``ValueError``, which ``autoretry_for=(Exception,)``
    swept up regardless of the ``dont_autoretry_for`` tuple.
    """
    from application.parser.embedding_pipeline import embed_and_store_documents
    from application.parser.file.base_parser import DocumentParseError

    with pytest.raises(DocumentParseError, match="No text could be extracted"):
        embed_and_store_documents([], "/tmp", "src", None)


@pytest.mark.unit
class TestReclaimIsSkippedForEmbeds:
    """The post-task heap reclaim must not run on the query hot path.

    ``_reclaim_memory_after_task`` exists for the large transient allocations
    docling/torch parsing makes. Query embedding became a Celery task, and a
    full generational collect on a worker holding the ONNX model measured ~86 ms
    against ~8 ms for the embed itself -- a 9x slowdown of the round trip for a
    task that allocates a few kilobytes.
    """

    @staticmethod
    def _collects(task_name):
        from application.celery_init import _reclaim_memory_after_task

        task = MagicMock()
        task.name = task_name
        with patch("application.celery_init.gc.collect") as collect, patch(
            "application.celery_init._trim_native_heap"
        ):
            _reclaim_memory_after_task(task=task, task_id="t", state="SUCCESS")
        return collect.called

    def test_the_embed_task_is_skipped(self):
        assert not self._collects("application.vectorstore.embeddings_tasks.embed_texts")

    def test_parsing_still_reclaims(self):
        assert self._collects("application.api.user.tasks.parse_document")

    def test_ingest_still_reclaims(self):
        assert self._collects("application.api.user.tasks.ingest")

    def test_an_unnamed_sender_still_reclaims(self):
        """Unknown callers keep the old behaviour rather than silently skipping."""
        from application.celery_init import _reclaim_memory_after_task

        with patch("application.celery_init.gc.collect") as collect, patch(
            "application.celery_init._trim_native_heap"
        ):
            _reclaim_memory_after_task(task_id="t", state="SUCCESS")
        assert collect.called

    def test_the_skip_list_names_the_real_task(self):
        """A renamed task must not silently start paying the collect again."""
        from application.celery_init import _NO_RECLAIM_TASKS
        from application.vectorstore.embeddings_delegated import EMBED_TASK

        assert EMBED_TASK in _NO_RECLAIM_TASKS
