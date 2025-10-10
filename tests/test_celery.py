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
