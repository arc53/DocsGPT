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
