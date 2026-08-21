from unittest.mock import patch

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

    assert DURABLE_TASK["retry_backoff"] == 30
    # Leaving a ``countdown`` in would only document a value celery discards.
    assert "countdown" not in DURABLE_TASK["retry_kwargs"]

    seen: list[dict] = []

    class _Task:
        max_retries = DURABLE_TASK["retry_kwargs"]["max_retries"]

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
        retry_kwargs=dict(DURABLE_TASK["retry_kwargs"]),
        retry_backoff=DURABLE_TASK["retry_backoff"],
    )

    ceilings = []
    for attempt in range(DURABLE_TASK["retry_kwargs"]["max_retries"]):
        task.request.retries = attempt
        with pytest.raises(RuntimeError, match="retry-sentinel"):
            task.run()
        ceilings.append(30 * 2**attempt)
        # full jitter: the wait is drawn from [0, factor * 2**retries].
        assert 0 <= seen[-1]["countdown"] <= ceilings[-1]

    # 30 / 60 / 120 — an envelope that can actually outlast a multi-minute
    # blip, versus the 1 / 2 / 4 the old settings produced.
    assert ceilings == [30, 60, 120]
    assert sum(ceilings) >= 200
